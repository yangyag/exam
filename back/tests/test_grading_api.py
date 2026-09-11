"""채점 API 테스트(DB 없이 가짜 커넥션으로).

- 정답을 고른 경우와 오답을 고른 경우 모두 정답 여부·정답 번호·해설이 정확해야 한다.
- study_attempt INSERT 와 study_state UPSERT 에 넘어가는 파라미터로 진도 갱신 계획을 검증한다.
  (실제 누계 갱신은 SQL 이 하므로 통합 테스트에서 확인한다.)
- sessionId 가드(없는 세션 404 · 종료된 세션 409 · 슬롯 세션 409)와 sessionId 없이 채점하는 기존 계약을 고정한다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sample_data import choice_analysis_rows, state_row

ANSWER_SELECT = "SELECT answer, explanation, key_point FROM ipe.question"
ATTEMPT_INSERT = "INSERT INTO ipe.study_attempt"
STATE_UPSERT = "INSERT INTO ipe.study_state"
CHOICES_SELECT = "FROM ipe.question_choice"
SESSION_LOOKUP = "FROM ipe.study_session WHERE id"
SLOT_GUARD = "FROM ipe.study_session_item"

QUESTION_ID = "2022-1-001"
ANSWER = 2
FINISHED_AT = datetime(2026, 9, 5, 3, 0, tzinfo=timezone.utc)


def _answer_rules() -> dict:
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

    return {
        ANSWER_SELECT: [{"answer": ANSWER, "explanation": "정답 해설", "key_point": "핵심 개념"}],
        ATTEMPT_INSERT: [],
        STATE_UPSERT: state_from_params,
        CHOICES_SELECT: choice_analysis_rows(ANSWER),
        SESSION_LOOKUP: [{"finished_at": None}],
        SLOT_GUARD: [],
    }


@pytest.fixture()
def fake(fake_db):
    return fake_db(_answer_rules())


def grade(client, choice_no: int, **extra):
    return client.post(f"/api/questions/{QUESTION_ID}/answer", json={"choiceNo": choice_no, **extra})


def test_correct_choice_returns_grading_result(client, fake):
    """정답을 고르면 isCorrect=true, 정답 번호·해설·보기별 해설이 함께 온다."""
    response = grade(client, 2, sessionId=7, elapsedMs=1500)
    assert response.status_code == 200
    body = response.json()
    assert body["isCorrect"] is True
    assert body["choiceNo"] == 2
    assert body["answer"] == 2
    assert body["explanation"] == "정답 해설"
    assert body["keyPoint"] == "핵심 개념"
    analysis = body["choicesAnalysis"]
    assert [item["no"] for item in analysis] == [1, 2, 3, 4]
    assert [item["no"] for item in analysis if item["correct"]] == [2]
    assert sum(item["correct"] for item in analysis) == 1
    assert body["state"]["lastIsCorrect"] is True
    assert body["state"]["lastChoiceNo"] == 2
    assert body["state"]["streak"] == 1


def test_correct_choice_records_attempt_and_state(client, fake):
    grade(client, 2, sessionId=7, elapsedMs=1500)
    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params == (7, QUESTION_ID, 2, True, 1500)
    _, state_params = fake.single(STATE_UPSERT)
    # (문항, 정답 수 +1, 오답 수 +0, 마지막 정답 여부, 고른 번호, 연속 정답 +1)
    assert state_params == (QUESTION_ID, 1, 0, True, 2, 1)


def test_wrong_choice_returns_answer_but_marks_incorrect(client, fake):
    """오답을 골라도 채점 응답이므로 정답 번호·해설은 온다(isCorrect=false)."""
    response = grade(client, 1)
    assert response.status_code == 200
    body = response.json()
    assert body["isCorrect"] is False
    assert body["answer"] == 2
    assert body["explanation"] == "정답 해설"
    assert [item["no"] for item in body["choicesAnalysis"] if item["correct"]] == [2]
    assert body["state"]["lastIsCorrect"] is False

    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params == (None, QUESTION_ID, 1, False, None)
    _, state_params = fake.single(STATE_UPSERT)
    assert state_params == (QUESTION_ID, 0, 1, False, 1, 0)
    # 세션을 주지 않았으면 세션 조회도 하지 않는다.
    assert fake.executed(SESSION_LOOKUP) == []


@pytest.mark.parametrize("choice_no", [0, 5, -1])
def test_choice_out_of_range_rejected_without_writes(client, fake, choice_no):
    """1~4 밖의 보기 번호는 422 이고 진도에 아무것도 기록되지 않는다."""
    response = grade(client, choice_no)
    assert response.status_code == 422
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []


def test_negative_elapsed_rejected(client, fake):
    response = grade(client, 2, elapsedMs=-1)
    assert response.status_code == 422
    assert fake.executed(ATTEMPT_INSERT) == []


def test_elapsed_ms_upper_bound_accepted(client, fake):
    """elapsedMs 상한(2147483647)은 통과하고 그대로 저장된다(B-03)."""
    response = grade(client, 2, sessionId=7, elapsedMs=2147483647)
    assert response.status_code == 200
    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params == (7, QUESTION_ID, 2, True, 2147483647)


def test_elapsed_ms_above_upper_bound_rejected(client, fake):
    """DB integer 범위를 넘는 elapsedMs 는 요청 단계에서 422 로 거부된다(B-03)."""
    response = grade(client, 2, sessionId=7, elapsedMs=2147483648)
    assert response.status_code == 422
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []


def test_unknown_question_404_without_writes(client, fake_db):
    fake_db({})
    response = grade(client, 2)
    assert response.status_code == 404
    assert "찾을 수 없습니다" in response.json()["detail"]


def test_unknown_session_404_without_writes(client, fake_db):
    rules = _answer_rules()
    rules[SESSION_LOOKUP] = []
    fake = fake_db(rules)
    response = grade(client, 2, sessionId=999)
    assert response.status_code == 404
    assert "세션" in response.json()["detail"]
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []


def test_ongoing_session_grades_and_records(client, fake):
    """진행 중 세션(finished_at NULL)은 그대로 채점되고 그 세션에 기록된다."""
    response = grade(client, 2, sessionId=7)
    assert response.status_code == 200
    sql, params = fake.single(SESSION_LOOKUP)
    assert sql.endswith("FOR UPDATE"), sql  # 세션 행 잠금으로 종료와 순서를 보장한다(B-01)
    assert params == (7,)
    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params == (7, QUESTION_ID, 2, True, None)


def test_slot_session_rejected_with_409_without_writes(client, fake_db):
    """슬롯(study_session_item)이 있는 세션은 /answer 로 기록할 수 없다 — 슬롯 제출을 쓴다."""
    rules = _answer_rules()
    rules[SLOT_GUARD] = [{"?column?": 1}]
    fake = fake_db(rules)
    response = grade(client, 2, sessionId=7)
    assert response.status_code == 409
    assert "슬롯" in response.json()["detail"]
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []
    # 슬롯 판별은 세션 잠금 뒤에 한다(세션 → 슬롯 순서, 설계 4.6절).
    assert [sql for sql, _ in fake.executed(SESSION_LOOKUP)][0].endswith("FOR UPDATE")


def test_finished_session_rejected_with_409_without_writes(client, fake_db):
    """종료된 세션에 채점하면 409 이고 진도에는 아무것도 쓰지 않는다."""
    rules = _answer_rules()
    rules[SESSION_LOOKUP] = [{"finished_at": FINISHED_AT}]
    fake = fake_db(rules)
    response = grade(client, 2, sessionId=7)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "종료된 세션" in detail and "새 세션" in detail
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []


def test_sessionless_grading_keeps_working(client, fake):
    """sessionId 를 생략한 채점은 세션을 조회하지 않고 기존 계약대로 동작한다."""
    response = grade(client, 2)
    assert response.status_code == 200
    assert fake.executed(SESSION_LOOKUP) == []
    _, attempt_params = fake.single(ATTEMPT_INSERT)
    assert attempt_params[0] is None


def test_write_requires_token_when_configured(client, fake, monkeypatch):
    """EXAM_API_TOKEN 이 설정되면 채점 요청에 X-Exam-Token 헤더가 필요하다."""
    from app.config import get_settings

    monkeypatch.setenv("EXAM_API_TOKEN", "s3cret-token")
    get_settings.cache_clear()  # 앱 생성 때 캐시된 설정(토큰 없음)을 버린다

    denied = grade(client, 2)
    assert denied.status_code == 401
    assert fake.executed(ATTEMPT_INSERT) == []
    assert fake.executed(STATE_UPSERT) == []

    allowed = client.post(
        f"/api/questions/{QUESTION_ID}/answer",
        json={"choiceNo": 2},
        headers={"X-Exam-Token": "s3cret-token"},
    )
    assert allowed.status_code == 200
    assert len(fake.executed(ATTEMPT_INSERT)) == 1
