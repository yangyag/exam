"""진도: 세션·슬롯(사이클 라운드·회차 연습·모의고사)과 문항별 상태(북마크·메모·복습 예정일)."""
from __future__ import annotations

from datetime import date
from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import cycles, grading
from ..deps import Conn, require_token
from ..queries import STATE_COLUMNS, fetch_questions, question_filters, to_question
from ..schemas import (
    ProgressItem,
    SessionCreate,
    SessionDetailOut,
    SessionItemDetail,
    SessionItemOut,
    SessionMode,
    SessionOut,
    SlotAnswerRequest,
    SlotGradeResult,
    SlotSaveOut,
    StateOut,
    StateUpdate,
)

router = APIRouter(prefix="/api", tags=["progress"])

SESSION_SELECT = """
SELECT s.id, s.mode, s.exam_id, s.subject_code, s.cycle_id, s.round_no, s.end_reason,
       s.started_at, s.finished_at,
       coalesce(a.answered, 0) AS answered,
       coalesce(a.correct, 0) AS correct
  FROM ipe.study_session s
  LEFT JOIN LATERAL (
       SELECT count(*)::int AS answered,
              count(*) FILTER (WHERE at.is_correct)::int AS correct
         FROM ipe.study_attempt at
        WHERE at.session_id = s.id
  ) a ON true
"""

PROGRESS_SELECT = """
SELECT q.id AS question_id, q.exam_id, q.number, q.subject_code,
       sj.name AS subject_name, q.stem,
       st.attempt_count, st.correct_count, st.wrong_count, st.last_is_correct, st.last_choice_no,
       st.last_answered_at, st.streak, st.bookmarked, st.note, st.review_due_on, st.updated_at
  FROM ipe.study_state st
  JOIN ipe.question q ON q.id = st.question_id
  JOIN ipe.subject sj ON sj.code = q.subject_code
"""

STATE_INSERT_SQL = f"""
INSERT INTO ipe.study_state (question_id, bookmarked, note, review_due_on)
VALUES (%s, coalesce(%s, false), %s, %s)
ON CONFLICT (question_id) DO UPDATE SET {{assignments}}, updated_at = now()
RETURNING {STATE_COLUMNS}
"""


def _get_session(conn: Conn, session_id: int) -> dict:
    row = conn.execute(f"{SESSION_SELECT} WHERE s.id = %s", (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"세션 {session_id} 를 찾을 수 없습니다")
    return row


def _ensure_question(conn: Conn, question_id: str) -> None:
    if not conn.execute("SELECT 1 FROM ipe.question WHERE id = %s", (question_id,)).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")


@router.post(
    "/sessions",
    response_model=SessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="세션 시작",
    dependencies=[Depends(require_token)],
)
def create_session(payload: SessionCreate, conn: Conn):
    """mode: exam_practice(회차 연습)·exam(모의고사)·random(랜덤).

    - exam_practice·exam 은 회차의 문항 번호 순으로 슬롯(study_session_item)을 만든다.
      같은 모드·회차의 진행 중 세션이 있으면 409 이고, replaceActive=true 면 그 세션을
      abandoned 로 닫고 같은 트랜잭션에서 새로 만든다(설계 5.3절).
    - subject·review 는 사이클 API 로만 만들 수 있다(400).
    - random 은 기존대로 슬롯 없이 만든다.
    """
    if payload.mode in ("subject", "review"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"mode={payload.mode} 세션은 사이클 API(/api/subject-cycles)로만 만들 수 있습니다",
        )
    if payload.mode in ("exam", "exam_practice") and not payload.exam_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"mode={payload.mode} 세션에는 examId 가 필요합니다"
        )
    if payload.exam_id and not conn.execute(
        "SELECT 1 FROM ipe.exam WHERE id = %s", (payload.exam_id,)
    ).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"회차 {payload.exam_id} 를 찾을 수 없습니다")
    if payload.subject_code is not None and not conn.execute(
        "SELECT 1 FROM ipe.subject WHERE code = %s", (payload.subject_code,)
    ).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"과목 {payload.subject_code} 를 찾을 수 없습니다")

    if payload.mode in ("exam", "exam_practice"):
        question_ids = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM ipe.question WHERE exam_id = %s ORDER BY number, id",
                (payload.exam_id,),
            ).fetchall()
        ]
        if not question_ids:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"회차 {payload.exam_id} 에 문항이 없습니다"
            )
        try:
            with conn.transaction():
                cycles.replace_open_exam_session(
                    conn,
                    mode=payload.mode,
                    exam_id=payload.exam_id,
                    replace_active=payload.replace_active,
                )
                session_id = cycles.create_round_session(
                    conn,
                    mode=payload.mode,
                    exam_id=payload.exam_id,
                    question_ids=question_ids,
                )
        except psycopg.errors.UniqueViolation as exc:
            # 동시 생성 경합: study_session_exam_open_uk 가 두 번째 INSERT 를 막는다(설계 4.6절).
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"이미 진행 중인 {payload.mode} 세션이 있습니다. replaceActive=true 로 새로 구성하세요",
            ) from exc
        return _get_session(conn, session_id)

    row = conn.execute(
        "INSERT INTO ipe.study_session (mode, exam_id, subject_code) VALUES (%s, %s, %s) RETURNING id",
        (payload.mode, payload.exam_id, payload.subject_code),
    ).fetchone()
    return _get_session(conn, row["id"])


