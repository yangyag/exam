"""세션·진도 API 테스트(DB 없이 가짜 커넥션으로).

- 세션 모드별 필수 인자 검증
- study_state PATCH 는 요청에 담긴 필드만 갱신한다.
- 목록 필터가 WHERE 절·파라미터로 정확히 반영된다.
"""
from __future__ import annotations

from datetime import date

from sample_data import ANSWERED_AT, session_row, state_row

SESSION_INSERT = "INSERT INTO ipe.study_session"
SESSION_SELECT = "FROM ipe.study_session s"
SESSION_UPDATE = "UPDATE ipe.study_session SET finished_at"
EXAM_EXISTS = "FROM ipe.exam WHERE id"
SUBJECT_EXISTS = "FROM ipe.subject WHERE code"
STATE_UPSERT = "INSERT INTO ipe.study_state"
QUESTION_EXISTS = "SELECT 1 FROM ipe.question WHERE id"
STATE_SELECT_ONE = "FROM ipe.study_state WHERE question_id"
STATE_LIST = "FROM ipe.study_state st"

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


def test_create_subject_session_requires_subject_code(client, fake_db):
    fake = fake_db({})
    response = client.post("/api/sessions", json={"mode": "subject"})
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
    fake = fake_db({SUBJECT_EXISTS: []})
    response = client.post("/api/sessions", json={"mode": "subject", "subjectCode": 5})
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


def test_sessions_list_passes_paging(client, fake_db):
    fake = fake_db({SESSION_SELECT: [session_row(answered=2, correct=1)]})
    response = client.get("/api/sessions", params={"limit": 5, "offset": 2})
    assert response.status_code == 200
    assert response.json()[0]["answered"] == 2

    sql, params = fake.single(SESSION_SELECT)
    assert "ORDER BY s.started_at DESC" in sql
    assert params == [5, 2]


def test_finish_session_is_idempotent(client, fake_db):
    """이미 끝난 세션을 다시 끝내도 현재 상태를 그대로 돌려준다."""
    fake = fake_db(
        {
            SESSION_UPDATE: [],
            "SELECT 1 FROM ipe.study_session WHERE id": [{"?column?": 1}],
            SESSION_SELECT: [session_row(id=9, finished_at=ANSWERED_AT, answered=2, correct=1)],
        }
    )
    response = client.post("/api/sessions/9/finish")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 9
    assert body["finishedAt"] is not None
    assert body["answered"] == 2
    assert body["correct"] == 1
    assert len(fake.executed(SESSION_UPDATE)) == 1


def test_finish_unknown_session_404(client, fake_db):
    fake_db({SESSION_UPDATE: [], "SELECT 1 FROM ipe.study_session WHERE id": []})
    response = client.post("/api/sessions/999/finish")
    assert response.status_code == 404
