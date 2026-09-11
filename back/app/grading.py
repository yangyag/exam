"""채점 공용 로직.

정답 조회·원장(study_attempt) INSERT·누계(study_state) upsert·보기별 해설 조회를 한곳에 모은다.
단발 채점(`POST /api/questions/{id}/answer`), 슬롯 제출(`PUT /api/sessions/{id}/items/{seq}/answer`),
모의고사 일괄 제출(`POST /api/sessions/{id}/submit`)이 같은 규칙을 쓴다.

트랜잭션은 호출자가 열고, 잠금 순서(세션 → 슬롯 → 사이클)도 호출자가 지킨다(설계 4.6절).
"""
from __future__ import annotations

from fastapi import HTTPException, status

from .queries import STATE_COLUMNS
from .schemas import ChoiceAnalysisOut, ExamResultOut, ExamSubjectScoreOut, GradeResult, StateOut

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

# --- 모의고사(mode=exam) 최종 제출 -------------------------------------------------
# 슬롯과 과목 코드를 함께 읽는다. 제출 경로는 FOR UPDATE OF si 로 슬롯 100개를 한 번에 잠근다
# (세션 잠금 다음이 슬롯 잠금 — 설계 4.6절).
EXAM_SLOT_ROWS_SQL = """
SELECT si.seq, si.question_id, si.choice_no, si.is_correct, q.subject_code
  FROM ipe.study_session_item si
  JOIN ipe.question q ON q.id = si.question_id
 WHERE si.session_id = %s
 ORDER BY si.seq
"""
EXAM_SLOT_ROWS_LOCK_SQL = EXAM_SLOT_ROWS_SQL + " FOR UPDATE OF si"

EXAM_ANSWERS_SQL = "SELECT id, answer FROM ipe.question WHERE id = ANY(%s)"

# 제출할 때만 쓰는 배열 기반 일괄 쓰기 3종. 문항 순서를 고정(ORDER BY)해 두 세션의 동시 제출이
# 같은 study_state 행을 서로 다른 순서로 잠그는 교착을 피한다.
ATTEMPT_BATCH_SQL = """
INSERT INTO ipe.study_attempt (session_id, question_id, choice_no, is_correct)
SELECT %s, t.question_id, t.choice_no, t.is_correct
  FROM unnest(%s::text[], %s::smallint[], %s::boolean[]) AS t(question_id, choice_no, is_correct)
 ORDER BY t.question_id
"""
# STATE_UPSERT_SQL 과 같은 증분 규칙을 여러 행에 한 번에 적용한다(행마다 1회씩 기록한 것과 같은 결과).
STATE_BATCH_SQL = f"""
INSERT INTO ipe.study_state (
        question_id, attempt_count, correct_count, wrong_count,
        last_is_correct, last_choice_no, last_answered_at, streak)
SELECT t.question_id, 1, t.is_correct::int, (NOT t.is_correct)::int,
       t.is_correct, t.choice_no, now(), t.is_correct::int
  FROM unnest(%s::text[], %s::smallint[], %s::boolean[]) AS t(question_id, choice_no, is_correct)
 ORDER BY t.question_id
ON CONFLICT (question_id) DO UPDATE SET
    attempt_count    = ipe.study_state.attempt_count + 1,
    correct_count    = ipe.study_state.correct_count + excluded.last_is_correct::int,
    wrong_count      = ipe.study_state.wrong_count + (NOT excluded.last_is_correct)::int,
    last_is_correct  = excluded.last_is_correct,
    last_choice_no   = excluded.last_choice_no,
    last_answered_at = excluded.last_answered_at,
    streak           = CASE WHEN excluded.last_is_correct THEN ipe.study_state.streak + 1 ELSE 0 END,
    updated_at       = now()
"""
SLOT_GRADE_BATCH_SQL = """
UPDATE ipe.study_session_item si
   SET is_correct = t.is_correct
  FROM unnest(%s::smallint[], %s::boolean[]) AS t(seq, is_correct)
 WHERE si.session_id = %s AND si.seq = t.seq
"""
# 미응답 슬롯: 점수상 오답(is_correct=false)이지만 choice_no 는 NULL 그대로 둔다(원장에 남기지 않는다).
SLOT_UNANSWERED_SQL = """
UPDATE ipe.study_session_item SET is_correct = FALSE
 WHERE session_id = %s AND choice_no IS NULL AND is_correct IS NULL
"""
EXAM_FINISH_SQL = """
UPDATE ipe.study_session SET finished_at = now(), end_reason = 'finished'
 WHERE id = %s AND finished_at IS NULL
RETURNING finished_at
"""

# 정보처리기사 필기 기준: 과목당 20문항·문항당 5점, 매 과목 40점 이상이면서 전 과목 평균 60점 이상.
POINTS_PER_QUESTION = 5
PASS_SCORE_PER_SUBJECT = 40
PASS_AVERAGE_SCORE = 60


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
    choice_no: int | None,
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


