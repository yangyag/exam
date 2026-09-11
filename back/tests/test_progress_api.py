"""세션·슬롯·진도 API 테스트(DB 없이 가짜 커넥션으로).

- 세션 모드 계약: exam_practice·exam 은 회차 문항 슬롯을 만들고, subject·review 는 400,
  random 은 슬롯 없이 만든다. 진행 중 세션이 있으면 409 / replaceActive=true 는 중단 후 재생성.
- 슬롯 조회(세션 단건·문항 단건)와 제출(연습 멱등·409·nextSeq, 모의고사 선택 저장·해제).
- 모의고사 최종 제출(submit): 모드 400·중단 409·멱등 재제출·미응답 점수 처리·합격 경계.
- study_state PATCH 는 요청에 담긴 필드만 갱신한다.
- 목록 필터가 WHERE 절·파라미터로 정확히 반영된다.

가짜 커넥션 규칙 조각은 서로 겹치지 않게 WHERE·SELECT 절까지 포함해 고른다
(예: "INSERT INTO ipe.study_session" 은 study_session_item INSERT 와도 겹친다).
"""
from __future__ import annotations

from datetime import date

import pytest

from app import grading

from sample_data import (
    ANSWERED_AT,
    choice_analysis_rows,
    question_row,
    session_row,
    slot_row,
    state_row,
)

SESSION_INSERT = "INSERT INTO ipe.study_session (mode, exam_id, subject_code) VALUES"
SESSION_INSERT_ROUND = "VALUES (%s, %s, %s, %s, %s) RETURNING id"
SESSION_SELECT = "FROM ipe.study_session s"
SESSION_LOOKUP = "FROM ipe.study_session WHERE id"
SESSION_UPDATE = "UPDATE ipe.study_session SET finished_at"
EXAM_OPEN_SESSION = "mode = %s AND exam_id = %s AND finished_at IS NULL"
EXAM_EXISTS = "FROM ipe.exam WHERE id"
SUBJECT_EXISTS = "FROM ipe.subject WHERE code"
QUESTION_IDS_BY_EXAM = "SELECT id FROM ipe.question WHERE exam_id"
QUESTION_SELECT = "coalesce(ch.choices"
ANSWER_SELECT = "SELECT answer, explanation, key_point FROM ipe.question"
ATTEMPT_INSERT = "INSERT INTO ipe.study_attempt"
STATE_UPSERT = "INSERT INTO ipe.study_state"
QUESTION_EXISTS = "SELECT 1 FROM ipe.question WHERE id"
STATE_SELECT_ONE = "FROM ipe.study_state WHERE question_id"
STATE_LIST = "FROM ipe.study_state st"
SLOT_INSERT = "INSERT INTO ipe.study_session_item"
SLOT_GUARD = "SELECT 1 FROM ipe.study_session_item"
SLOT_LIST = "answered_at FROM ipe.study_session_item WHERE session_id = %s ORDER BY seq"
SLOT_ONE = "answered_at FROM ipe.study_session_item WHERE session_id = %s AND seq = %s"
SLOT_STATS = "AS correct_count"
SLOT_PENDING = "AS n FROM ipe.study_session_item"
SLOT_GRADE = "SET choice_no = %s, is_correct"
SLOT_SAVE = "answered_at = CASE WHEN"
ROUND_FINISH = "SET finished_at = now(), end_reason = 'finished'"
CYCLE_LOOKUP = "FROM ipe.study_cycle WHERE id"
CYCLE_OPEN_SESSION = "s.cycle_id = %s AND s.finished_at IS NULL"
WRONG_SLOTS = "SELECT question_id FROM ipe.study_session_item"
CHOICES_SELECT = "FROM ipe.question_choice"
# 모의고사 제출(submit) 경로 — 배치 SQL 이 단건 채점 SQL 과 겹치지 않게 조각을 고른다.
EXAM_SLOT_ROWS = "JOIN ipe.question q ON q.id = si.question_id"
EXAM_ANSWERS = "SELECT id, answer FROM ipe.question WHERE id = ANY"
ATTEMPT_BATCH = "SELECT %s, t.question_id, t.choice_no, t.is_correct"
STATE_BATCH = "SELECT t.question_id, 1, t.is_correct::int"
SLOT_GRADE_BATCH = "SET is_correct = t.is_correct"
SLOT_UNANSWERED = "SET is_correct = FALSE"
EXAM_FINISH = "end_reason = 'finished' WHERE id = %s AND finished_at IS NULL"

QUESTION_ID = "2022-1-001"


def progress_row(**overrides) -> dict:
    """진도 목록(PROGRESS_SELECT) 1행 = study_state + 문항 요약."""
    row = {
        **state_row(),
        "exam_id": "2022-1",
        "number": 1,
        "subject_code": 1,
        "subject_name": "소프트웨어 설계",
        "stem": "다음 중 옳은 것은?",
    }
    row.update(overrides)
    return row


def test_create_exam_session_requires_exam_id(client, fake_db):
    fake = fake_db({})
    response = client.post("/api/sessions", json={"mode": "exam"})
    assert response.status_code == 400
    assert fake.executed(SESSION_INSERT) == []


def test_create_subject_session_rejected_with_400(client, fake_db):
    """mode=subject 는 사이클 API 로만 만든다 — POST /api/sessions 는 400 이다(설계 5.3절)."""
    fake = fake_db({})
    response = client.post("/api/sessions", json={"mode": "subject", "subjectCode": 1})
    assert response.status_code == 400
    assert "사이클" in response.json()["detail"]
    assert fake.executed(SESSION_INSERT) == []


def test_create_review_session_rejected_with_400(client, fake_db):
    """mode=review 도 사이클 라운드 자동 전환으로만 만들어진다."""
    fake = fake_db({})
    response = client.post("/api/sessions", json={"mode": "review", "subjectCode": 1})
    assert response.status_code == 400
    assert fake.executed(SESSION_INSERT) == []


