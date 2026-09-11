"""과목 사이클: 목록 구성·라운드 연쇄·홈 요약(설계 4.5·5.1~5.2절).

- 라운드 세션과 슬롯은 `cycles.create_round_session`, 중단·새로 구성은
  `cycles.replace_active_cycle`, 라운드 전환은 `cycles.advance_round_if_complete`(M1 공용 모듈)가 맡는다.
  이 라우터는 목록을 구성하고 그 위에서 읽고 쓴다.
- 조회는 `cycle_queries`(사이클 조회 SQL), 응답 모델은 `cycle_schemas` 를 쓴다.
"""
from __future__ import annotations

from typing import Annotated

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import cycle_queries, cycles
from ..cycle_queries import (
    fetch_cycle,
    fetch_open_rounds,
    fetch_rounds,
    fetch_subject,
    fetch_subjects,
    find_cycles,
    pick_home_cycles,
    to_cycle_out,
    to_round_summary,
)
from ..cycle_schemas import (
    CycleCreate,
    CycleOut,
    CycleStatus,
    HomeCycleOut,
    SubjectOverviewOut,
)
from ..deps import Conn, require_token

router = APIRouter(prefix="/api/subject-cycles", tags=["cycles"])


def _cycle_out(conn: Conn, cycle_id: int) -> CycleOut:
    """사이클 1건 + 라운드 목록. 없으면 404."""
    cycle = fetch_cycle(conn, cycle_id)
    if cycle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"사이클 {cycle_id} 를 찾을 수 없습니다")
    return to_cycle_out(cycle, fetch_rounds(conn, [cycle_id]).get(cycle_id, []))


@router.post(
    "",
    response_model=CycleOut,
    status_code=status.HTTP_201_CREATED,
    summary="과목 사이클 시작",
    dependencies=[Depends(require_token)],
)
def create_subject_cycle(payload: CycleCreate, conn: Conn):
    """과목 문항 전체를 중복 제거·셔플해 라운드 1 세션까지 만든다(설계 4.5·5.2절).

    - 과목 문항 260개를 `content_key()` 로 묶고 그룹 대표(가장 최근 회차 = id 최대)를 모은 뒤
      무작위로 섞어 슬롯(seq 1..N)으로 저장한다. 목록은 만든 뒤 바뀌지 않는다.
    - 진행 중 사이클이 있으면 409 다. `replaceActive=true` 면 그 사이클과 그 시점의 열린 라운드를
      같은 트랜잭션에서 abandoned 로 닫고 새 사이클을 만든다.
    - 두 기기에서 동시에 시작하면 `study_cycle_active_uk` 위반이 나므로 409 로 돌려준다(설계 4.6절).
    """
    if fetch_subject(conn, payload.subject_code) is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"과목 {payload.subject_code} 를 찾을 수 없습니다"
        )
    question_ids = cycle_queries.unique_question_ids(
        cycle_queries.subject_content_rows(conn, payload.subject_code)
    )
    if not question_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"과목 {payload.subject_code} 에 문항이 없습니다"
        )

    try:
        with conn.transaction():
            cycles.replace_active_cycle(
                conn,
                subject_code=payload.subject_code,
                replace_active=payload.replace_active,
            )
            cycle = cycle_queries.insert_cycle(conn, payload.subject_code)
            cycles.create_round_session(
                conn,
                mode="subject",
                question_ids=question_ids,
                subject_code=payload.subject_code,
                cycle_id=cycle["id"],
                round_no=1,
                shuffle=True,
            )
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"과목 {payload.subject_code} 에 이미 진행 중인 사이클이 있습니다."
            " replaceActive=true 로 새로 구성하세요",
        ) from exc
    return _cycle_out(conn, cycle["id"])