def exam_result(conn, session: dict) -> ExamResultOut:
    """제출된 모의고사의 점수 요약. 슬롯·문항만 읽고 아무것도 기록하지 않는다.

    `submittedAt` 은 세션 행의 `finished_at` 을 그대로 써서 제출 응답과 재조회가 같은 값을 갖는다.
    """
    rows = conn.execute(EXAM_SLOT_ROWS_SQL, (session["id"],)).fetchall()
    return exam_summary(rows, session_id=session["id"], submitted_at=session["finished_at"])


def submit_exam(conn, session: dict) -> ExamResultOut:
    """모의고사 최종 제출: 전 문항을 한 트랜잭션에서 채점하고 세션을 끝낸다(설계 5.3절).

    호출자 계약: 세션 행을 이미 `FOR UPDATE` 로 잠갔고(`lock_session`), `mode='exam'` 이며
    `finished_at IS NULL` 임을 확인한 뒤에만 부른다(진도 라우터). 잠금 순서는 세션 → 슬롯이다.

    - 답한 문항: 정답을 한 번에 조회해 원장 1행·누계 upsert·슬롯 `is_correct` 를 쓴다.
    - 미응답 문항: 슬롯만 `is_correct=false` 로 표시한다 — 원장·누계에는 한 행도 남기지 않는다.
    - 이미 채워진 슬롯(`is_correct IS NOT NULL`)은 건드리지 않는다(정상 흐름에서는 생기지 않는다).
    """
    session_id = session["id"]
    rows = conn.execute(EXAM_SLOT_ROWS_LOCK_SQL, (session_id,)).fetchall()
    pending = [row for row in rows if row["choice_no"] is not None and row["is_correct"] is None]
    if pending:
        answers = _answer_map(conn, [row["question_id"] for row in pending])
        seqs = [row["seq"] for row in pending]
        question_ids = [row["question_id"] for row in pending]
        choice_nos = [row["choice_no"] for row in pending]
        flags = [row["choice_no"] == answers[row["question_id"]] for row in pending]
        conn.execute(ATTEMPT_BATCH_SQL, (session_id, question_ids, choice_nos, flags))
        conn.execute(STATE_BATCH_SQL, (question_ids, choice_nos, flags))
        conn.execute(SLOT_GRADE_BATCH_SQL, (seqs, flags, session_id))
    if any(row["choice_no"] is None for row in rows):
        conn.execute(SLOT_UNANSWERED_SQL, (session_id,))
    finished_at = conn.execute(EXAM_FINISH_SQL, (session_id,)).fetchone()["finished_at"]
    # 채점을 마친 슬롯에서 다시 읽어 점수를 계산한다(이번 트랜잭션이 방금 쓴 값이 보인다).
    scored = conn.execute(EXAM_SLOT_ROWS_SQL, (session_id,)).fetchall()
    return exam_summary(scored, session_id=session_id, submitted_at=finished_at)


def _answer_map(conn, question_ids: list[str]) -> dict[str, int]:
    """문항 정답 번호. 슬롯의 문항은 외래 키로 보장되므로 없으면 KeyError 로 드러나게 둔다."""
    rows = conn.execute(EXAM_ANSWERS_SQL, (list(question_ids),)).fetchall()
    return {row["id"]: row["answer"] for row in rows}


def exam_summary(rows, *, session_id: int, submitted_at) -> ExamResultOut:
    """슬롯 행 목록 → 점수 요약(정보처리기사 필기 기준).

    - `score` = 그 과목 정답 수 × 5점. 미응답은 오답과 같이 0점이고 과목 만점은 100점이다
      (세션에 그 과목 문항이 20개보다 적게 들어 있으면 그만큼 낮은 점수가 만점이 된다).
    - `averageScore` 는 세션에 있는 과목 점수의 평균이다(과목이 하나도 없으면 0.0).
    - `passed` = 과목이 하나 이상 있고, **매 과목 40점 이상**이며 평균이 60점 이상일 때만 참이다.
    """
    answered = 0
    correct = 0
    per_subject: dict[int, int] = {}
    for row in rows:
        if row["choice_no"] is not None:
            answered += 1
        per_subject.setdefault(row["subject_code"], 0)
        if row["is_correct"]:
            correct += 1
            per_subject[row["subject_code"]] += 1
    by_subject = [
        ExamSubjectScoreOut(
            subject_code=code,
            correct=count,
            score=count * POINTS_PER_QUESTION,
            passed=count * POINTS_PER_QUESTION >= PASS_SCORE_PER_SUBJECT,
        )
        for code, count in sorted(per_subject.items())
    ]
    average = (
        round(sum(item.score for item in by_subject) / len(by_subject), 1) if by_subject else 0.0
    )
    return ExamResultOut(
        session_id=session_id,
        item_count=len(rows),
        answered_count=answered,
        unanswered_count=len(rows) - answered,
        correct_count=correct,
        wrong_count=answered - correct,
        by_subject=by_subject,
        average_score=average,
        passed=bool(by_subject)
        and all(item.passed for item in by_subject)
        and average >= PASS_AVERAGE_SCORE,
        submitted_at=submitted_at,
    )