def test_create_random_session(client, fake_db):
    fake = fake_db({SESSION_INSERT: [{"id": 7}], SESSION_SELECT: [session_row(id=7)]})
    response = client.post("/api/sessions", json={"mode": "random"})
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 7
    assert body["mode"] == "random"
    assert body["answered"] == 0
    _, params = fake.single(SESSION_INSERT)
    assert params == ("random", None, None)


def test_create_exam_session_with_unknown_exam_404(client, fake_db):
    fake = fake_db({EXAM_EXISTS: []})
    response = client.post("/api/sessions", json={"mode": "exam", "examId": "2000-9"})
    assert response.status_code == 404
    assert fake.executed(SESSION_INSERT) == []


def test_create_session_with_unknown_subject_404(client, fake_db):
    """과목 존재 검사는 남은 모드(random 등)에서 그대로 동작한다."""
    fake = fake_db({SUBJECT_EXISTS: []})
    response = client.post("/api/sessions", json={"mode": "random", "subjectCode": 5})
    assert response.status_code == 404
    assert fake.executed(SESSION_INSERT) == []


def test_patch_without_fields_rejected(client, fake_db):
    fake = fake_db({})
    response = client.patch(f"/api/progress/questions/{QUESTION_ID}", json={})
    assert response.status_code == 400
    assert fake.executed(STATE_UPSERT) == []


def test_patch_note_only_updates_note(client, fake_db):
    """보낸 필드만 SET 절에 들어가야 다른 값(북마크 등)을 덮어쓰지 않는다."""
    fake = fake_db(
        {
            QUESTION_EXISTS: [{"?column?": 1}],
            STATE_UPSERT: [state_row(note="메모", updated_at=ANSWERED_AT)],
        }
    )
    response = client.patch(f"/api/progress/questions/{QUESTION_ID}", json={"note": "메모"})
    assert response.status_code == 200
    assert response.json()["note"] == "메모"

    sql, params = fake.single(STATE_UPSERT)
    assert "note = excluded.note" in sql
    assert "bookmarked = excluded.bookmarked" not in sql
    assert "review_due_on = excluded.review_due_on" not in sql
    assert params == (QUESTION_ID, None, "메모", None)


def test_patch_bookmark_and_review_due(client, fake_db):
    fake = fake_db(
        {
            QUESTION_EXISTS: [{"?column?": 1}],
            STATE_UPSERT: [state_row(bookmarked=True, review_due_on=date(2026, 9, 20))],
        }
    )
    response = client.patch(
        f"/api/progress/questions/{QUESTION_ID}",
        json={"bookmarked": True, "reviewDueOn": "2026-09-20"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["bookmarked"] is True
    assert body["reviewDueOn"] == "2026-09-20"

    sql, params = fake.single(STATE_UPSERT)
    assert "bookmarked = excluded.bookmarked" in sql
    assert "review_due_on = excluded.review_due_on" in sql
    assert "note = excluded.note" not in sql
    assert params == (QUESTION_ID, True, None, date(2026, 9, 20))


def test_patch_unknown_question_404(client, fake_db):
    fake = fake_db({QUESTION_EXISTS: []})
    response = client.patch(f"/api/progress/questions/없는-문항", json={"bookmarked": True})
    assert response.status_code == 404
    assert fake.executed(STATE_UPSERT) == []


def test_get_progress_unknown_question_404(client, fake_db):
    fake_db({QUESTION_EXISTS: []})
    response = client.get(f"/api/progress/questions/없는-문항")
    assert response.status_code == 404


def test_get_progress_without_history_returns_null(client, fake_db):
    """응답 이력이 없는 문항이면 null(200)이지 404 가 아니다."""
    fake_db({QUESTION_EXISTS: [{"?column?": 1}], STATE_SELECT_ONE: []})
    response = client.get(f"/api/progress/questions/{QUESTION_ID}")
    assert response.status_code == 200
    assert response.json() is None


def test_progress_list_filters(client, fake_db):
    fake = fake_db({STATE_LIST: [progress_row(bookmarked=True, wrong_count=1, attempt_count=1)]})
    response = client.get(
        "/api/progress/questions",
        params={"bookmarked": "true", "wrong": "true", "dueOn": "2026-09-30", "limit": 10, "offset": 3},
    )
    assert response.status_code == 200
    assert response.json()[0]["questionId"] == QUESTION_ID

    sql, params = fake.single(STATE_LIST)
    assert "st.bookmarked = %s" in sql
    assert "st.wrong_count > 0" in sql
    assert "st.review_due_on <= %s" in sql
    assert params == [True, date(2026, 9, 30), 10, 3]


def test_progress_list_wrong_true_filter(client, fake_db):
    fake = fake_db({STATE_LIST: []})
    response = client.get("/api/progress/questions", params={"wrong": "true"})
    assert response.status_code == 200

    sql, params = fake.single(STATE_LIST)
    assert "st.wrong_count > 0" in sql
    assert params == [50, 0]


def test_progress_list_wrong_false_filter(client, fake_db):
    """wrong=false 도 bookmarked 처럼 무시되지 않고 '한 번도 틀린 적 없음' 조건이 된다."""
    fake = fake_db({STATE_LIST: []})
    response = client.get("/api/progress/questions", params={"wrong": "false"})
    assert response.status_code == 200

    sql, params = fake.single(STATE_LIST)
    assert "st.wrong_count = 0" in sql
    assert "st.wrong_count > 0" not in sql
    assert params == [50, 0]


def test_progress_list_unresolved_true_filter(client, fake_db):
    fake = fake_db({STATE_LIST: []})
    response = client.get("/api/progress/questions", params={"unresolved": "true"})
    assert response.status_code == 200

    sql, _ = fake.single(STATE_LIST)
    assert "st.wrong_count > 0 AND st.last_is_correct IS FALSE" in sql


def test_progress_list_unresolved_false_filter(client, fake_db):
    """unresolved=false = '마지막이 맞았거나 틀린 적 없음'. last_is_correct NULL 행도 들어간다."""
    fake = fake_db({STATE_LIST: []})
    response = client.get("/api/progress/questions", params={"unresolved": "false"})
    assert response.status_code == 200

    sql, params = fake.single(STATE_LIST)
    assert "(st.wrong_count = 0 OR st.last_is_correct IS TRUE)" in sql
    assert "IS FALSE" not in sql
    assert params == [50, 0]


def test_progress_list_without_flags_has_no_filter(client, fake_db):
    """bookmarked·wrong·unresolved 를 주지 않으면 WHERE 절이 붙지 않는다(전체 조회)."""
    fake = fake_db({STATE_LIST: []})
    response = client.get("/api/progress/questions")
    assert response.status_code == 200

    sql, params = fake.single(STATE_LIST)
    assert "WHERE" not in sql
    assert params == [50, 0]


def test_sessions_list_passes_paging(client, fake_db):
    fake = fake_db({SESSION_SELECT: [session_row(answered=2, correct=1)]})
    response = client.get("/api/sessions", params={"limit": 5, "offset": 2})
    assert response.status_code == 200
    assert response.json()[0]["answered"] == 2

    sql, params = fake.single(SESSION_SELECT)
    assert "ORDER BY s.started_at DESC" in sql
    assert params == [5, 2]


def test_finish_session_is_idempotent(client, fake_db):
    """이미 끝난 세션을 다시 끝내도 현재 상태를 그대로 돌려준다(UPDATE 없음)."""
    finished = session_row(
        id=9, finished_at=ANSWERED_AT, end_reason="finished", answered=2, correct=1
    )
    fake = fake_db({SESSION_LOOKUP: [finished], SLOT_GUARD: [], SESSION_SELECT: [finished]})
    response = client.post("/api/sessions/9/finish")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 9
    assert body["finishedAt"] is not None
    assert body["endReason"] == "finished"
    assert body["answered"] == 2
    assert body["correct"] == 1
    assert fake.executed(SESSION_UPDATE) == []


def test_finish_session_records_end_reason(client, fake_db):
    """진행 중 세션을 끝내면 finished_at 과 end_reason='finished' 를 함께 기록한다(새 CHECK 통과)."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=9)],
            SLOT_GUARD: [],
            SESSION_SELECT: [session_row(id=9, finished_at=ANSWERED_AT, end_reason="finished")],
        }
    )
    response = client.post("/api/sessions/9/finish")
    assert response.status_code == 200
    assert response.json()["endReason"] == "finished"
    sql, params = fake.single(SESSION_UPDATE)
    assert "end_reason = 'finished'" in sql
    assert params == (9,)


def test_finish_slot_session_rejected_with_409(client, fake_db):
    """슬롯이 있는 세션은 /finish 로 끝낼 수 없다 — 연습은 자동 종료, 모의고사는 최종 제출."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=9, mode="exam_practice", exam_id="2026-1")],
            SLOT_GUARD: [{"?column?": 1}],
        }
    )
    response = client.post("/api/sessions/9/finish")
    assert response.status_code == 409
    assert "슬롯" in response.json()["detail"]
    assert fake.executed(SESSION_UPDATE) == []


