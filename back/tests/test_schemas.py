"""스키마 직렬화 테스트.

- 조회용 스키마(QuestionOut)에는 정답·해설 필드가 없다.
- 채점 응답(GradeResult)에는 정답·해설·보기별 해설이 있다.
- JSON 키는 데이터셋 계약과 같은 camelCase 로 나간다.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.queries import figure_url, to_question
from app.schemas import GradeRequest, GradeResult, QuestionOut, SessionCreate, StateOut

from helpers import assert_no_answer_leak
from sample_data import ANSWERED_AT, choice_analysis_rows, question_row, state_row


def test_question_out_has_no_secret_fields():
    """조회 스키마 필드에 정답·해설·보기별 해설이 없어야 한다."""
    fields = set(QuestionOut.model_fields)
    assert not fields & {"answer", "explanation", "choices_analysis", "key_point"}
    assert {"id", "stem", "choices", "figure", "tags", "state"} <= fields


def test_question_out_serializes_camel_case():
    question = to_question(
        question_row(
            figure_needed=True,
            figure_kind="diagram",
            figure_image="figures/2022-1/001.png",
            figure_alt="순서도",
        )
    )
    dumped = question.model_dump(by_alias=True)
    assert set(dumped) == {
        "id",
        "examId",
        "number",
        "subjectCode",
        "subjectName",
        "stem",
        "passage",
        "passageKind",
        "difficulty",
        "choices",
        "figure",
        "tags",
        "state",
    }
    assert dumped["examId"] == "2022-1"
    assert dumped["subjectCode"] == 1
    assert dumped["figure"] == {
        "needed": True,
        "kind": "diagram",
        "imageUrl": "/figures/2022-1/001.png",
        "alt": "순서도",
    }
    assert dumped["choices"][0] == {"no": 1, "text": "보기 하나"}
    assert_no_answer_leak(dumped)


def test_to_question_maps_state_row():
    """study_state 행이 있으면 StateOut 으로 변환되고, 없으면 null 이다."""
    without_state = to_question(question_row())
    assert without_state.state is None

    question = to_question(question_row(state=state_row(attempt_count=3, correct_count=2, wrong_count=1)))
    assert question.state is not None
    assert question.state.attempt_count == 3
    assert question.state.correct_count == 2
    assert question.state.wrong_count == 1


def test_grade_result_carries_answer_and_explanation():
    """채점 응답은 정답 공개가 목적이므로 정답·해설·보기별 해설을 싣는다."""
    result = GradeResult(
        question_id="2022-1-001",
        choice_no=2,
        is_correct=True,
        answer=2,
        explanation="정답 해설",
        key_point="핵심 개념",
        choices_analysis=[
            # DB 행(is_correct)을 응답 스키마(correct)로 바꿔 넣는다.
            {"no": row["no"], "correct": row["is_correct"], "why": row["why"]}
            for row in choice_analysis_rows(2)
        ],
        state=state_row(last_is_correct=True, last_choice_no=2),
    )
    dumped = result.model_dump(by_alias=True)
    assert dumped["answer"] == 2
    assert dumped["explanation"] == "정답 해설"
    assert dumped["keyPoint"] == "핵심 개념"
    assert len(dumped["choicesAnalysis"]) == 4
    assert sum(item["correct"] for item in dumped["choicesAnalysis"]) == 1
    assert [item["no"] for item in dumped["choicesAnalysis"] if item["correct"]] == [2]


@pytest.mark.parametrize("choice_no", [1, 2, 3, 4])
def test_grade_request_accepts_choice_1_to_4(choice_no):
    request = GradeRequest(choiceNo=choice_no)
    assert request.choice_no == choice_no
    assert request.session_id is None
    assert request.elapsed_ms is None


@pytest.mark.parametrize("choice_no", [0, 5, -1, 100])
def test_grade_request_rejects_out_of_range_choice(choice_no):
    """보기 번호는 1~4 밖이면 요청 단계에서 거부된다."""
    with pytest.raises(ValidationError):
        GradeRequest(choiceNo=choice_no)


def test_grade_request_validates_elapsed_and_session():
    assert GradeRequest(choiceNo=1, elapsedMs=0, sessionId=3).elapsed_ms == 0
    with pytest.raises(ValidationError):
        GradeRequest(choiceNo=1, elapsedMs=-1)


def test_state_out_parses_db_row():
    state = StateOut.model_validate(
        state_row(
            attempt_count=5,
            correct_count=4,
            wrong_count=1,
            last_is_correct=True,
            last_choice_no=3,
            last_answered_at=ANSWERED_AT,
            streak=2,
            bookmarked=True,
            note="메모",
            review_due_on=date(2026, 9, 1),
        )
    )
    assert state.attempt_count == 5
    assert state.last_is_correct is True
    assert state.last_answered_at == datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    dumped = state.model_dump(by_alias=True)
    assert dumped["lastIsCorrect"] is True
    assert dumped["reviewDueOn"] == date(2026, 9, 1)


@pytest.mark.parametrize(
    ("image", "expected"),
    [
        (None, None),
        ("", None),
        ("figures/2022-1/001.png", "/figures/2022-1/001.png"),
        ("/figures/2022-1/001.png", "/figures/2022-1/001.png"),
        ("  2022-1/001.png  ", "/figures/2022-1/001.png"),
    ],
)
def test_figure_url_mapping(image, expected):
    assert figure_url(image) == expected


def test_grade_request_allows_elapsed_ms_upper_bound():
    """elapsedMs 허용 상한은 DB integer 최대값과 같다(B-03)."""
    assert GradeRequest(choiceNo=1, elapsedMs=2147483647).elapsed_ms == 2147483647
    with pytest.raises(ValidationError):
        GradeRequest(choiceNo=1, elapsedMs=2147483648)


@pytest.mark.parametrize("blank", ["", "   "])
def test_session_create_normalizes_blank_exam_id(blank):
    """빈 문자열·공백뿐인 examId 는 null 로 정규화된다(B-02)."""
    assert SessionCreate(mode="random", examId=blank).exam_id is None


def test_session_create_keeps_real_exam_id():
    assert SessionCreate(mode="exam", examId="2026-1").exam_id == "2026-1"
