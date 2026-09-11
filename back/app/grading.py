"""채점 공용 로직.

정답 조회·원장(study_attempt) INSERT·누계(study_state) upsert·보기별 해설 조회를 한곳에 모은다.
단발 채점(`POST /api/questions/{id}/answer`), 슬롯 제출(`PUT /api/sessions/{id}/items/{seq}/answer`),
앞으로의 모의고사 일괄 제출(`POST /api/sessions/{id}/submit`)이 같은 함수를 쓴다.

트랜잭션은 호출자가 열고, 잠금 순서(세션 → 슬롯 → 사이클)도 호출자가 지킨다(설계 4.6절).
"""
from __future__ import annotations

from fastapi import HTTPException, status

from .queries import STATE_COLUMNS
from .schemas import ChoiceAnalysisOut, GradeResult, StateOut

ANSWER_SQL = "SELECT answer, explanation, key_point FROM ipe.question WHERE id = %s"

CHOICES_ANALYSIS_SQL = """
SELECT no, is_correct, why FROM ipe.question_choice WHERE question_id = %s ORDER BY no
"""

ATTEMPT_SQL = """
INSERT INTO ipe.study_attempt (session_id, question_id, choice_no, is_correct, elapsed_ms)
VALUES (%s, %s, %s, %s, %s)
"""

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

STATE_SELECT_SQL = f"SELECT {STATE_COLUMNS} FROM ipe.study_state WHERE question_id = %s"

SESSION_COLUMNS = (
    "id, mode, exam_id, subject_code, cycle_id, round_no, started_at, finished_at, end_reason"
)

# 세션 존재 확인·종료 검사·라운드 정보를 한 번의 조회로 함께 처리한다.
# FOR UPDATE 로 세션 행을 잠가 두면 이 채점 트랜잭션이 끝날 때까지 /finish 의 UPDATE 가
# 기다린다 — 종료와 겹친 채점이 종료 뒤 집계에 끼어드는 일이 없다(B-01).
SESSION_LOCK_SQL = f"SELECT {SESSION_COLUMNS} FROM ipe.study_session WHERE id = %s FOR UPDATE"
SESSION_SELECT_SQL = f"SELECT {SESSION_COLUMNS} FROM ipe.study_session WHERE id = %s"

# 슬롯 세션 판별. 슬롯이 하나라도 있으면 기록은 슬롯 API 로만 받는다(설계 5.3절).
SLOT_GUARD_SQL = "SELECT 1 FROM ipe.study_session_item WHERE session_id = %s LIMIT 1"


def fetch_session(conn, session_id: int) -> dict:
    """세션 1행. 없으면 404. 잠금 없이 읽는다(쓰기 전 검사에는 lock_session)."""
    row = conn.execute(SESSION_SELECT_SQL, (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"세션 {session_id} 를 찾을 수 없습니다")
    return row


def lock_session(conn, session_id: int) -> dict:
    """세션 행을 FOR UPDATE 로 잠근다. 모든 쓰기의 첫 잠금이다(설계 4.6절). 없으면 404."""
    row = conn.execute(SESSION_LOCK_SQL, (session_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"세션 {session_id} 를 찾을 수 없습니다")
    return row


def session_has_slots(conn, session_id: int) -> bool:
    """슬롯(study_session_item)이 있는 세션인지. 있으면 /answer·/finish 는 409 다."""
    return conn.execute(SLOT_GUARD_SQL, (session_id,)).fetchone() is not None


def fetch_answer_row(conn, question_id: str) -> dict:
    """정답·해설. 없으면 404."""
    row = conn.execute(ANSWER_SQL, (question_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")
    return row


def fetch_state(conn, question_id: str) -> dict | None:
    """문항 누계(study_state) 1행. 응답 이력이 없으면 None."""
    return conn.execute(STATE_SELECT_SQL, (question_id,)).fetchone()


def record_attempt(
    conn,
    *,
    question_id: str,
    choice_no: int,
    is_correct: bool,
    session_id: int | None,
    elapsed_ms: int | None,
) -> dict:
    """원장 1행 추가 + 누계 upsert. 갱신된 study_state 행을 돌려준다."""
    conn.execute(ATTEMPT_SQL, (session_id, question_id, choice_no, is_correct, elapsed_ms))
    return conn.execute(
        STATE_UPSERT_SQL,
        (question_id, int(is_correct), int(not is_correct), is_correct, choice_no, int(is_correct)),
    ).fetchone()


def build_grade_result(
    conn,
    *,
    question_id: str,
    choice_no: int,
    is_correct: bool,
    answer_row: dict | None = None,
    state: dict | StateOut | None = None,
) -> GradeResult:
    """채점 응답 조립. 기록은 하지 않는다.

    state 를 안 주면 현재 누계를 조회한다 — 이미 채점된 슬롯의 재전송·재조회가 이 경로다.
    answer_row 를 안 주면 정답을 조회한다.
    """
    row = fetch_answer_row(conn, question_id) if answer_row is None else answer_row
    if state is None:
        state_row = fetch_state(conn, question_id)
        state_model = (
            StateOut.model_validate(state_row) if state_row else StateOut(question_id=question_id)
        )
    elif isinstance(state, StateOut):
        state_model = state
    else:
        state_model = StateOut.model_validate(state)

    analysis = [
        ChoiceAnalysisOut(no=r["no"], correct=r["is_correct"], why=r["why"])
        for r in conn.execute(CHOICES_ANALYSIS_SQL, (question_id,)).fetchall()
    ]
    return GradeResult(
        question_id=question_id,
        choice_no=choice_no,
        is_correct=is_correct,
        answer=row["answer"],
        explanation=row["explanation"],
        key_point=row["key_point"],
        choices_analysis=analysis,
        state=state_model,
    )


def grade_question(
    conn,
    *,
    question_id: str,
    choice_no: int,
    session_id: int | None = None,
    elapsed_ms: int | None = None,
) -> GradeResult:
    """단발·슬롯 공용 채점: 정답 조회 → 원장·누계 기록 → 채점 응답.

    트랜잭션과 세션 검사(존재·종료·슬롯 여부)는 호출자가 맡는다.
    """
    row = fetch_answer_row(conn, question_id)
    is_correct = choice_no == row["answer"]
    state = record_attempt(
        conn,
        question_id=question_id,
        choice_no=choice_no,
        is_correct=is_correct,
        session_id=session_id,
        elapsed_ms=elapsed_ms,
    )
    return build_grade_result(
        conn, question_id=question_id, choice_no=choice_no, is_correct=is_correct, answer_row=row, state=state
    )