def test_finish_unknown_session_404(client, fake_db):
    fake_db({SESSION_LOOKUP: []})
    response = client.post("/api/sessions/999/finish")
    assert response.status_code == 404


def test_create_random_session_with_explicit_null_exam_id(client, fake_db):
    """examId 를 null 로 보내는 것은 생략과 같다(존재 검사도 INSERT 값도 null)."""
    fake = fake_db({SESSION_INSERT: [{"id": 7}], SESSION_SELECT: [session_row(id=7)]})
    response = client.post("/api/sessions", json={"mode": "random", "examId": None})
    assert response.status_code == 201
    assert response.json()["examId"] is None
    assert fake.single(SESSION_INSERT)[1] == ("random", None, None)


def test_create_session_with_blank_exam_id_normalizes_to_null(client, fake_db):
    """빈 문자열 examId 는 null 로 정규화되어 회차 존재 검사를 건너뛴다(B-02)."""
    fake = fake_db({SESSION_INSERT: [{"id": 7}], SESSION_SELECT: [session_row(id=7)]})
    response = client.post("/api/sessions", json={"mode": "random", "examId": ""})
    assert response.status_code == 201
    assert response.json()["examId"] is None
    assert fake.single(SESSION_INSERT)[1] == ("random", None, None)
    assert fake.executed(EXAM_EXISTS) == []


def test_create_exam_session_with_blank_exam_id_400(client, fake_db):
    """mode=exam 은 examId 가 필요하므로 빈 문자열은 400 이고 INSERT 하지 않는다(B-02)."""
    fake = fake_db({})
    response = client.post("/api/sessions", json={"mode": "exam", "examId": ""})
    assert response.status_code == 400
    assert "examId" in response.json()["detail"]
    assert fake.executed(SESSION_INSERT) == []


@pytest.mark.parametrize("mode", ["exam", "exam_practice"])
def test_create_exam_slot_session_creates_slots(client, fake_db, mode):
    """exam_practice·exam 은 회차 문항 번호 순으로 슬롯을 만들고 세션 요약에 새 필드를 싣는다."""
    fake = fake_db(
        {
            EXAM_EXISTS: [{"?column?": 1}],
            QUESTION_IDS_BY_EXAM: [{"id": "2026-1-001"}, {"id": "2026-1-002"}],
            EXAM_OPEN_SESSION: [],
            SESSION_INSERT_ROUND: [{"id": 11}],
            SLOT_INSERT: [],
            SESSION_SELECT: [session_row(id=11, mode=mode, exam_id="2026-1")],
        }
    )
    response = client.post("/api/sessions", json={"mode": mode, "examId": "2026-1"})
    assert response.status_code == 201
    body = response.json()
    assert body["examId"] == "2026-1"
    assert body["cycleId"] is None and body["roundNo"] is None and body["endReason"] is None

    sql, params = fake.single(QUESTION_IDS_BY_EXAM)
    assert "ORDER BY number, id" in sql
    assert params == ("2026-1",)
    _, insert_params = fake.single(SESSION_INSERT_ROUND)
    assert insert_params == (mode, "2026-1", None, None, None)
    _, slot_params = fake.single(SLOT_INSERT)
    assert slot_params == (11, ["2026-1-001", "2026-1-002"])


