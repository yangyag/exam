"""요청·응답 스키마. JSON 키는 데이터셋 JSON 계약과 같은 camelCase 로 내보낸다."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

SessionMode = Literal["exam", "exam_practice", "subject", "random", "review"]
PassageKind = Literal["code", "table", "text"]
FigureKind = Literal["diagram", "screen"]


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class ChoiceOut(ApiModel):
    no: int
    text: str


class FigureOut(ApiModel):
    needed: bool = False
    kind: FigureKind | None = None
    image_url: str | None = None
    alt: str | None = None


class StateOut(ApiModel):
    question_id: str
    attempt_count: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    last_is_correct: bool | None = None
    last_choice_no: int | None = None
    last_answered_at: datetime | None = None
    streak: int = 0
    bookmarked: bool = False
    note: str | None = None
    review_due_on: date | None = None
    updated_at: datetime | None = None


class QuestionOut(ApiModel):
    """조회 응답. 정답·해설·보기별 해설은 포함하지 않는다(채점 응답에서만)."""

    id: str
    exam_id: str
    number: int
    subject_code: int
    subject_name: str | None = None
    stem: str
    passage: str | None = None
    passage_kind: PassageKind | None = None
    difficulty: int | None = None
    choices: list[ChoiceOut] = Field(default_factory=list)
    figure: FigureOut = Field(default_factory=FigureOut)
    tags: list[str] = Field(default_factory=list)
    state: StateOut | None = None


class QuestionPage(ApiModel):
    items: list[QuestionOut]
    total: int
    limit: int
    offset: int


class SubjectOut(ApiModel):
    code: int
    name: str
    from_no: int
    to_no: int
    question_count: int | None = None


class ExamOut(ApiModel):
    id: str
    year: int
    round: int
    title: str
    question_count: int = 0
    figure_count: int = 0


class ExamDetail(ExamOut):
    source_pdf: str | None = None
    subjects: list[SubjectOut] = Field(default_factory=list)


class TagOut(ApiModel):
    id: int
    name: str
    question_count: int = 0


class GradeRequest(ApiModel):
    choice_no: int = Field(ge=1, le=4)
    session_id: int | None = None
    # elapsed_ms 는 PostgreSQL integer 컬럼(study_attempt.elapsed_ms)에 들어가므로 상한을 맞춘다(B-03).
    elapsed_ms: int | None = Field(default=None, ge=0, le=2147483647)


class ChoiceAnalysisOut(ApiModel):
    no: int
    correct: bool
    why: str


class GradeResult(ApiModel):
    question_id: str
    choice_no: int
    is_correct: bool
    answer: int
    explanation: str
    key_point: str | None = None
    choices_analysis: list[ChoiceAnalysisOut]
    state: StateOut


class SessionCreate(ApiModel):
    mode: SessionMode
    exam_id: str | None = None
    subject_code: int | None = Field(default=None, ge=1, le=5)
    # 진행 중인 같은 모드·회차 세션이 있으면 409 이고, true 면 그 세션을 abandoned 로 닫고 새로 만든다(설계 5.2~5.3절).
    replace_active: bool = False

    @field_validator("exam_id", mode="before")
    @classmethod
    def _blank_exam_id_as_none(cls, value: object) -> object:
        """프론트 선택 입력의 초기값인 빈 문자열은 '회차 없음'(null)으로 본다(B-02).

        라우터는 값이 없으면 회차 존재 검사를 건너뛰므로, 빈 문자열을 그대로 두면
        없는 회차를 INSERT 하다가 외래 키 위반(500)이 난다. mode=exam 에서는 이 값이
        null 이 되어 기존 400(examId 필요)으로 간다.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SessionOut(ApiModel):
    id: int
    mode: SessionMode
    exam_id: str | None = None
    subject_code: int | None = None
    cycle_id: int | None = None
    round_no: int | None = None
    end_reason: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    answered: int = 0
    correct: int = 0


class SessionItemOut(ApiModel):
    """세션 슬롯 1개(요약). 진행 중인 모의고사는 isCorrect 를 null 로 가린다."""

    seq: int
    question_id: str
    choice_no: int | None = None
    is_correct: bool | None = None


class SessionDetailOut(SessionOut):
    """세션 단건 조회. 슬롯 목록과 진행 위치(nextSeq)를 함께 준다."""

    item_count: int = 0
    answered_count: int = 0
    next_seq: int | None = None
    items: list[SessionItemOut] = Field(default_factory=list)


class SessionItemDetail(QuestionOut):
    """슬롯 문항 단건: QuestionOut + 슬롯 상태 + result.

    채점 전에는 state 를 null 로 빼서 이전 풀이의 정답 여부가 드러나지 않게 한다.
    """

    seq: int
    choice_no: int | None = None
    is_correct: bool | None = None
    answered_at: datetime | None = None
    result: GradeResult | None = None


class SlotAnswerRequest(ApiModel):
    """슬롯 제출. 모의고사에서 choiceNo=null 은 선택 해제다(연습에서는 필수)."""

    choice_no: int | None = Field(default=None, ge=1, le=4)
    elapsed_ms: int | None = Field(default=None, ge=0, le=2147483647)


class SessionProgressOut(ApiModel):
    """제출 응답에 붙는 세션 진행 정보. nextSeq 는 다음에 풀 슬롯(없으면 null)."""

    id: int
    item_count: int = 0
    answered_count: int = 0
    next_seq: int | None = None
    finished: bool = False


class RoundResultOut(ApiModel):
    """이 제출로 라운드(세션)가 끝났을 때만 붙는다. roundNo 는 회차 연습·모의고사면 null."""

    round_no: int | None = None
    item_count: int
    correct: int
    wrong: int


class CycleResultOut(ApiModel):
    """사이클 라운드일 때만 붙는다. 다음 라운드가 없으면 nextSessionId 가 null."""

    id: int
    status: str
    next_session_id: int | None = None
    next_round_no: int | None = None
    next_item_count: int | None = None


class SlotGradeResult(GradeResult):
    """연습 슬롯 제출 응답: 채점 결과 + 세션 진행 + 라운드·사이클 상태."""

    session: SessionProgressOut
    round_result: RoundResultOut | None = None
    cycle: CycleResultOut | None = None


class SlotSaveOut(ApiModel):
    """모의고사 선택 저장 응답. 정답·해설은 최종 제출 전까지 돌려주지 않는다."""

    seq: int
    choice_no: int | None = None
    answered_at: datetime | None = None


class StateUpdate(ApiModel):
    bookmarked: bool | None = None
    note: str | None = None
    review_due_on: date | None = None


class ProgressItem(StateOut):
    exam_id: str
    number: int
    subject_code: int
    subject_name: str | None = None
    stem: str


class SubjectStatsOut(ApiModel):
    subject_code: int
    subject_name: str
    answered: int
    correct: int
    wrong: int
    questions_total: int
    questions_seen: int
    accuracy_pct: float | None = None


class WrongQuestionOut(ApiModel):
    question_id: str
    exam_id: str
    number: int
    subject_code: int
    subject_name: str
    stem: str
    attempt_count: int
    wrong_count: int
    last_choice_no: int | None = None
    last_is_correct: bool | None = None
    last_answered_at: datetime | None = None
    bookmarked: bool = False
    note: str | None = None
    review_due_on: date | None = None


class ReviewDueOut(ApiModel):
    question_id: str
    exam_id: str
    number: int
    subject_code: int
    subject_name: str
    stem: str
    review_due_on: date
    overdue_days: int
    last_is_correct: bool | None = None
    wrong_count: int
    note: str | None = None
