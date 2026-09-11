"""테스트용 행 모양 헬퍼.

실제 SELECT 가 돌려주는 컬럼 이름과 값을 맞춰 둔다(psycopg dict_row 기준).
"""
from __future__ import annotations

from datetime import date, datetime, timezone

ANSWERED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
REVIEW_DUE = date(2026, 9, 1)
CHOICE_TEXT = {1: "보기 하나", 2: "보기 둘", 3: "보기 셋", 4: "보기 넷"}


def question_row(**overrides) -> dict:
    """queries.QUESTION_SELECT 가 돌려주는 문항 1행."""
    row = {
        "id": "2022-1-001",
        "exam_id": "2022-1",
        "number": 1,
        "subject_code": 1,
        "subject_name": "소프트웨어 설계",
        "stem": "다음 중 옳은 것은?",
        "passage": None,
        "passage_kind": None,
        "difficulty": 2,
        "figure_needed": False,
        "figure_kind": None,
        "figure_image": None,
        "figure_alt": None,
        "choices": [{"no": no, "text": text} for no, text in CHOICE_TEXT.items()],
        "tags": ["테스트"],
        "state": None,
    }
    row.update(overrides)
    return row


def question_content_row(**overrides) -> dict:
    """중복 판정용 조회(queries.CONTENT_KEY_SELECT) 1행.

    question_row 와 같은 문항을 가리키며, 보기 본문은 번호 순서의 문자열 배열로 온다.
    """
    row = {
        "id": "2022-1-001",
        "stem": "다음 중 옳은 것은?",
        "passage": None,
        "passage_kind": None,
        "figure_needed": False,
        "figure_kind": None,
        "figure_alt": None,
        "choice_texts": list(CHOICE_TEXT.values()),
    }
    row.update(overrides)
    return row


def state_row(**overrides) -> dict:
    """ipe.study_state 1행."""
    row = {
        "question_id": "2022-1-001",
        "attempt_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "last_is_correct": None,
        "last_choice_no": None,
        "last_answered_at": None,
        "streak": 0,
        "bookmarked": False,
        "note": None,
        "review_due_on": None,
        "updated_at": ANSWERED_AT,
    }
    row.update(overrides)
    return row


def choice_analysis_rows(answer: int = 2) -> list[dict]:
    """ipe.question_choice 4행. answer 번호만 is_correct=True."""
    return [
        {"no": no, "is_correct": no == answer, "why": f"보기 {no} 해설"}
        for no in sorted(CHOICE_TEXT)
    ]


def session_row(**overrides) -> dict:
    """진도 라우터의 SESSION_SELECT 가 돌려주는 세션 1행."""
    row = {
        "id": 7,
        "mode": "random",
        "exam_id": None,
        "subject_code": None,
        "started_at": ANSWERED_AT,
        "finished_at": None,
        "answered": 0,
        "correct": 0,
    }
    row.update(overrides)
    return row
