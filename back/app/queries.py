"""문항 조회 공용 SQL.

정답 번호(answer)·해설(explanation)·보기별 해설(is_correct, why)은 조회 SELECT 에 절대 넣지 않는다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .schemas import FigureOut, QuestionOut, StateOut

if TYPE_CHECKING:
    import psycopg

FIGURE_MOUNT = "/figures"

STATE_COLUMNS = (
    "question_id, attempt_count, correct_count, wrong_count, last_is_correct, last_choice_no, "
    "last_answered_at, streak, bookmarked, note, review_due_on, updated_at"
)


def figure_url(image_path: str | None) -> str | None:
    """DB 의 data/ 기준 상대경로(figures/2026-1/099.png)를 정적 서빙 URL 로 바꾼다."""
    if not image_path:
        return None
    path = image_path.strip().lstrip("/")
    if path.startswith("figures/"):
        path = path[len("figures/"):]
    return f"{FIGURE_MOUNT}/{path}"


QUESTION_SELECT = """
SELECT q.id, q.exam_id, q.number, q.subject_code,
       sj.name AS subject_name,
       q.stem, q.passage, q.passage_kind, q.difficulty,
       q.figure_needed, q.figure_kind, q.figure_image, q.figure_alt,
       coalesce(ch.choices, '[]'::jsonb) AS choices,
       coalesce(tg.tags, ARRAY[]::text[]) AS tags,
       st.state
  FROM ipe.question q
  JOIN ipe.subject sj ON sj.code = q.subject_code
  LEFT JOIN LATERAL (
       SELECT jsonb_agg(jsonb_build_object('no', c.no, 'text', c.text) ORDER BY c.no) AS choices
         FROM ipe.question_choice c
        WHERE c.question_id = q.id
  ) ch ON true
  LEFT JOIN LATERAL (
       SELECT array_agg(t.name ORDER BY t.name) AS tags
         FROM ipe.question_tag qt
         JOIN ipe.tag t ON t.id = qt.tag_id
        WHERE qt.question_id = q.id
  ) tg ON true
  LEFT JOIN LATERAL (
       SELECT to_jsonb(s) AS state
         FROM ipe.study_state s
        WHERE s.question_id = q.id
  ) st ON true
"""


def question_filters(
    *,
    question_id: str | None = None,
    exam_id: str | None = None,
    subject_code: int | None = None,
    difficulty: int | None = None,
    tags: Sequence[str] | None = None,
    figure_only: bool = False,
) -> tuple[str, list[Any]]:
    """WHERE 절과 파라미터를 만든다. 조건이 없으면 'TRUE'."""
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("q.id = %s")
        params.append(question_id)
    if exam_id:
        clauses.append("q.exam_id = %s")
        params.append(exam_id)
    if subject_code is not None:
        clauses.append("q.subject_code = %s")
        params.append(subject_code)
    if difficulty is not None:
        clauses.append("q.difficulty = %s")
        params.append(difficulty)
    if figure_only:
        clauses.append("q.figure_needed")
    tag_names = [t for t in (tags or []) if t]
    if tag_names:
        clauses.append(
            """EXISTS (SELECT 1 FROM ipe.question_tag qt
                        JOIN ipe.tag t ON t.id = qt.tag_id
                       WHERE qt.question_id = q.id AND t.name = ANY(%s))"""
        )
        params.append(tag_names)
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def fetch_questions(
    conn: psycopg.Connection,
    *,
    where: str,
    params: Sequence[Any],
    order_by: str = "q.number",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """ORDER BY 는 코드 안의 상수만 넘긴다(사용자 입력 금지)."""
    sql = f"{QUESTION_SELECT} WHERE {where} ORDER BY {order_by}"
    args: list[Any] = list(params)
    if limit is not None:
        sql += " LIMIT %s OFFSET %s"
        args += [limit, offset]
    return conn.execute(sql, args).fetchall()


def count_questions(conn: psycopg.Connection, where: str, params: Sequence[Any]) -> int:
    row = conn.execute(f"SELECT count(*)::int AS n FROM ipe.question q WHERE {where}", list(params)).fetchone()
    return row["n"]


def to_question(row: dict) -> QuestionOut:
    return QuestionOut(
        id=row["id"],
        exam_id=row["exam_id"],
        number=row["number"],
        subject_code=row["subject_code"],
        subject_name=row["subject_name"],
        stem=row["stem"],
        passage=row["passage"],
        passage_kind=row["passage_kind"],
        difficulty=row["difficulty"],
        choices=row["choices"] or [],
        figure=FigureOut(
            needed=row["figure_needed"],
            kind=row["figure_kind"],
            image_url=figure_url(row["figure_image"]),
            alt=row["figure_alt"],
        ),
        tags=list(row["tags"] or []),
        state=StateOut.model_validate(row["state"]) if row["state"] else None,
    )
