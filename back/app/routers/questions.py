"""문항 단건·랜덤 출제·채점."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..deps import Conn, require_token
from ..queries import STATE_COLUMNS, fetch_questions, question_filters, to_question
from ..schemas import ChoiceAnalysisOut, GradeRequest, GradeResult, QuestionOut

router = APIRouter(prefix="/api", tags=["questions"])

ANSWER_SQL = "SELECT answer, explanation, key_point FROM ipe.question WHERE id = %s"

CHOICES_ANALYSIS_SQL = """
SELECT no, is_correct, why FROM ipe.question_choice WHERE question_id = %s ORDER BY no
"""

ATTEMPT_SQL = """
INSERT INTO ipe.study_attempt (session_id, question_id, choice_no, is_correct, elapsed_ms)
VALUES (%s, %s, %s, %s, %s)
"""

# 세션 존재 확인과 종료(finished_at) 검사를 한 번의 조회로 함께 처리한다.
SESSION_SQL = "SELECT finished_at FROM ipe.study_session WHERE id = %s"

# 응답마다 누계를 증분 갱신하는 upsert. correct_count + wrong_count = attempt_count 를 유지한다(db/README.md).
STATE_UPSERT_SQL = f"""
INSERT INTO ipe.study_state (
        question_id, attempt_count, correct_count, wrong_count,
        last_is_correct, last_choice_no, last_answered_at, streak)
VALUES (%s, 1, %s, %s, %s, %s, now(), %s)
ON CONFLICT (question_id) DO UPDATE SET
    attempt_count    = ipe.study_state.attempt_count + 1,
    correct_count    = ipe.study_state.correct_count + excluded.last_is_correct::int,
    wrong_count      = ipe.study_state.wrong_count + (NOT excluded.last_is_correct)::int,
    last_is_correct  = excluded.last_is_correct,
    last_choice_no   = excluded.last_choice_no,
    last_answered_at = excluded.last_answered_at,
    streak           = CASE WHEN excluded.last_is_correct THEN ipe.study_state.streak + 1 ELSE 0 END,
    updated_at       = now()
RETURNING {STATE_COLUMNS}
"""


@router.get("/questions/random", response_model=list[QuestionOut], summary="랜덤 출제")
def random_questions(
    conn: Conn,
    exam_id: Annotated[str | None, Query(alias="examId")] = None,
    subject_code: Annotated[int | None, Query(alias="subjectCode", ge=1, le=5)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    figure_only: Annotated[bool, Query(alias="figureOnly")] = False,
    count: Annotated[int, Query(ge=1, le=100)] = 10,
):
    where, params = question_filters(
        exam_id=exam_id, subject_code=subject_code, tags=tag, figure_only=figure_only
    )
    rows = fetch_questions(conn, where=where, params=params, order_by="random()", limit=count)
    return [to_question(r) for r in rows]


@router.get("/questions/{question_id}", response_model=QuestionOut, summary="문항 단건")
def get_question(question_id: str, conn: Conn):
    where, params = question_filters(question_id=question_id)
    rows = fetch_questions(conn, where=where, params=params, limit=1)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")
    return to_question(rows[0])


@router.post(
    "/questions/{question_id}/answer",
    response_model=GradeResult,
    summary="채점",
    dependencies=[Depends(require_token)],
)
def answer_question(question_id: str, payload: GradeRequest, conn: Conn):
    """고른 보기 번호를 받아 정답 여부를 돌려주고 study_attempt/study_state 에 기록한다.

    sessionId 를 주면 그 세션에 귀속시킨다 — 없는 세션이면 404, 이미 종료된 세션이면 409 다.
    종료된 세션은 기록을 받지 않으므로(제출 = 점수 확정) 계속 풀려면 새 세션을 만들어야 한다.
    """
    row = conn.execute(ANSWER_SQL, (question_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")

    is_correct = payload.choice_no == row["answer"]
    with conn.transaction():
        if payload.session_id is not None:
            session = conn.execute(SESSION_SQL, (payload.session_id,)).fetchone()
            if session is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND, f"세션 {payload.session_id} 를 찾을 수 없습니다"
                )
            if session["finished_at"] is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "이미 종료된 세션입니다. 계속 풀려면 새 세션을 시작하세요",
                )
        conn.execute(
            ATTEMPT_SQL,
            (payload.session_id, question_id, payload.choice_no, is_correct, payload.elapsed_ms),
        )
        state = conn.execute(
            STATE_UPSERT_SQL,
            (
                question_id,
                int(is_correct),
                int(not is_correct),
                is_correct,
                payload.choice_no,
                int(is_correct),
            ),
        ).fetchone()

    analysis = [
        ChoiceAnalysisOut(no=r["no"], correct=r["is_correct"], why=r["why"])
        for r in conn.execute(CHOICES_ANALYSIS_SQL, (question_id,)).fetchall()
    ]
    return GradeResult(
        question_id=question_id,
        choice_no=payload.choice_no,
        is_correct=is_correct,
        answer=row["answer"],
        explanation=row["explanation"],
        key_point=row["key_point"],
        choices_analysis=analysis,
        state=state,
    )
