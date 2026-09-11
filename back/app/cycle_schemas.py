"""과목 사이클 요청·응답 스키마(설계 5.1~5.2절).

JSON 키는 기존 규약대로 camelCase 다 — `schemas.ApiModel` 을 그대로 물려받는다.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from .schemas import ApiModel, SessionMode

# study_cycle.status 와 같은 값 집합(db/003_study_items.sql).
CycleStatus = Literal["active", "completed", "abandoned"]
# 홈 요약의 과목 상태(설계 5.1절).
HomeStatus = Literal["not_started", "first_pass", "reviewing", "completed"]


class CycleCreate(ApiModel):
    """`POST /api/subject-cycles` 본문."""

    subject_code: int = Field(ge=1, le=5)
    # 진행 중 사이클이 있으면 409 이고, true 면 그 사이클을 abandoned 로 닫고 새로 만든다(설계 5.2절).
    replace_active: bool = False


class RoundOut(ApiModel):
    """사이클의 라운드 1회(= 세션). 집계는 슬롯(study_session_item) 기준이다.

    `itemCount` 는 라운드에 담긴 문항 수, `answered` 는 답한 슬롯 수, `correct` 는 맞힌 수다.
    """

    session_id: int
    round_no: int
    mode: SessionMode
    item_count: int = 0
    answered: int = 0
    correct: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    end_reason: str | None = None


class CycleOut(ApiModel):
    """사이클 단건·목록·생성 응답. `startedAt` 은 사이클 생성 시각(study_cycle.created_at)이다."""

    id: int
    subject_code: int
    subject_name: str | None = None
    status: CycleStatus
    started_at: datetime
    ended_at: datetime | None = None
    rounds: list[RoundOut] = Field(default_factory=list)


class RoundSummaryOut(ApiModel):
    """홈 요약의 라운드 집계. 라운드가 없으면 null 이고, 있으면 세 값이 항상 채워진다."""

    session_id: int | None = None
    round_no: int | None = None
    item_count: int = 0
    answered: int = 0
    correct: int = 0


class HomeCycleOut(ApiModel):
    """홈에 보여 줄 사이클: 진행 중(active)이거나, 없으면 마지막 완료(completed) 사이클."""

    id: int
    status: CycleStatus
    started_at: datetime
    ended_at: datetime | None = None
    first_round: RoundSummaryOut | None = None
    # 진행 중 사이클의 열린 라운드. 완료 사이클이거나 진행 중인데 열린 라운드가 없으면 null.
    current_round: RoundSummaryOut | None = None


class SubjectOverviewOut(ApiModel):
    """과목 1개의 홈 요약(`GET /api/subject-cycles/overview` 한 행)."""

    subject_code: int
    subject_name: str
    # 중복 제거(content_key) 후 문항 수. 요청할 때마다 계산한다(설계 5.1절).
    unique_question_count: int
    status: HomeStatus
    cycle: HomeCycleOut | None = None
