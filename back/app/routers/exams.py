"""회차·과목 조회와 회차별 문항 목록."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..deps import Conn
from ..queries import count_questions, fetch_questions, question_filters, to_question
from ..schemas import ExamDetail, ExamOut, QuestionPage, SubjectOut

router = APIRouter(prefix="/api", tags=["exams"])

SUBJECT_LIST_SQL = """
SELECT s.code, s.name, s.from_no, s.to_no, count(q.id)::int AS question_count
  FROM ipe.subject s
  LEFT JOIN ipe.question q ON q.subject_code = s.code
 GROUP BY s.code, s.name, s.from_no, s.to_no
 ORDER BY s.code
"""

EXAM_LIST_SQL = """
SELECT e.id, e.year, e.round, e.title,
       count(q.id)::int AS question_count,
       count(q.id) FILTER (WHERE q.figure_needed)::int AS figure_count
  FROM ipe.exam e
  LEFT JOIN ipe.question q ON q.exam_id = e.id
 GROUP BY e.id, e.year, e.round, e.title
 ORDER BY e.year DESC, e.round DESC
"""

EXAM_DETAIL_SQL = """
SELECT e.id, e.year, e.round, e.title, e.source_pdf,
       count(q.id)::int AS question_count,
       count(q.id) FILTER (WHERE q.figure_needed)::int AS figure_count
  FROM ipe.exam e
  LEFT JOIN ipe.question q ON q.exam_id = e.id
 WHERE e.id = %s
 GROUP BY e.id, e.year, e.round, e.title, e.source_pdf
"""

EXAM_SUBJECT_SQL = """
SELECT s.code, s.name, s.from_no, s.to_no, count(q.id)::int AS question_count
  FROM ipe.subject s
  JOIN ipe.question q ON q.subject_code = s.code AND q.exam_id = %s
 GROUP BY s.code, s.name, s.from_no, s.to_no
 ORDER BY s.code
"""


def _ensure_exam(conn: Conn, exam_id: str) -> None:
    if not conn.execute("SELECT 1 FROM ipe.exam WHERE id = %s", (exam_id,)).fetchone():
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"회차 {exam_id} 를 찾을 수 없습니다")


@router.get("/subjects", response_model=list[SubjectOut], summary="과목 목록")
def list_subjects(conn: Conn):
    return conn.execute(SUBJECT_LIST_SQL).fetchall()


@router.get("/exams", response_model=list[ExamOut], summary="회차 목록")
def list_exams(conn: Conn):
    return conn.execute(EXAM_LIST_SQL).fetchall()


@router.get("/exams/{exam_id}", response_model=ExamDetail, summary="회차 상세")
def get_exam(exam_id: str, conn: Conn):
    row = conn.execute(EXAM_DETAIL_SQL, (exam_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"회차 {exam_id} 를 찾을 수 없습니다")
    row["subjects"] = conn.execute(EXAM_SUBJECT_SQL, (exam_id,)).fetchall()
    return row


@router.get("/exams/{exam_id}/questions", response_model=QuestionPage, summary="회차 문항 목록(과목 필터)")
def list_exam_questions(
    exam_id: str,
    conn: Conn,
    subject_code: Annotated[int | None, Query(alias="subjectCode", ge=1, le=5)] = None,
    difficulty: Annotated[int | None, Query(ge=1, le=5)] = None,
    tag: Annotated[list[str] | None, Query()] = None,
    figure_only: Annotated[bool, Query(alias="figureOnly")] = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    _ensure_exam(conn, exam_id)
    where, params = question_filters(
        exam_id=exam_id,
        subject_code=subject_code,
        difficulty=difficulty,
        tags=tag,
        figure_only=figure_only,
    )
    rows = fetch_questions(conn, where=where, params=params, limit=limit, offset=offset)
    return {
        "items": [to_question(r) for r in rows],
        "total": count_questions(conn, where, params),
        "limit": limit,
        "offset": offset,
    }