def test_create_exam_slot_session_with_replace_active_abandons_old(client, fake_db):
    """replaceActive=true 면 진행 중 세션을 abandoned 로 닫고 같은 트랜잭션에서 새로 만든다."""
    fake = fake_db(
        {
            EXAM_EXISTS: [{"?column?": 1}],
            QUESTION_IDS_BY_EXAM: [{"id": "2026-1-001"}],
            EXAM_OPEN_SESSION: [{"id": 5}],
            SESSION_INSERT_ROUND: [{"id": 12}],
            SLOT_INSERT: [],
            SESSION_SELECT: [session_row(id=12, mode="exam_practice", exam_id="2026-1")],
        }
    )
    response = client.post(
        "/api/sessions",
        json={"mode": "exam_practice", "examId": "2026-1", "replaceActive": True},
    )
    assert response.status_code == 201
    sql, params = fake.single(SESSION_UPDATE)
    assert "end_reason = 'abandoned'" in sql
    assert params == ([5],)
    assert fake.executed(SLOT_INSERT)


def test_create_exam_slot_session_conflicts_with_open_session(client, fake_db):
    """진행 중 세션이 있고 replaceActive 가 없으면 409 이고 아무것도 만들지 않는다."""
    fake = fake_db(
        {
            EXAM_EXISTS: [{"?column?": 1}],
            QUESTION_IDS_BY_EXAM: [{"id": "2026-1-001"}],
            EXAM_OPEN_SESSION: [{"id": 5}],
        }
    )
    response = client.post("/api/sessions", json={"mode": "exam_practice", "examId": "2026-1"})
    assert response.status_code == 409
    assert fake.executed(SESSION_INSERT_ROUND) == []
    assert fake.executed(SLOT_INSERT) == []


def test_create_exam_slot_session_without_questions_400(client, fake_db):
    fake = fake_db({EXAM_EXISTS: [{"?column?": 1}], QUESTION_IDS_BY_EXAM: []})
    response = client.post("/api/sessions", json={"mode": "exam_practice", "examId": "2000-9"})
    assert response.status_code == 400
    assert fake.executed(SESSION_INSERT_ROUND) == []


def test_get_session_detail_returns_slots_and_next_seq(client, fake_db):
    """세션 단건은 요약 + 슬롯 목록 + nextSeq 를 준다. 조회는 아무것도 기록하지 않는다."""
    fake = fake_db(
        {
            SESSION_SELECT: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_STATS: [
                {"item_count": 3, "answered_count": 1, "next_seq": 2, "correct_count": 1, "wrong_count": 0}
            ],
            SLOT_LIST: [
                slot_row(seq=1, choice_no=2, is_correct=True, answered_at=ANSWERED_AT),
                slot_row(seq=2, question_id="2022-1-002"),
                slot_row(seq=3, question_id="2022-1-003"),
            ],
        }
    )
    response = client.get("/api/sessions/7")
    assert response.status_code == 200
    body = response.json()
    assert body["itemCount"] == 3
    assert body["answeredCount"] == 1
    assert body["nextSeq"] == 2
    assert body["finishedAt"] is None
    assert [item["seq"] for item in body["items"]] == [1, 2, 3]
    assert body["items"][0]["isCorrect"] is True
    assert body["items"][1]["isCorrect"] is None
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(SLOT_GRADE) == []


def test_get_ongoing_exam_session_hides_is_correct(client, fake_db):
    """진행 중 모의고사는 슬롯 목록에서도 정답 여부를 가린다(isCorrect=null)."""
    fake_db(
        {
            SESSION_SELECT: [session_row(id=7, mode="exam", exam_id="2026-1")],
            SLOT_STATS: [
                {"item_count": 2, "answered_count": 1, "next_seq": 1, "correct_count": 1, "wrong_count": 0}
            ],
            SLOT_LIST: [
                slot_row(seq=1, choice_no=2, is_correct=True, answered_at=ANSWERED_AT),
                slot_row(seq=2),
            ],
        }
    )
    body = client.get("/api/sessions/7").json()
    assert body["items"][0]["choiceNo"] == 2
    assert body["items"][0]["isCorrect"] is None


def test_get_session_item_before_grading_hides_state_and_result(client, fake_db):
    """채점 전 슬롯은 state 를 빼고 result 를 주지 않는다 — 이전 풀이 정답이 드러나지 않게."""
    fake = fake_db(
        {
            SESSION_SELECT: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_ONE: [slot_row(seq=1, question_id=QUESTION_ID)],
            QUESTION_SELECT: [question_row(state=state_row(last_is_correct=True, last_choice_no=2))],
        }
    )
    response = client.get("/api/sessions/7/items/1")
    assert response.status_code == 200
    body = response.json()
    assert body["seq"] == 1
    assert body["id"] == QUESTION_ID
    assert body["state"] is None
    assert body["result"] is None
    assert body["isCorrect"] is None
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(ANSWER_SELECT) == []


def test_get_session_item_graded_slot_returns_result_without_recording(client, fake_db):
    """채점된 슬롯은 result 에 채점 응답과 같은 형식을 담는다. 조회는 원장을 늘리지 않는다."""
    fake = fake_db(
        {
            SESSION_SELECT: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_ONE: [
                slot_row(seq=2, question_id=QUESTION_ID, choice_no=2, is_correct=True, answered_at=ANSWERED_AT)
            ],
            QUESTION_SELECT: [question_row()],
            ANSWER_SELECT: [{"answer": 2, "explanation": "정답 해설", "key_point": "핵심 개념"}],
            CHOICES_SELECT: choice_analysis_rows(2),
            STATE_SELECT_ONE: [state_row(attempt_count=1, correct_count=1, last_is_correct=True, last_choice_no=2)],
        }
    )
    response = client.get("/api/sessions/7/items/2")
    assert response.status_code == 200
    body = response.json()
    assert body["isCorrect"] is True
    assert body["answeredAt"] is not None
    assert body["result"]["answer"] == 2
    assert body["result"]["explanation"] == "정답 해설"
    assert [item["no"] for item in body["result"]["choicesAnalysis"] if item["correct"]] == [2]
    assert body["state"] is None
    assert fake.executed(ATTEMPT_INSERT) == []