@router.get("/sessions", response_model=list[SessionOut], summary="세션 목록")
def list_sessions(
    conn: Conn,
    mode: Annotated[SessionMode | None, Query()] = None,
    cycle_id: Annotated[int | None, Query(alias="cycleId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """mode·cycleId 로 거를 수 있다(설계 5.4절)."""
    clauses: list[str] = []
    params: list = []
    if mode:
        clauses.append("s.mode = %s")
        params.append(mode)
    if cycle_id is not None:
        clauses.append("s.cycle_id = %s")
        params.append(cycle_id)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"{SESSION_SELECT}{where} ORDER BY s.started_at DESC, s.id DESC LIMIT %s OFFSET %s"
    return conn.execute(sql, [*params, limit, offset]).fetchall()


@router.post(
    "/sessions/{session_id}/finish",
    response_model=SessionOut,
    summary="세션 종료",
    dependencies=[Depends(require_token)],
)
def finish_session(session_id: int, conn: Conn):
    """세션을 끝낸다(end_reason='finished'). 이미 끝난 세션을 다시 부르면 현재 상태를 그대로 돌려준다(멱등).

    슬롯이 있는 세션은 409 다 — 연습은 마지막 문항에서 자동으로 끝나고 모의고사는 최종 제출을 쓴다.
    세션 행을 FOR UPDATE 로 먼저 잠가 채점과의 순서를 지킨다(B-01).
    """
    with conn.transaction():
        session = grading.lock_session(conn, session_id)
        if grading.session_has_slots(conn, session_id):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "슬롯 세션은 이 경로로 끝낼 수 없습니다. 연습은 마지막 문항에서 자동 종료되고 모의고사는 최종 제출을 쓰세요",
            )
        if session["finished_at"] is None:
            # finished_at 과 end_reason 을 함께 채워야 새 CHECK 를 통과한다(db/003_study_items.sql).
            conn.execute(
                "UPDATE ipe.study_session SET finished_at = now(), end_reason = 'finished' WHERE id = %s",
                (session_id,),
            )
    return _get_session(conn, session_id)


def _question_row(conn: Conn, question_id: str) -> dict:
    """슬롯 문항 조회용 행. study_state(state)는 뺀다 — 이전 풀이 결과가 드러나지 않게."""
    where, params = question_filters(question_id=question_id)
    rows = fetch_questions(conn, where=where, params=params, limit=1)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")
    row = dict(rows[0])
    row["state"] = None
    return row


def _slot_grade_response(conn: Conn, session: dict, result) -> SlotGradeResult:
    """채점 결과에 세션 진행·라운드·사이클 상태를 붙인다(설계 5.3절)."""
    return SlotGradeResult(
        **result.model_dump(),
        session=cycles.session_progress(conn, session),
        round_result=cycles.round_result(conn, session),
        cycle=cycles.cycle_result(conn, session),
    )


@router.get("/sessions/{session_id}", response_model=SessionDetailOut, summary="세션 단건(슬롯 목록·진행)")
def get_session(session_id: int, conn: Conn):
    """세션 요약 + 슬롯 목록 + 진행 위치(nextSeq). 슬롯이 없는 랜덤 세션이면 items 가 빈 목록이다.

    진행 중인 모의고사는 isCorrect 를 null 로 가린다(제출 전 정답 비공개). 조회는 기록을 남기지 않는다.
    """
    session = _get_session(conn, session_id)
    progress = cycles.session_progress(conn, session)
    reveal = not (session["mode"] == "exam" and session["finished_at"] is None)
    items = [
        SessionItemOut(
            seq=slot["seq"],
            question_id=slot["question_id"],
            choice_no=slot["choice_no"],
            is_correct=slot["is_correct"] if reveal else None,
        )
        for slot in cycles.fetch_slots(conn, session_id)
    ]
    return SessionDetailOut(
        **session,
        item_count=progress.item_count,
        answered_count=progress.answered_count,
        next_seq=progress.next_seq,
        items=items,
    )


@router.get(
    "/sessions/{session_id}/items/{seq}",
    response_model=SessionItemDetail,
    summary="세션 문항(슬롯) 단건",
)
def get_session_item(session_id: int, seq: int, conn: Conn):
    """슬롯 문항 1개. 채점된 슬롯이면 result 에 채점 응답과 같은 형식이 붙는다.

    채점 전 슬롯은 QuestionOut.state 를 빼서 이전 풀이의 정답 여부가 드러나지 않게 한다.
    조회는 원장(study_attempt)을 늘리지 않는다.
    """
    _get_session(conn, session_id)
    slot = cycles.fetch_slot(conn, session_id, seq)
    result = None
    if slot["is_correct"] is not None:
        result = grading.build_grade_result(
            conn,
            question_id=slot["question_id"],
            choice_no=slot["choice_no"],
            is_correct=slot["is_correct"],
        )
    question = to_question(_question_row(conn, slot["question_id"]))
    return SessionItemDetail(
        **question.model_dump(),
        seq=slot["seq"],
        choice_no=slot["choice_no"],
        is_correct=slot["is_correct"],
        answered_at=slot["answered_at"],
        result=result,
    )


@router.put(
    "/sessions/{session_id}/items/{seq}/answer",
    response_model=SlotGradeResult | SlotSaveOut,
    summary="슬롯 답안 제출(연습 즉시 채점·모의고사 선택 저장)",
    dependencies=[Depends(require_token)],
)
def answer_session_item(session_id: int, seq: int, payload: SlotAnswerRequest, conn: Conn):
    """연습 슬롯은 즉시 채점하고, 모의고사 슬롯은 선택만 저장한다.

    - 연습: 같은 보기 재전송은 기록 없이 저장된 결과로 200, 다른 보기는 409.
    - 모의고사: choiceNo=null 은 선택 해제. 정답·해설은 최종 제출 전까지 돌려주지 않는다.
    - 잠금 순서는 세션 → 슬롯 → 사이클이다(설계 4.6절).
    """
    with conn.transaction():
        session = grading.lock_session(conn, session_id)
        slot = cycles.lock_slot(conn, session_id, seq)

        if session["mode"] == "exam":
            if session["finished_at"] is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "이미 제출된 모의고사입니다. 결과는 세션 조회로 확인하세요"
                )
            saved = cycles.save_slot_choice(conn, session_id, seq, payload.choice_no)
            return SlotSaveOut(
                seq=seq, choice_no=saved["choice_no"], answered_at=saved["answered_at"]
            )

        if payload.choice_no is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "연습 슬롯에는 choiceNo 가 필요합니다")
        if slot["is_correct"] is not None:
            if slot["choice_no"] != payload.choice_no:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "이미 채점된 문항입니다. 같은 보기만 다시 보낼 수 있습니다",
                )
            # 같은 보기 재전송: 기록 없이 저장된 결과와 현재 진행 상태를 그대로 돌려준다.
            return _slot_grade_response(
                conn,
                session,
                grading.build_grade_result(
                    conn,
                    question_id=slot["question_id"],
                    choice_no=slot["choice_no"],
                    is_correct=slot["is_correct"],
                ),
            )
        if session["finished_at"] is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "이미 종료된 세션입니다. 계속 풀려면 새 세션을 시작하세요"
            )

        result = grading.grade_question(
            conn,
            question_id=slot["question_id"],
            choice_no=payload.choice_no,
            session_id=session_id,
            elapsed_ms=payload.elapsed_ms,
        )
        cycles.grade_slot(
            conn, session_id, seq, choice_no=payload.choice_no, is_correct=result.is_correct
        )
        # 마지막 슬롯이면 같은 트랜잭션에서 라운드를 닫고 다음 라운드/사이클 완료로 넘긴다.
        if cycles.advance_round_if_complete(conn, session):
            session = grading.fetch_session(conn, session_id)
        return _slot_grade_response(conn, session, result)


@router.get("/progress/questions", response_model=list[ProgressItem], summary="문항 상태 목록")
def list_progress_questions(
    conn: Conn,
    bookmarked: Annotated[bool | None, Query()] = None,
    wrong: Annotated[bool | None, Query()] = None,
    unresolved: Annotated[bool | None, Query()] = None,
    due_on: Annotated[date | None, Query(alias="dueOn")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """진도 목록 필터. 세 플래그 모두 `None`(미지정)이면 조건이 걸리지 않는다.

    - `bookmarked`: true/false 로 북마크 여부를 가른다.
    - `wrong`: true = 한 번이라도 틀림(`wrong_count > 0`), false = 한 번도 틀린 적 없음(`wrong_count = 0`).
    - `unresolved`: true = 마지막 응답도 틀림, false = 마지막이 맞았거나 틀린 적 없음.
    - `dueOn`: 복습 예정일이 그날 이하.

    `wrong`·`unresolved` 의 false 는 `bookmarked` 와 같은 규칙(값을 주면 조건이 된다)이며,
    `last_is_correct` 가 NULL 인 행(응답 이력 없이 북마크·메모만 남긴 행)도 의도한 쪽에 들어가도록
    부정형을 `IS NOT FALSE` 가 아니라 `(= 0 OR IS TRUE)` 로 편다.
    """
    clauses: list[str] = []
    params: list = []
    if bookmarked is not None:
        clauses.append("st.bookmarked = %s")
        params.append(bookmarked)
    if wrong is not None:
        clauses.append("st.wrong_count > 0" if wrong else "st.wrong_count = 0")
    if unresolved is not None:
        clauses.append(
            "st.wrong_count > 0 AND st.last_is_correct IS FALSE"
            if unresolved
            else "(st.wrong_count = 0 OR st.last_is_correct IS TRUE)"
        )
    if due_on is not None:
        clauses.append("st.review_due_on <= %s")
        params.append(due_on)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"{PROGRESS_SELECT}{where} ORDER BY st.last_answered_at DESC NULLS LAST, q.id LIMIT %s OFFSET %s"
    return conn.execute(sql, [*params, limit, offset]).fetchall()


@router.get("/progress/questions/{question_id}", response_model=StateOut | None, summary="문항 상태 단건")
def get_progress_question(question_id: str, conn: Conn):
    """응답 이력이 없는 문항이면 null."""
    _ensure_question(conn, question_id)
    return conn.execute(
        f"SELECT {STATE_COLUMNS} FROM ipe.study_state WHERE question_id = %s", (question_id,)
    ).fetchone()


@router.patch(
    "/progress/questions/{question_id}",
    response_model=StateOut,
    summary="문항 상태 수정(북마크·메모·복습 예정일)",
    dependencies=[Depends(require_token)],
)
def update_progress_question(question_id: str, payload: StateUpdate, conn: Conn):
    provided = payload.model_fields_set
    if not provided:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "수정할 필드가 없습니다(bookmarked·note·reviewDueOn 중 하나 이상)"
        )
    _ensure_question(conn, question_id)

    assignments = []
    if "bookmarked" in provided:
        assignments.append("bookmarked = excluded.bookmarked")
    if "note" in provided:
        assignments.append("note = excluded.note")
    if "review_due_on" in provided:
        assignments.append("review_due_on = excluded.review_due_on")

    sql = STATE_INSERT_SQL.format(assignments=", ".join(assignments))
    row = conn.execute(
        sql, (question_id, payload.bookmarked, payload.note, payload.review_due_on)
    ).fetchone()
    return row
