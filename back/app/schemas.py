"""요청·응답 스키마. JSON 키는 데이터셋 JSON 계약과 같은 camelCase 로 내보낸다."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

SessionMode = Literal["exam", "subject", "random", "review"]
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
    elapsed_ms: int | None = Field(default=None, ge=0)


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


class SessionOut(ApiModel):
    id: int
    mode: SessionMode
    exam_id: str | None = None
    subject_code: int | None = None
    started_at: datetime
    finished_at: datetime | None = None
    answered: int = 0
    correct: int = 0


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