def test_get_session_item_unknown_slot_404(client, fake_db):
    fake_db({SESSION_SELECT: [session_row(id=7, mode="exam_practice", exam_id="2026-1")], SLOT_ONE: []})
    response = client.get("/api/sessions/7/items/99")
    assert response.status_code == 404


def _grading_rules(slot: dict, session: dict | None = None, **extra) -> dict:
    """연습 슬롯 채점에 쓰는 기본 규칙. 상태 행은 upsert 파라미터에서 만든다."""

    def state_from_params(sql, params):
        question_id, correct, wrong, last, choice_no, streak = params
        return [
            state_row(
                question_id=question_id,
                attempt_count=correct + wrong,
                correct_count=correct,
                wrong_count=wrong,
                last_is_correct=last,
                last_choice_no=choice_no,
                streak=streak,
            )
        ]

    rules = {
        SESSION_LOOKUP: [session or session_row(id=7, mode="exam_practice", exam_id="2026-1")],
        SLOT_ONE: [slot],
        ANSWER_SELECT: [{"answer": 2, "explanation": "정답 해설", "key_point": "핵심 개념"}],
        ATTEMPT_INSERT: [],
        STATE_UPSERT: state_from_params,
        CHOICES_SELECT: choice_analysis_rows(2),
        SLOT_GRADE: [],
        SLOT_PENDING: [{"n": 1}],
        SLOT_STATS: [
            {"item_count": 3, "answered_count": 1, "next_seq": 2, "correct_count": 1, "wrong_count": 0}
        ],
    }
    rules.update(extra)
    return rules


def test_put_practice_slot_grades_and_returns_progress(client, fake_db):
    """연습 슬롯 제출은 즉시 채점하고 세션 진행 정보를 함께 돌려준다."""
    fake = fake_db(_grading_rules(slot_row(seq=1, question_id=QUESTION_ID)))
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["isCorrect"] is True
    assert body["answer"] == 2
    assert body["session"] == {
        "id": 7,
        "itemCount": 3,
        "answeredCount": 1,
        "nextSeq": 2,
        "finished": False,
    }
    assert body["roundResult"] is None
    assert body["cycle"] is None

    _, slot_params = fake.single(SLOT_GRADE)
    assert slot_params == (2, True, 7, 1)
    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params == (7, QUESTION_ID, 2, True, None)


def test_put_practice_slot_resend_same_choice_is_idempotent(client, fake_db):
    """같은 보기 재전송은 원장·슬롯을 건드리지 않고 저장된 결과로 200 이다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_ONE: [
                slot_row(seq=1, question_id=QUESTION_ID, choice_no=2, is_correct=True, answered_at=ANSWERED_AT)
            ],
            ANSWER_SELECT: [{"answer": 2, "explanation": "정답 해설", "key_point": "핵심 개념"}],
            CHOICES_SELECT: choice_analysis_rows(2),
            STATE_SELECT_ONE: [state_row(attempt_count=1, correct_count=1, last_is_correct=True, last_choice_no=2)],
            SLOT_STATS: [
                {"item_count": 3, "answered_count": 1, "next_seq": 2, "correct_count": 1, "wrong_count": 0}
            ],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 2, "elapsedMs": 900})
    assert response.status_code == 200
    assert response.json()["isCorrect"] is True
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []
    assert fake.executed(SLOT_GRADE) == []
    assert fake.executed(SLOT_PENDING) == []


def test_put_practice_slot_different_choice_conflicts(client, fake_db):
    """이미 채점된 슬롯에 다른 보기를 보내면 409 이고 아무것도 쓰지 않는다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_ONE: [
                slot_row(seq=1, question_id=QUESTION_ID, choice_no=2, is_correct=True, answered_at=ANSWERED_AT)
            ],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 3})
    assert response.status_code == 409
    assert "이미 채점된" in response.json()["detail"]
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(SLOT_GRADE) == []


def test_put_practice_slot_requires_choice_no(client, fake_db):
    """연습 슬롯은 선택 해제가 없다 — choiceNo 없이 보내면 400 이다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=7, mode="exam_practice", exam_id="2026-1")],
            SLOT_ONE: [slot_row(seq=1, question_id=QUESTION_ID)],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={})
    assert response.status_code == 400
    assert fake.executed(ATTEMPT_INSERT) == []


def test_put_slot_on_random_session_404(client, fake_db):
    """슬롯이 없는 세션(랜덤)에는 슬롯 제출 경로가 없다."""
    fake_db({SESSION_LOOKUP: [session_row(id=7)], SLOT_ONE: []})
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 2})
    assert response.status_code == 404


def test_put_exam_slot_saves_choice_without_answer(client, fake_db):
    """모의고사 슬롯은 선택만 저장하고 정답·해설을 돌려주지 않는다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=7, mode="exam", exam_id="2026-1")],
            SLOT_ONE: [slot_row(seq=1, question_id=QUESTION_ID)],
            SLOT_SAVE: [{"choice_no": 3, "answered_at": ANSWERED_AT}],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["seq"] == 1
    assert body["choiceNo"] == 3
    assert body["answeredAt"] is not None
    assert "answer" not in body and "result" not in body
    _, save_params = fake.single(SLOT_SAVE)
    assert save_params == (3, 3, 7, 1)
    # 선택 저장은 원장·누계를 건드리지 않는다.
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []


def test_put_exam_slot_null_clears_choice(client, fake_db):
    """모의고사에서 choiceNo=null 은 선택 해제다(answered_at 도 비운다)."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [session_row(id=7, mode="exam", exam_id="2026-1")],
            SLOT_ONE: [slot_row(seq=1, choice_no=3, answered_at=ANSWERED_AT)],
            SLOT_SAVE: [{"choice_no": None, "answered_at": None}],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": None})
    assert response.status_code == 200
    assert response.json()["choiceNo"] is None
    assert fake.single(SLOT_SAVE)[1] == (None, None, 7, 1)


def test_put_exam_slot_on_abandoned_session_409(client, fake_db):
    """replaceActive 로 중단된 모의고사에는 '이미 제출' 이 아니라 중단 안내가 나간다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [
                session_row(
                    id=7, mode="exam", exam_id="2026-1", finished_at=ANSWERED_AT, end_reason="abandoned"
                )
            ],
            SLOT_ONE: [
                slot_row(seq=1, question_id=QUESTION_ID, choice_no=2, answered_at=ANSWERED_AT)
            ],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 2})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "중단" in detail
    assert "제출" not in detail, "제출된 적 없는 세션에 '이미 제출' 안내가 나갔다"
    assert fake.executed(SLOT_SAVE) == []
    assert fake.executed(ATTEMPT_INSERT) == []


def test_put_practice_slot_on_abandoned_session_409(client, fake_db):
    """중단된 라운드(사이클 새로 구성)에도 중단 안내가 나가고 기록하지 않는다."""
    fake = fake_db(
        {
            SESSION_LOOKUP: [
                session_row(
                    id=7,
                    mode="subject",
                    subject_code=1,
                    cycle_id=3,
                    round_no=1,
                    finished_at=ANSWERED_AT,
                    end_reason="abandoned",
                )
            ],
            SLOT_ONE: [slot_row(seq=1, question_id=QUESTION_ID)],
        }
    )
    response = client.put("/api/sessions/7/items/1/answer", json={"choiceNo": 2})
    assert response.status_code == 409
    assert "중단" in response.json()["detail"]
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []
    assert fake.executed(SLOT_GRADE) == []


