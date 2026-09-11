"""과목 사이클 조회·집계 SQL(설계 4.2·5.1~5.2절).

- 문항 목록과 중복 판정은 문항 조회 공용 모듈(`queries.py`)을 그대로 쓴다 —
  `fetch_content_rows`·`content_key` 가 정본이고 여기서 컬럼 목록을 다시 적지 않는다.
- 사이클·라운드 조회는 **진행 중(active) 사이클을 근거로 삼는다**. `cycles.replace_active_cycle`
  의 경합 계약(설계 4.6절)에 따라 'abandoned 사이클 = 열린 라운드 없음' 을 가정하지 않는다.
- 정답·해설 컬럼은 조회하지 않는다. 라운드 집계는 슬롯의 `is_correct` **개수**만 본다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

from .cycle_schemas import CycleOut, RoundOut, RoundSummaryOut
from .queries import content_key, fetch_content_rows, question_filters

if TYPE_CHECKING:
    import psycopg

SUBJECTS_SELECT = "SELECT code, name FROM ipe.subject ORDER BY code"
SUBJECT_SELECT = "SELECT code, name FROM ipe.subject WHERE code = %s"

CYCLE_COLUMNS = "c.id, c.subject_code, sj.name AS subject_name, c.status, c.created_at, c.ended_at"
CYCLE_SELECT = f"""
SELECT {CYCLE_COLUMNS}
  FROM ipe.study_cycle c
  JOIN ipe.subject sj ON sj.code = c.subject_code
"""
CYCLE_INSERT_SQL = "INSERT INTO ipe.study_cycle (subject_code) VALUES (%s) RETURNING id"

# 라운드 = 사이클의 세션 1개. answered·correct 는 슬롯 기준(원장 아님)이라 진행 중에도 바로 나온다.
# correct 는 count(i.is_correct) 가 아니라 FILTER 다 — count(boolean) 은 false 도 세어 버린다.
ROUND_SELECT = """
SELECT s.cycle_id, s.id AS session_id, s.round_no, s.mode, s.started_at, s.finished_at, s.end_reason,
       count(i.*)::int                            AS item_count,
       count(i.choice_no)::int                    AS answered,
       (count(*) FILTER (WHERE i.is_correct))::int AS correct
  FROM ipe.study_session s
  LEFT JOIN ipe.study_session_item i ON i.session_id = s.id
 WHERE s.cycle_id = ANY(%s)
 GROUP BY s.cycle_id, s.id, s.round_no, s.mode, s.started_at, s.finished_at, s.end_reason
 ORDER BY s.cycle_id, s.round_no, s.id
"""

# 홈 요약: 과목마다 진행 중 사이클 하나, 없으면 마지막 완료 사이클 하나(DISTINCT ON 으로 1행).
# 중단(abandoned) 사이클은 상태 판정에 쓰지 않는다 — 홈의 not_started 조건이 '진행 중도 완료도 없음' 이다.
HOME_CYCLE_PICK_SQL = """
SELECT DISTINCT ON (c.subject_code)
       c.id, c.subject_code, c.status, c.created_at, c.ended_at
  FROM ipe.study_cycle c
 WHERE c.status IN ('active', 'completed')
 ORDER BY c.subject_code, (c.status = 'active') DESC, c.ended_at DESC NULLS LAST, c.id DESC
"""

# 홈 요약에서 쓰는 열린 라운드. 사이클당 1개지만, 경합으로 중단된 사이클에 남을 수 있다(4.6절 계약).
OPEN_ROUND_SELECT = """
SELECT cycle_id, id AS session_id, round_no
  FROM ipe.study_session
 WHERE cycle_id = ANY(%s) AND finished_at IS NULL
