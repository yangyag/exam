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
from app.schemas import (
    CycleResultOut,
    ExamResultOut,
    ExamSubjectScoreOut,
    GradeRequest,
    GradeResult,
    QuestionOut,
    SessionCreate,
    SessionDetailOut,
    SessionOut,
    SessionProgressOut,
    SlotAnswerRequest,
    SlotGradeResult,
    SlotSaveOut,
    StateOut,
)

from helpers import assert_no_answer_leak
from sample_data import ANSWERED_AT, choice_analysis_rows, question_row, session_row, state_row


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


def test_session_create_replace_active_defaults_false():
    """replaceActive 기본값은 false — 진행 중 세션이 있으면 409, true 면 중단 후 재생성."""
    assert SessionCreate(mode="exam_practice", examId="2026-1").replace_active is False
    assert SessionCreate(mode="exam_practice", examId="2026-1", replaceActive=True).replace_active is True


def test_session_out_carries_cycle_fields():
    """SessionOut 에 cycleId·roundNo·endReason 이 실린다(설계 5.4절)."""
    dumped = SessionOut.model_validate(
        session_row(mode="review", subject_code=1, cycle_id=3, round_no=2, end_reason="finished")
    ).model_dump(by_alias=True)
    assert dumped["cycleId"] == 3
    assert dumped["roundNo"] == 2
    assert dumped["endReason"] == "finished"


@pytest.mark.parametrize("choice_no", [1, 2, 3, 4, None])
def test_slot_answer_request_accepts_choice_or_null(choice_no):
    """모의고사 선택 해제(null)를 받아야 하므로 choiceNo 는 null 을 허용한다."""
    assert SlotAnswerRequest(choiceNo=choice_no).choice_no == choice_no


@pytest.mark.parametrize("choice_no", [0, 5, -1])
def test_slot_answer_request_rejects_out_of_range(choice_no):
    with pytest.raises(ValidationError):
        SlotAnswerRequest(choiceNo=choice_no)


def test_slot_answer_request_validates_elapsed():
    assert SlotAnswerRequest(choiceNo=1, elapsedMs=2147483647).elapsed_ms == 2147483647
    with pytest.raises(ValidationError):
        SlotAnswerRequest(choiceNo=1, elapsedMs=-1)


def test_slot_grade_result_serializes_progress_and_cycle():
    """슬롯 제출 응답은 GradeResult + session + roundResult + cycle 을 camelCase 로 싣는다."""
    result = SlotGradeResult(
        question_id="2022-1-001",
        choice_no=2,
        is_correct=True,
        answer=2,
        explanation="정답 해설",
        choices_analysis=[
            {"no": row["no"], "correct": row["is_correct"], "why": row["why"]}
            for row in choice_analysis_rows(2)
        ],
        state=state_row(last_is_correct=True, last_choice_no=2),
        session=SessionProgressOut(id=7, item_count=3, answered_count=2, next_seq=3, finished=False),
        round_result=None,
        cycle=CycleResultOut(id=3, status="active"),
    )
    dumped = result.model_dump(by_alias=True)
    assert dumped["session"] == {
        "id": 7,
        "itemCount": 3,
        "answeredCount": 2,
        "nextSeq": 3,
        "finished": False,
    }
    assert dumped["roundResult"] is None
    assert dumped["cycle"] == {
        "id": 3,
        "status": "active",
        "nextSessionId": None,
        "nextRoundNo": None,
        "nextItemCount": None,
    }


def test_slot_save_out_has_no_answer_fields():
    """모의고사 선택 저장 응답에는 정답·해설이 없어야 한다."""
    dumped = SlotSaveOut(seq=1, choice_no=None, answered_at=None).model_dump(by_alias=True)
    assert dumped == {"seq": 1, "choiceNo": None, "answeredAt": None}
    assert_no_answer_leak(dumped)


def test_grade_result_allows_null_choice_for_unanswered_exam_item():
    """제출된 모의고사의 미응답 문항 결과는 choiceNo=null·isCorrect=false 로 온다(해설은 그대로)."""
    result = GradeResult(
        question_id="2022-1-001",
        choice_no=None,
        is_correct=False,
        answer=2,
        explanation="정답 해설",
        choices_analysis=[
            {"no": row["no"], "correct": row["is_correct"], "why": row["why"]}
            for row in choice_analysis_rows(2)
        ],
        state=state_row(),
    )
    dumped = result.model_dump(by_alias=True)
    assert dumped["choiceNo"] is None
    assert dumped["isCorrect"] is False
    assert dumped["answer"] == 2


def test_exam_result_serializes_camel_case():
    """모의고사 점수 요약은 bySubject·averageScore·passed 를 camelCase 로 싣는다."""
    result = ExamResultOut(
        session_id=7,
        item_count=100,
        answered_count=95,
        unanswered_count=5,
        correct_count=60,
        wrong_count=35,
        by_subject=[
            ExamSubjectScoreOut(subject_code=1, correct=8, score=40, passed=True),
            ExamSubjectScoreOut(subject_code=2, correct=7, score=35, passed=False),
        ],
        average_score=60.0,
        passed=False,
        submitted_at=ANSWERED_AT,
    )
    dumped = result.model_dump(by_alias=True)
    assert set(dumped) == {
        "sessionId",
        "itemCount",
        "answeredCount",
        "unansweredCount",
        "correctCount",
        "wrongCount",
        "bySubject",
        "averageScore",
        "passed",
        "submittedAt",
    }
    assert dumped["sessionId"] == 7
    assert dumped["unansweredCount"] == 5
    assert dumped["bySubject"] == [
        {"subjectCode": 1, "correct": 8, "score": 40, "passed": True},
        {"subjectCode": 2, "correct": 7, "score": 35, "passed": False},
    ]
    assert dumped["averageScore"] == 60.0
    assert dumped["submittedAt"] == ANSWERED_AT


def test_session_detail_exam_result_is_null_until_submitted():
    """examResult 는 제출된 모의고사에만 붙는다 — 기본값은 null 이다."""
    dumped = SessionDetailOut.model_validate(
        session_row(id=7, mode="exam", exam_id="2026-1")
    ).model_dump(by_alias=True)
    assert dumped["examResult"] is None
    assert set(dumped) >= {"itemCount", "answeredCount", "nextSeq", "items", "examResult"}
