"""진도: 세션 시작/종료와 문항별 상태(북마크·메모·복습 예정일)."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import Conn, require_token
from ..queries import STATE_COLUMNS
from ..schemas import ProgressItem, SessionCreate, SessionMode, SessionOut, StateOut, StateUpdate

router = APIRouter(prefix="/api", tags=["progress"])

SESSION_SELECT = """
SELECT s.id, s.mode, s.exam_id, s.subject_code, s.started_at, s.finished_at,
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
    """mode: exam(회차 모의고사)·subject(과목 연습)·random(랜덤)·review(오답 복습)."""
    if payload.mode == "exam" and not payload.exam_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mode=exam 세션에는 examId 가 필요합니다")
    if payload.mode == "subject" and payload.subject_code is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "mode=subject 세션에는 subjectCode 가 필요합니다")
    if payload.exam_id and not conn.execute(
        "SELECT 1 FROM ipe.exam WHERE id = %s", (payload.exam_id,)
    ).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"회차 {payload.exam_id} 를 찾을 수 없습니다")
    if payload.subject_code is not None and not conn.execute(
        "SELECT 1 FROM ipe.subject WHERE code = %s", (payload.subject_code,)
    ).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"과목 {payload.subject_code} 를 찾을 수 없습니다")

    row = conn.execute(
        "INSERT INTO ipe.study_session (mode, exam_id, subject_code) VALUES (%s, %s, %s) RETURNING id",
        (payload.mode, payload.exam_id, payload.subject_code),
    ).fetchone()
    return _get_session(conn, row["id"])


@router.get("/sessions", response_model=list[SessionOut], summary="세션 목록")
def list_sessions(
    conn: Conn,
    mode: Annotated[SessionMode | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    sql = SESSION_SELECT
    params: list = []
    if mode:
        sql += " WHERE s.mode = %s"
        params.append(mode)
    sql += " ORDER BY s.started_at DESC, s.id DESC LIMIT %s OFFSET %s"
    return conn.execute(sql, [*params, limit, offset]).fetchall()


@router.post(
    "/sessions/{session_id}/finish",
    response_model=SessionOut,
    summary="세션 종료",
    dependencies=[Depends(require_token)],
)
def finish_session(session_id: int, conn: Conn):
    """이미 끝난 세션을 다시 부르면 현재 상태를 그대로 돌려준다(멱등)."""
    with conn.transaction():
        updated = conn.execute(
            "UPDATE ipe.study_session SET finished_at = now() WHERE id = %s AND finished_at IS NULL RETURNING id",
            (session_id,),
        ).fetchone()
        if updated is None and not conn.execute(
            "SELECT 1 FROM ipe.study_session WHERE id = %s", (session_id,)
        ).fetchone():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"세션 {session_id} 를 찾을 수 없습니다")
    return _get_session(conn, session_id)


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
