"""문항 조회 공용 SQL.

정답 번호(answer)·해설(explanation)·보기별 해설(is_correct, why)은 조회 SELECT 에 절대 넣지 않는다.
"""
from __future__ import annotations

import random
import re
import unicodedata
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


# 내용이 같은 문항(회차 간 중복)을 묶는 조회. 보기 본문은 번호 순서의 문자열 배열로 모은다.
CONTENT_KEY_SELECT = """
SELECT q.id, q.stem, q.passage, q.passage_kind,
       q.figure_needed, q.figure_kind, q.figure_alt,
       coalesce(ch.choice_texts, ARRAY[]::text[]) AS choice_texts
  FROM ipe.question q
  LEFT JOIN LATERAL (
       SELECT array_agg(c.text ORDER BY c.no) AS choice_texts
         FROM ipe.question_choice c
        WHERE c.question_id = q.id
  ) ch ON true
"""

# 내용 키의 쉼표 규칙 (I-01 보완). 회차별 인쇄 차이로 쉼표만 다르게 실린 같은 문항
# (2023-1-001 과 2023-1-023, 2022-1-052 와 2024-3-058 등)은 계속 한 그룹으로 묶되,
# 코드·표에서 의미 있는 쉼표는 서로 다른 문항을 가르는 정보라 보존한다.
#   - 자연어 문장부호 쉼표(한글에 붙거나 공백이 이웃한 쉼표)는 stem·지문·보기 어디서든 무시한다.
#   - 공백 없이 코드 문자(영문·숫자·밑줄·%·따옴표)에 붙은 쉼표는 코드·수식의 쉼표로 보고
#     남긴다 — print(1,23) 과 print(12,3) 을 다른 문항으로 가른다.
#   - code·table 지문은 쉼표가 문법(인자 구분)·자료라 하나도 지우지 않는다(종류가 신호다).
# 공백·줄바꿈·나머지 기호는 그대로 두어 코드·표의 서식 차이를 다른 문항으로 남긴다 —
# 기호와 공백까지 지우는 정규화(tools/dups.py 의 norm)는 쓰지 않는다.
_CODE_CHARS = r"0-9A-Za-z_%'\""
LOOSE_COMMA = re.compile(rf"(?<![{_CODE_CHARS}])[,，、]|[,，、](?![{_CODE_CHARS}])")
CODE_PASSAGE_KINDS = ("code", "table")
CONTENT_KEY_SEPARATOR = "\x1f"
CHOICE_SEPARATOR = "\x1e"


def key_text(text: str | None) -> str:
    """내용 키에 넣을 자연어 텍스트. NFC 로 맞추고 문장부호 쉼표만 뺀다.

    바로 앞뒤가 공백 없이 코드 문자(영문·숫자·밑줄·%·따옴표)인 쉼표는 코드·수식 기호라
    남긴다. stem·보기·도식 alt 와 text/null 지문에 쓴다(code/table 지문은 code_key_text).
    """
    if not text:
        return ""
    return LOOSE_COMMA.sub("", unicodedata.normalize("NFC", text))


def code_key_text(text: str | None) -> str:
    """내용 키에 넣을 code·table 지문. 쉼표가 문법(인자 구분)·자료라 그대로 둔다(NFC 만)."""
    if not text:
        return ""
    return unicodedata.normalize("NFC", text)


def content_key(row: dict) -> str:
    """같은 문항으로 볼 내용 키. stem·지문(kind 포함)·보기 4개·도식 정보를 모두 반영한다.

    쉼표는 자연어 문장부호일 때만 무시한다(key_text). 회차에 따라 쉼표만 다르게 실린
    자연어 문항(2023-1-001·2023-1-023)을 계속 한 그룹으로 묶기 위해서다. code·table 지문과
    코드·수식에 붙은 쉼표는 서로 다른 문항을 가르는 정보라 보존한다(리뷰 반례
    print(1,23) 과 print(12,3) 같은 코드).

    회차·문항 번호·정답·해설·태그·난이도·그림 파일 경로는 내용이 아니므로 넣지 않는다
    (같은 문항이 다른 회차에 실리면 그림 경로도 회차 디렉터리로 달라진다).
    """
    kind = row["passage_kind"] or ""
    passage = code_key_text(row["passage"]) if kind in CODE_PASSAGE_KINDS else key_text(row["passage"])
    return CONTENT_KEY_SEPARATOR.join(
        [
            key_text(row["stem"]),
            kind,
            passage,
            CHOICE_SEPARATOR.join(key_text(text) for text in row["choice_texts"]),
            "1" if row["figure_needed"] else "0",
            row["figure_kind"] or "",
            key_text(row["figure_alt"]),
        ]
    )


def fetch_content_rows(
    conn: psycopg.Connection, *, where: str, params: Sequence[Any]
) -> list[dict]:
    """중복 판정에 필요한 필드만 골라 온다(문항 전체 컬럼·상태 조인 없음)."""
    return conn.execute(f"{CONTENT_KEY_SELECT} WHERE {where}", list(params)).fetchall()


def pick_unique_random_ids(rows: Sequence[dict], count: int) -> list[str]:
    """내용 키가 같은 문항을 한 그룹으로 묶어 그룹마다 대표 1개를 무작위로 뽑는다.

    그룹 순서와 대표는 모두 무작위이고, 고유 그룹 수가 count 보다 적으면 있는 만큼만 돌려준다.
    """
    groups: dict[str, list[str]] = {}
    for row in rows:
        groups.setdefault(content_key(row), []).append(row["id"])
    picked_keys = random.sample(list(groups), min(count, len(groups)))
    return [random.choice(groups[key]) for key in picked_keys]


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