def test_put_last_practice_slot_advances_cycle_round(client, fake_db):
    """마지막 슬롯 채점은 라운드를 닫고 오답으로 다음 라운드(review)를 만든다(같은 트랜잭션)."""
    cycle = {"id": 3, "subject_code": 1, "status": "active"}

    def session_by_sql(sql, params):
        if sql.endswith("FOR UPDATE"):
            return [session_row(id=7, mode="subject", subject_code=1, cycle_id=3, round_no=1)]
        return [
            session_row(
                id=7,
                mode="subject",
                subject_code=1,
                cycle_id=3,
                round_no=1,
                finished_at=ANSWERED_AT,
                end_reason="finished",
            )
        ]

    def cycle_by_sql(sql, params):
        # 잠글 때는 active, 라운드 전환 뒤 조회에는 completed 로 바뀐 상태를 흉내낸다.
        return [cycle] if sql.endswith("FOR UPDATE") else [{**cycle, "status": "active"}]

    rules = _grading_rules(
        slot_row(seq=2, question_id="2022-1-002"),
        **{
            SESSION_LOOKUP: session_by_sql,
            SLOT_PENDING: [{"n": 0}],
            ROUND_FINISH: [],
            CYCLE_LOOKUP: cycle_by_sql,
            WRONG_SLOTS: [{"question_id": "2022-1-003"}],
            SESSION_INSERT_ROUND: [{"id": 9}],
            SLOT_INSERT: [],
            CYCLE_OPEN_SESSION: [{"id": 9, "round_no": 2, "item_count": 1}],
            SLOT_STATS: [
                {"item_count": 2, "answered_count": 2, "next_seq": None, "correct_count": 1, "wrong_count": 1}
            ],
        },
    )
    fake = fake_db(rules)
    response = client.put("/api/sessions/7/items/2/answer", json={"choiceNo": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["session"]["finished"] is True
    assert body["session"]["nextSeq"] is None
    assert body["roundResult"] == {"roundNo": 1, "itemCount": 2, "correct": 1, "wrong": 1}
    assert body["cycle"] == {
        "id": 3,
        "status": "active",
        "nextSessionId": 9,
        "nextRoundNo": 2,
        "nextItemCount": 1,
    }

    # 라운드를 먼저 닫고 다음 라운드를 만든다 — 열린 라운드 1개 인덱스 때문에 순서가 중요하다.
    calls = [sql for sql, _ in fake.calls]
    finish_at = next(i for i, sql in enumerate(calls) if ROUND_FINISH in sql)
    insert_at = next(i for i, sql in enumerate(calls) if SESSION_INSERT_ROUND in sql)
    assert finish_at < insert_at
    _, insert_params = fake.single(SESSION_INSERT_ROUND)
    assert insert_params == ("review", None, 1, 3, 2)
    _, slot_params = fake.single(SLOT_INSERT)
    assert slot_params == (9, ["2022-1-003"])


def test_put_last_practice_slot_completes_cycle_without_wrong(client, fake_db):
    """오답이 없으면 다음 라운드를 만들지 않고 사이클을 completed 로 바꾼다."""

    def session_by_sql(sql, params):
        if sql.endswith("FOR UPDATE"):
            return [session_row(id=7, mode="subject", subject_code=1, cycle_id=3, round_no=1)]
        return [
            session_row(
                id=7,
                mode="subject",
                subject_code=1,
                cycle_id=3,
                round_no=1,
                finished_at=ANSWERED_AT,
                end_reason="finished",
            )
        ]

    def cycle_by_sql(sql, params):
        return [{"id": 3, "subject_code": 1, "status": "active" if sql.endswith("FOR UPDATE") else "completed"}]

    fake = fake_db(
        _grading_rules(
            slot_row(seq=2, question_id="2022-1-002"),
            **{
                SESSION_LOOKUP: session_by_sql,
                SLOT_PENDING: [{"n": 0}],
                ROUND_FINISH: [],
                CYCLE_LOOKUP: cycle_by_sql,
                WRONG_SLOTS: [],
                SLOT_STATS: [
                    {"item_count": 2, "answered_count": 2, "next_seq": None, "correct_count": 2, "wrong_count": 0}
                ],
            },
        )
    )
    response = client.put("/api/sessions/7/items/2/answer", json={"choiceNo": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["roundResult"] == {"roundNo": 1, "itemCount": 2, "correct": 2, "wrong": 0}
    assert body["cycle"]["status"] == "completed"
    assert body["cycle"]["nextSessionId"] is None
    assert "status = 'completed'" in fake.single("SET status = 'completed'")[0]
    assert fake.executed(SESSION_INSERT_ROUND) == []


# --- 모의고사 최종 제출(POST /api/sessions/{id}/submit) -------------------------


def exam_slot_row(
    seq: int, question_id: str, *, choice_no: int | None = None,
    is_correct: bool | None = None, subject_code: int = 1,
) -> dict:
    """모의고사 채점 조회(EXAM_SLOT_ROWS) 1행 = 슬롯 + 과목 코드."""
    return {
        "seq": seq,
        "question_id": question_id,
        "choice_no": choice_no,
        "is_correct": is_correct,
        "subject_code": subject_code,
    }


def _exam_session(**overrides) -> dict:
    """모의고사 세션 1행(기본: 진행 중)."""
    return session_row(id=7, mode="exam", exam_id="2026-1", **overrides)


@pytest.mark.parametrize("mode", ["exam_practice", "random", "subject"])
def test_submit_exam_rejects_other_modes_with_400(client, fake_db, mode):
    """submit 은 모의고사(mode=exam) 전용이다 — 다른 모드는 400 이고 아무것도 쓰지 않는다."""
    fake = fake_db({SESSION_LOOKUP: [session_row(id=7, mode=mode, exam_id="2026-1")]})
    response = client.post("/api/sessions/7/submit")
    assert response.status_code == 400, response.text
    assert "모의고사" in response.json()["detail"]
    assert fake.executed(ATTEMPT_BATCH) == []
    assert fake.executed(EXAM_FINISH) == []


def test_submit_exam_unknown_session_404(client, fake_db):
    fake_db({SESSION_LOOKUP: []})
    response = client.post("/api/sessions/999/submit")
    assert response.status_code == 404
    assert "999" in response.json()["detail"]


def test_submit_exam_abandoned_session_409(client, fake_db):
    """replaceActive 로 중단된 모의고사는 제출할 수 없다 — 제출된 적이 없어 결과도 없다."""
    fake = fake_db(
        {SESSION_LOOKUP: [_exam_session(finished_at=ANSWERED_AT, end_reason="abandoned")]}
    )
    response = client.post("/api/sessions/7/submit")
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "중단" in detail
    assert "이미 제출" not in detail
    assert fake.executed(ATTEMPT_BATCH) == []
    assert fake.executed(EXAM_FINISH) == []


def test_submit_exam_grades_answered_and_scores_unanswered_as_wrong(client, fake_db):
    """제출: 답한 문항만 원장·누계에 남기고, 미응답은 점수상 오답으로만 센다(원장 미기록)."""
    slots = [
        exam_slot_row(1, "2022-1-001", choice_no=2, subject_code=1),  # 정답(2)
        exam_slot_row(2, "2022-1-002", choice_no=1, subject_code=1),  # 오답(정답 3)
        exam_slot_row(3, "2022-1-003", subject_code=2),  # 미응답
    ]
    written = {"graded": False, "unanswered": False}

    def slot_rows(sql, params):
        # 채점 배치가 실행된 뒤의 재조회에는 이번 트랜잭션이 쓴 is_correct 가 보인다.
        if written["graded"]:
            slots[0]["is_correct"] = True
            slots[1]["is_correct"] = False
        if written["unanswered"]:
            slots[2]["is_correct"] = False
        return [dict(row) for row in slots]

    def grade_batch(sql, params):
        written["graded"] = True
        return []

    def unanswered_update(sql, params):
        written["unanswered"] = True
        return []

    fake = fake_db(
        {
            SESSION_LOOKUP: [_exam_session()],
            EXAM_SLOT_ROWS: slot_rows,
            EXAM_ANSWERS: [
                {"id": "2022-1-001", "answer": 2},
                {"id": "2022-1-002", "answer": 3},
                {"id": "2022-1-003", "answer": 4},
            ],
            ATTEMPT_BATCH: [],
            STATE_BATCH: [],
            SLOT_GRADE_BATCH: grade_batch,
            SLOT_UNANSWERED: unanswered_update,
            EXAM_FINISH: [{"finished_at": ANSWERED_AT}],
        }
    )
    response = client.post("/api/sessions/7/submit")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {key: value for key, value in body.items() if key != "submittedAt"} == {
        "sessionId": 7,
        "itemCount": 3,
        "answeredCount": 2,
        "unansweredCount": 1,
        "correctCount": 1,
        "wrongCount": 1,
        "bySubject": [
            {"subjectCode": 1, "correct": 1, "score": 5, "passed": False},
            {"subjectCode": 2, "correct": 0, "score": 0, "passed": False},
        ],
        "averageScore": 2.5,
        "passed": False,
    }
    assert body["submittedAt"] is not None

    # 원장·누계 배치는 답한 문항만 담는다(미응답 3번은 빠진다).
    assert fake.single(ATTEMPT_BATCH)[1] == (7, ["2022-1-001", "2022-1-002"], [2, 1], [True, False])
    assert fake.single(STATE_BATCH)[1] == (["2022-1-001", "2022-1-002"], [2, 1], [True, False])
    assert fake.single(SLOT_GRADE_BATCH)[1] == ([1, 2], [True, False], 7)
    assert fake.single(SLOT_UNANSWERED)[1] == (7,)

    # 기록 순서: 원장 → 누계 → 슬롯 채점 → 미응답 표시 → 세션 종료.
    calls = [sql for sql, _ in fake.calls]

    def at(fragment: str) -> int:
        return next(i for i, sql in enumerate(calls) if fragment in sql)

    assert at(ATTEMPT_BATCH) < at(STATE_BATCH) < at(SLOT_GRADE_BATCH) < at(SLOT_UNANSWERED)
    assert at(SLOT_UNANSWERED) < at(EXAM_FINISH)


def test_submit_exam_is_idempotent_without_writes(client, fake_db):
    """이미 제출된 모의고사에 다시 보내면 기록 없이 같은 결과를 돌려준다(멱등)."""
    slots = [
        exam_slot_row(1, "2022-1-001", choice_no=2, is_correct=True, subject_code=1),
        exam_slot_row(2, "2022-1-002", subject_code=1, is_correct=False),
    ]
    fake = fake_db(
        {
            SESSION_LOOKUP: [_exam_session(finished_at=ANSWERED_AT, end_reason="finished")],
            EXAM_SLOT_ROWS: slots,
        }
    )
    first = client.post("/api/sessions/7/submit")
    second = client.post("/api/sessions/7/submit")
    assert first.status_code == 200 and second.status_code == 200, first.text
    assert first.json() == second.json()
    body = first.json()
    assert body["answeredCount"] == 1
    assert body["unansweredCount"] == 1
    assert body["correctCount"] == 1
    assert body["bySubject"] == [{"subjectCode": 1, "correct": 1, "score": 5, "passed": False}]

    # 재제출은 아무것도 쓰지 않는다 — 원장·누계·슬롯·세션 모두 그대로다.
    assert fake.executed(ATTEMPT_BATCH) == []
    assert fake.executed(STATE_BATCH) == []
    assert fake.executed(SLOT_GRADE_BATCH) == []
    assert fake.executed(SLOT_UNANSWERED) == []
    assert fake.executed(EXAM_FINISH) == []


def test_get_session_detail_exam_result_only_after_finish(client, fake_db):
    """세션 단건 조회는 제출된 모의고사에만 점수 요약을 싣는다(진행 중이면 null)."""
    stats = [
        {"item_count": 1, "answered_count": 1, "next_seq": None, "correct_count": 1, "wrong_count": 0}
    ]
    slots = [exam_slot_row(1, "2022-1-001", choice_no=2, is_correct=True, subject_code=1)]
    submitted = fake_db(
        {
            SESSION_SELECT: [
                _exam_session(finished_at=ANSWERED_AT, end_reason="finished", answered=1, correct=1)
            ],
            SLOT_STATS: stats,
            SLOT_LIST: [],
            EXAM_SLOT_ROWS: slots,
        }
    )
    body = client.get("/api/sessions/7").json()
    assert body["examResult"]["correctCount"] == 1
    assert body["examResult"]["bySubject"] == [
        {"subjectCode": 1, "correct": 1, "score": 5, "passed": False}
    ]
    assert submitted.executed(ATTEMPT_BATCH) == []

    ongoing = fake_db(
        {
            SESSION_SELECT: [_exam_session()],
            SLOT_STATS: stats,
            SLOT_LIST: [],
            EXAM_SLOT_ROWS: slots,
        }
    )
    assert client.get("/api/sessions/7").json()["examResult"] is None
    # 진행 중에는 점수를 계산하지 않는다(슬롯을 읽지도 않는다).
    assert ongoing.executed(EXAM_SLOT_ROWS) == []


def test_get_session_item_shows_unanswered_result_after_submit(client, fake_db):
    """제출 뒤 미응답 슬롯 조회: choiceNo=null·isCorrect=false 인 채로 해설(result)을 준다."""
    fake = fake_db(
        {
            SESSION_SELECT: [_exam_session(finished_at=ANSWERED_AT, end_reason="finished")],
            SLOT_ONE: [slot_row(seq=3, question_id=QUESTION_ID, choice_no=None, is_correct=False)],
            QUESTION_SELECT: [question_row()],
            ANSWER_SELECT: [{"answer": 2, "explanation": "정답 해설", "key_point": "핵심 개념"}],
            CHOICES_SELECT: choice_analysis_rows(2),
            STATE_SELECT_ONE: [],
        }
    )
    response = client.get("/api/sessions/7/items/3")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["choiceNo"] is None
    assert body["isCorrect"] is False
    assert body["result"]["choiceNo"] is None
    assert body["result"]["isCorrect"] is False
    assert body["result"]["answer"] == 2
    assert body["result"]["explanation"] == "정답 해설"
    assert body["state"] is None
    assert fake.executed(ATTEMPT_INSERT) == []


def exam_rows(pattern: str) -> list[dict]:
    """과목별 정답 수 패턴('1:8, 2:12' 형식)을 20문항씩 슬롯 행으로 편다.

    각 과목의 앞 n문항은 정답, 나머지는 오답으로 채운다(미응답은 넣지 않는다).
    """
    rows = []
    seq = 0
    for chunk in pattern.split(","):
        code, correct = chunk.strip().split(":")
        for number in range(1, 21):
            seq += 1
            rows.append(
                exam_slot_row(
                    seq,
                    f"2022-1-{seq:03d}",
                    choice_no=1,
                    is_correct=number <= int(correct),
                    subject_code=int(code),
                )
            )
    return rows


@pytest.mark.parametrize(
    ("pattern", "passed", "average"),
    [
        ("1:8, 2:12, 3:13, 4:13, 5:14", True, 60.0),   # 과목 40점·평균 60점 경계에서 통과
        ("1:8, 2:12, 3:12, 4:12, 5:15", False, 59.0),  # 매 과목 40점 이상이지만 평균 59점
        ("1:7, 2:20, 3:20, 4:20, 5:20", False, 87.0),  # 평균은 넘지만 35점 과목이 하나
    ],
)
def test_exam_summary_pass_boundaries(pattern, passed, average):
    """합격 판정은 매 과목 40점 이상 '이면서' 전 과목 평균 60점 이상이다."""
    summary = grading.exam_summary(
        exam_rows(pattern), session_id=7, submitted_at=ANSWERED_AT
    )
    assert summary.average_score == average
    assert summary.passed is passed
    assert [item.score for item in summary.by_subject] == [
        int(chunk.split(":")[1]) * 5 for chunk in pattern.split(",")
    ]
    assert [item.passed for item in summary.by_subject] == [
        int(chunk.split(":")[1]) >= 8 for chunk in pattern.split(",")
    ]
    assert summary.item_count == 100
    assert summary.answered_count == 100
    assert summary.unanswered_count == 0