"""


def subject_content_rows(conn: psycopg.Connection, subject_code: int) -> list[dict]:
    """중복 판정에 필요한 과목 문항 행(260개). SELECT 컬럼은 공용 모듈이 정한다."""
    where, params = question_filters(subject_code=subject_code)
    return fetch_content_rows(conn, where=where, params=params)


def unique_question_ids(rows: Sequence[dict]) -> list[str]:
    """내용이 같은 문항을 한 그룹으로 묶고 그룹 대표를 고른다(설계 4.5절).

    대표는 **가장 최근 회차 = id 최대** 다. id 는 `연도-회차-번호` 라 문자열 비교가 회차 순서와 같다.
    그룹 순서는 처음 만난 순서(결정적)이고, 무작위 셔플은 세션을 만들 때 `create_round_session` 이 한다.
    """
    representative: dict[str, str] = {}
    for row in rows:
        key = content_key(row)
        best = representative.get(key)
        if best is None or row["id"] > best:
            representative[key] = row["id"]
    return list(representative.values())


def count_unique_questions(rows: Sequence[dict]) -> int:
    """content_key 기준 고유 그룹 수(홈 요약의 uniqueQuestionCount)."""
    return len({content_key(row) for row in rows})


def fetch_subjects(conn: psycopg.Connection) -> list[dict]:
    return conn.execute(SUBJECTS_SELECT).fetchall()


def fetch_subject(conn: psycopg.Connection, subject_code: int) -> dict | None:
    return conn.execute(SUBJECT_SELECT, (subject_code,)).fetchone()


def insert_cycle(conn: psycopg.Connection, subject_code: int) -> dict:
    """사이클 1행(active). 호출자가 트랜잭션을 열고 `replace_active_cycle` 뒤에 부른다."""
    return conn.execute(CYCLE_INSERT_SQL, (subject_code,)).fetchone()


def fetch_cycle(conn: psycopg.Connection, cycle_id: int) -> dict | None:
    return conn.execute(f"{CYCLE_SELECT} WHERE c.id = %s", (cycle_id,)).fetchone()


def find_cycles(
    conn: psycopg.Connection,
    *,
    subject_code: int | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """목록 조회(최근 생성순). 조건이 없으면 전체다."""
    clauses: list[str] = []
    params: list[Any] = []
    if subject_code is not None:
        clauses.append("c.subject_code = %s")
        params.append(subject_code)
    if status is not None:
        clauses.append("c.status = %s")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"{CYCLE_SELECT}{where} ORDER BY c.created_at DESC, c.id DESC LIMIT %s OFFSET %s"
    return conn.execute(sql, [*params, limit, offset]).fetchall()


def fetch_rounds(conn: psycopg.Connection, cycle_ids: Sequence[int]) -> dict[int, list[dict]]:
    """사이클 id → 라운드 행 목록(round_no 순). 여러 사이클을 한 번에 조회한다."""
    if not cycle_ids:
        return {}
    grouped: dict[int, list[dict]] = {}
    for row in conn.execute(ROUND_SELECT, (list(cycle_ids),)).fetchall():
        grouped.setdefault(row["cycle_id"], []).append(row)
    return grouped


def pick_home_cycles(conn: psycopg.Connection) -> list[dict]:
    """과목별로 진행 중 사이클 또는 마지막 완료 사이클 1행(홈 요약용)."""
    return conn.execute(HOME_CYCLE_PICK_SQL).fetchall()


def fetch_open_rounds(conn: psycopg.Connection, cycle_ids: Sequence[int]) -> dict[int, dict]:
    """사이클 id → 열린 라운드(진행 중 세션) 1행. 없으면 키가 없다."""
    if not cycle_ids:
        return {}
    return {row["cycle_id"]: row for row in conn.execute(OPEN_ROUND_SELECT, (list(cycle_ids),)).fetchall()}


def to_round_out(row: dict) -> RoundOut:
    return RoundOut(
        session_id=row["session_id"],
        round_no=row["round_no"],
        mode=row["mode"],
        item_count=row["item_count"],
        answered=row["answered"],
        correct=row["correct"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        end_reason=row["end_reason"],
    )


def to_round_summary(row: dict | None) -> RoundSummaryOut | None:
    """라운드 집계 행을 홈 요약용으로 줄인다. 없으면 null."""
    if row is None:
        return None
    return RoundSummaryOut(
        session_id=row["session_id"],
        round_no=row["round_no"],
        item_count=row["item_count"],
        answered=row["answered"],
        correct=row["correct"],
    )


def to_cycle_out(cycle: dict, rounds: Sequence[dict]) -> CycleOut:
    return CycleOut(
        id=cycle["id"],
        subject_code=cycle["subject_code"],
        subject_name=cycle["subject_name"],
        status=cycle["status"],
        started_at=cycle["created_at"],
        ended_at=cycle["ended_at"],
        rounds=[to_round_out(row) for row in rounds],
    )