def _overview_item(
    subject: dict,
    unique_question_count: int,
    picked: dict | None,
    rounds: list[dict],
    open_round: dict | None,
) -> SubjectOverviewOut:
    """과목 1개의 홈 요약(설계 5.1절).

    - 진행 중·완료 사이클이 없으면 not_started(중단만 있는 과목도 여기다).
    - 진행 중 사이클의 열린 라운드가 1이면 first_pass, 2 이상이면 reviewing.
      열린 라운드가 없으면(경합 뒤 비정상 상태) 마지막 라운드로 판정하고 currentRound 는 null 이다.
    - 완료 사이클이면 completed 이고 currentRound 가 null 이다.
    """
    first_round = next((row for row in rounds if row["round_no"] == 1), None)
    if picked is None:
        return SubjectOverviewOut(
            subject_code=subject["code"],
            subject_name=subject["name"],
            unique_question_count=unique_question_count,
            status="not_started",
        )

    if picked["status"] == "completed":
        return SubjectOverviewOut(
            subject_code=subject["code"],
            subject_name=subject["name"],
            unique_question_count=unique_question_count,
            status="completed",
            cycle=HomeCycleOut(
                id=picked["id"],
                status="completed",
                started_at=picked["created_at"],
                ended_at=picked["ended_at"],
                first_round=to_round_summary(first_round),
                current_round=None,
            ),
        )

    current = None
    if open_round is not None:
        current = next((row for row in rounds if row["round_no"] == open_round["round_no"]), None)
    round_no = current["round_no"] if current else max(
        (row["round_no"] for row in rounds), default=1
    )
    return SubjectOverviewOut(
        subject_code=subject["code"],
        subject_name=subject["name"],
        unique_question_count=unique_question_count,
        status="first_pass" if round_no <= 1 else "reviewing",
        cycle=HomeCycleOut(
            id=picked["id"],
            status="active",
            started_at=picked["created_at"],
            ended_at=picked["ended_at"],
            first_round=to_round_summary(first_round),
            current_round=to_round_summary(current),
        ),
    )


@router.get("/overview", response_model=list[SubjectOverviewOut], summary="홈 요약(과목 5개 상태)")
def subject_cycle_overview(conn: Conn):
    """과목 5개의 상태·고유 문항 수·진행 집계를 한 번에 돌려준다(설계 5.1절).

    - `uniqueQuestionCount` 는 요청 시점의 문항을 `content_key()` 로 묶은 그룹 수다
      (과목별 176·194·194·199·181, 1,300행이라 요청마다 계산해도 부담이 없다).
    - `cycle` 은 진행 중 사이클이고, 없으면 마지막 완료 사이클이다(그때 `currentRound` 는 null).
    """
    picks = {row["subject_code"]: row for row in pick_home_cycles(conn)}
    cycle_ids = [row["id"] for row in picks.values()]
    rounds = fetch_rounds(conn, cycle_ids)
    open_rounds = fetch_open_rounds(conn, cycle_ids)
    items: list[SubjectOverviewOut] = []
    for subject in fetch_subjects(conn):
        picked = picks.get(subject["code"])
        picked_id = picked["id"] if picked else None
        items.append(
            _overview_item(
                subject,
                cycle_queries.count_unique_questions(
                    cycle_queries.subject_content_rows(conn, subject["code"])
                ),
                picked,
                rounds.get(picked_id, []),
                open_rounds.get(picked_id),
            )
        )
    return items


@router.get("", response_model=list[CycleOut], summary="사이클 목록")
def list_subject_cycles(
    conn: Conn,
    subject_code: Annotated[int | None, Query(alias="subjectCode", ge=1, le=5)] = None,
    cycle_status: Annotated[CycleStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """과목별 이전 사이클 목록(최근 생성순). `status` 로 active·completed·abandoned 를 가른다."""
    rows = find_cycles(
        conn, subject_code=subject_code, status=cycle_status, limit=limit, offset=offset
    )
    rounds = fetch_rounds(conn, [row["id"] for row in rows])
    return [to_cycle_out(row, rounds.get(row["id"], [])) for row in rows]


@router.get("/{cycle_id}", response_model=CycleOut, summary="사이클 단건(라운드 목록)")
def get_subject_cycle(cycle_id: int, conn: Conn):
    """사이클 상태 + 라운드별 문항 수·답한 수·정답 수·시작·종료 시각."""
    return _cycle_out(conn, cycle_id)
