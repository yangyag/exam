"""문항 단건·랜덤 출제·채점."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from .. import grading
from ..deps import Conn, require_token
from ..queries import (
    fetch_content_rows,
    fetch_questions,
    pick_unique_random_ids,
    question_filters,
    to_question,
)
from ..schemas import GradeRequest, GradeResult, QuestionOut

router = APIRouter(prefix="/api", tags=["questions"])


@router.get("/questions/random", response_model=list[QuestionOut], summary="랜덤 출제")
def random_questions(
    conn: Conn,
    exam_id: Annotated[str | None, Query(alias="examId")] = None,
    subject_code: Annotated[int | None, Query(alias="subjectCode", ge=1, le=5)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    figure_only: Annotated[bool, Query(alias="figureOnly")] = False,
    count: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """내용이 같은 문항(회차 간 중복)은 한 그룹으로 묶어 그룹마다 1문항만 돌려준다.

    그룹 대표는 무작위로 고르고, 중복을 제거한 고유 그룹이 count 보다 적으면 있는 만큼만 돌려준다.
    목록·단건 조회는 원본 그대로라 같은 내용의 문항이 모두 나온다.
    """
    where, params = question_filters(
        exam_id=exam_id, subject_code=subject_code, tags=tag, figure_only=figure_only
    )
    rows = fetch_content_rows(conn, where=where, params=params)
    picked_ids = pick_unique_random_ids(rows, count)
    if not picked_ids:
        return []
    by_id = {
        row["id"]: row
        for row in fetch_questions(conn, where="q.id = ANY(%s)", params=[picked_ids])
    }
    return [to_question(by_id[question_id]) for question_id in picked_ids if question_id in by_id]


@router.get("/questions/{question_id}", response_model=QuestionOut, summary="문항 단건")
def get_question(question_id: str, conn: Conn):
    where, params = question_filters(question_id=question_id)
    rows = fetch_questions(conn, where=where, params=params, limit=1)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"문항 {question_id} 를 찾을 수 없습니다")
    return to_question(rows[0])


@router.post(
    "/questions/{question_id}/answer",
    response_model=GradeResult,
    summary="채점",
    dependencies=[Depends(require_token)],
)
def answer_question(question_id: str, payload: GradeRequest, conn: Conn):
    """고른 보기 번호를 받아 정답 여부를 돌려주고 study_attempt/study_state 에 기록한다.

    sessionId 를 주면 그 세션에 귀속시킨다 — 없는 세션이면 404, 이미 종료된 세션이면 409 다.
    세션 행을 FOR UPDATE 로 잠근 채로 검사·기록하므로, 채점이 먼저 시작됐다면 /finish 가
    그 채점이 끝날 때까지 기다렸다가 이 채점까지 포함해 집계한다(B-01).
    슬롯(study_session_item)이 있는 세션은 이 경로로 기록할 수 없다(409) — 슬롯 제출
    `PUT /api/sessions/{sessionId}/items/{seq}/answer` 를 쓴다.
    종료된 세션은 기록을 받지 않으므로(제출 = 점수 확정) 계속 풀려면 새 세션을 만들어야 한다.
    """
    with conn.transaction():
        if payload.session_id is not None:
            session = grading.lock_session(conn, payload.session_id)
            if grading.session_has_slots(conn, payload.session_id):
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "슬롯 세션은 슬롯 제출(PUT /api/sessions/{sessionId}/items/{seq}/answer)로 기록합니다",
                )
            if session["finished_at"] is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "이미 종료된 세션입니다. 계속 풀려면 새 세션을 시작하세요",
                )
        return grading.grade_question(
            conn,
            question_id=question_id,
            choice_no=payload.choice_no,
            session_id=payload.session_id,
            elapsed_ms=payload.elapsed_ms,
        )
