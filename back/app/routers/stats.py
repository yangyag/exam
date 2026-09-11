"""통계 3종 뷰 조회. 정답 번호는 조회 응답에 넣지 않는다."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..deps import Conn
from ..schemas import ReviewDueOut, SubjectStatsOut, WrongQuestionOut

router = APIRouter(prefix="/api", tags=["stats"])

SUBJECT_STATS_SQL = """
SELECT subject_code, subject_name, answered, correct, wrong,
       questions_total, questions_seen, accuracy_pct
  FROM ipe.v_subject_stats
 ORDER BY subject_code
"""

WRONG_QUESTIONS_SQL = """
SELECT question_id, exam_id, number, subject_code, subject_name, stem,
       attempt_count, wrong_count, last_choice_no, last_is_correct,
       last_answered_at, bookmarked, note, review_due_on
  FROM ipe.v_wrong_questions
 {where}
 ORDER BY last_answered_at DESC NULLS LAST, question_id
 LIMIT %s OFFSET %s
"""

# '오늘' 판정과 overdue_days 계산은 뷰(ipe.v_review_due)가 Asia/Seoul 날짜 기준으로 한다.
REVIEW_DUE_SQL = """
SELECT question_id, exam_id, number, subject_code, subject_name, stem,
       review_due_on, overdue_days, last_is_correct, wrong_count, note
  FROM ipe.v_review_due
 ORDER BY review_due_on, question_id
 LIMIT %s OFFSET %s
"""


@router.get("/stats/subjects", response_model=list[SubjectStatsOut], summary="과목별 정답률")
def subject_stats(conn: Conn):
    """응답 기록이 없는 과목도 행이 나오고 accuracyPct 는 null."""
    return conn.execute(SUBJECT_STATS_SQL).fetchall()


@router.get("/stats/wrong-questions", response_model=list[WrongQuestionOut], summary="오답 문항")
def wrong_questions(
    conn: Conn,
    unresolved_only: Annotated[bool, Query(alias="unresolvedOnly")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    where = "WHERE NOT last_is_correct" if unresolved_only else ""
    sql = WRONG_QUESTIONS_SQL.format(where=where)
    return conn.execute(sql, (limit, offset)).fetchall()


@router.get("/stats/review-due", response_model=list[ReviewDueOut], summary="복습 예정 문항")
def review_due(
    conn: Conn,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    """복습 예정일이 오늘(Asia/Seoul 날짜) 이하인 문항. overdueDays 0 이면 오늘."""
    return conn.execute(REVIEW_DUE_SQL, (limit, offset)).fetchall()
