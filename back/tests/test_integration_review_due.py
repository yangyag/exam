"""복습 '오늘'이 한국 날짜(Asia/Seoul) 기준인지 실제 PostgreSQL 로 고정하는 통합 테스트.

기존 테스트 파일을 import 하지 않는다 — 자체 접속·정리 로직을 둔다.
- 이 모듈이 만든 `ipe.study_state` 행은 테스트 전 상태로 되돌린다(모듈 종료 시 검증).
- 접속할 수 없으면 실패가 아니라 skip 한다.

KST 자정~09시 경계를 실시간으로 기다릴 수 없으므로 다음으로 고정한다.
1. 세션 TimeZone 을 'KST 와 다른 날짜가 되는' 시간대로 바꿔 뷰를 조회한다. 기존 구현
   (`current_date`)은 이 조건에서 오늘 문항을 빠뜨리고 지연 일수를 1일 작게 센다.
2. 기대값은 모두 SQL `(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date` 로 계산해 비교한다.
3. `pg_get_viewdef` 에 Asia/Seoul 이 들어 있는지도 확인해 정의가 되돌아가는 것을 막는다.
"""
from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.rows import dict_row

from app import db as app_db
from app.config import get_settings
from app.main import app as fastapi_app

pytestmark = pytest.mark.integration

# study_state 전체 컬럼. 원래 행을 그대로 되돌리려면 전부 필요하다.
STATE_COLUMNS = (
    "question_id",
    "attempt_count",
    "correct_count",
    "wrong_count",
    "last_is_correct",
    "last_choice_no",
    "last_answered_at",
    "streak",
    "bookmarked",
    "note",
    "review_due_on",
    "updated_at",
)
STATE_RESTORE_SQL = (
    f"INSERT INTO ipe.study_state ({', '.join(STATE_COLUMNS)}) "
    f"VALUES ({', '.join(['%s'] * len(STATE_COLUMNS))})"
)
# KST 와 다른 날짜가 되도록 만드는 후보 시간대. 둘은 26시간(named offset 특성) 차이라
# 어느 순간에도 둘 중 하나는 KST 날짜와 다른 날짜가 된다 — 기존 구현이면 그 조건에서 틀린다.
FOREIGN_TIMEZONES = ("Etc/GMT+12", "Pacific/Kiritimati")


def kst_date(conn: psycopg.Connection, offset_days: int = 0) -> dt.date:
    """한국 날짜. 기대값은 항상 SQL AT TIME ZONE 으로 계산한다."""
    return conn.execute(
        "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date + %s AS d", (offset_days,)
    ).fetchone()["d"]


class StateRestorer:
    """테스트가 만든 study_state 행을 추적해 테스트 전 상태로 복원한다."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn
        # 문항별 테스트 전 행(None 이면 원래 없던 문항) — 만든 순서를 유지한다.
        self.states: dict[str, dict | None] = {}

    def set_due(self, question_id: str, due_on: dt.date) -> None:
        """복습 예정일만 채운 최소 행을 넣는다. 넣기 전 상태를 기억한다."""
        if question_id not in self.states:
            self.states[question_id] = self.conn.execute(
                "SELECT * FROM ipe.study_state WHERE question_id = %s", (question_id,)
            ).fetchone()
        self.conn.execute(
            "INSERT INTO ipe.study_state (question_id, review_due_on) VALUES (%s, %s)",
            (question_id, due_on),
        )

    def cleanup(self) -> None:
        for question_id, before in self.states.items():
            self.conn.execute("DELETE FROM ipe.study_state WHERE question_id = %s", (question_id,))
            if before is not None:
                self.conn.execute(
                    STATE_RESTORE_SQL, tuple(before[column] for column in STATE_COLUMNS)
                )

    def verify_restored(self) -> None:
        """만든 행이 남지 않았고, 기존 행은 그대로인지 확인한다."""
        for question_id, before in self.states.items():
            now = self.conn.execute(
                "SELECT * FROM ipe.study_state WHERE question_id = %s", (question_id,)
            ).fetchone()
            assert now == before, f"{question_id} 의 study_state 가 복원되지 않았다: {before} → {now}"


def pick_question_ids(conn: psycopg.Connection, count: int, exclude: set[str] | None = None) -> list[str]:
    """아직 study_state 가 없는 문항을 뒤에서부터 고른다.

    다른 에이전트/테스트가 앞에서부터 고를 수 있으므로 id 내림차순으로 겹침을 줄인다.
    상태가 있는 문항을 쓰게 되더라도 StateRestorer 가 원상 복구한다.
    """
    exclude = list(exclude or ())
    rows = conn.execute(
        """SELECT q.id
             FROM ipe.question q
            WHERE NOT EXISTS (SELECT 1 FROM ipe.study_state s WHERE s.question_id = q.id)
              AND NOT (q.id = ANY(%s))
            ORDER BY q.id DESC
            LIMIT %s""",
        (exclude, count),
    ).fetchall()
    if len(rows) < count:
        rows = conn.execute(
            "SELECT id FROM ipe.question WHERE NOT (id = ANY(%s)) ORDER BY id DESC LIMIT %s",
            (exclude, count),
        ).fetchall()
    ids = [row["id"] for row in rows]
    assert len(ids) == count, f"테스트용 문항 {count}개를 고르지 못했다: {ids}"
    return ids


@pytest.fixture(scope="module")
def db_conn():
    """백엔드와 같은 조건의 직접 커넥션. 접속할 수 없으면 통합 테스트를 건너뛴다."""
    settings = get_settings()
    try:
        conn = psycopg.connect(
            settings.db_url,
            autocommit=True,
            row_factory=dict_row,
            options=f"-c search_path={app_db.SEARCH_PATH}",
        )
        conn.execute("SELECT 1")
    except psycopg.Error as exc:
        pytest.skip(f"ipe DB 에 접속할 수 없어 건너뛴다 ({exc.__class__.__name__}): {exc}")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def restorer(db_conn):
    """study_state 추적기. 모듈의 모든 테스트가 끝나면 정리하고 복원을 검증한다."""
    tracker = StateRestorer(db_conn)
    yield tracker
    tracker.cleanup()
    tracker.verify_restored()


@pytest.fixture()
def live_client(db_conn):
    """lifespan(=DB 커넥션 풀)을 실제로 돌리는 TestClient. db_conn 이 접속을 확인한 뒤에만 쓰인다."""
    with TestClient(fastapi_app) as client:
        yield client


def test_view_definition_pins_asia_seoul(db_conn):
    """뷰 정의가 Asia/Seoul 을 명시하고 세션 기준 CURRENT_DATE 를 쓰지 않는다."""
    definition = db_conn.execute(
        "SELECT pg_get_viewdef('ipe.v_review_due'::regclass, true) AS definition"
    ).fetchone()["definition"]
    assert "Asia/Seoul" in definition, f"v_review_due 가 Asia/Seoul 기준을 쓰지 않는다:\n{definition}"
    assert "CURRENT_DATE" not in definition, (
        f"v_review_due 가 세션 TimeZone 을 따르는 CURRENT_DATE 를 쓴다:\n{definition}"
    )


def test_review_due_follows_kst_under_foreign_session_timezone(db_conn, restorer):
    """세션 TimeZone 이 KST 와 다른 날짜여도 뷰가 KST 날짜로 판정·계산하는지 본다.

    기존 `current_date` 구현이면 이 세션에서 오늘 문항이 빠지고 어제 문항의 지연 일수가
    0 으로 나온다(KST 자정~09시 현상의 결정적 재현).
    """
    # KST 날짜와 다른 날짜가 되는 세션 시간대를 찾는다(둘 중 하나는 항상 성립).
    zone = session_date = None
    for candidate in FOREIGN_TIMEZONES:
        db_conn.execute(sql.SQL("SET TIME ZONE {}").format(sql.Literal(candidate)))
        row = db_conn.execute(
            "SELECT current_date AS session_date, (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date AS kst"
        ).fetchone()
        if row["session_date"] != row["kst"]:
            zone, session_date = candidate, row["session_date"]
            break
    assert zone is not None, "KST 와 다른 날짜가 되는 세션 TimeZone 을 찾지 못했다"

    try:
        kst = kst_date(db_conn)
        assert session_date != kst, "세션 날짜와 KST 날짜가 같으면 기존 버그를 재현할 수 없다"

        due_today, due_yesterday = pick_question_ids(db_conn, 2, exclude=set(restorer.states))
        restorer.set_due(due_today, kst)
        restorer.set_due(due_yesterday, kst - dt.timedelta(days=1))

        rows = {
            row["question_id"]: row
            for row in db_conn.execute(
                """SELECT question_id, review_due_on, overdue_days
                     FROM ipe.v_review_due
                    WHERE question_id = ANY(%s)""",
                ([due_today, due_yesterday],),
            ).fetchall()
        }
        # 세션 날짜가 KST 보다 하루 뒤처져도 KST 기준으로 판정한다.
        assert due_today in rows, f"KST 오늘 문항이 복습 목록에서 빠졌다 (세션 TZ {zone})"
        assert rows[due_today]["overdue_days"] == 0
        assert rows[due_today]["review_due_on"] == kst
        assert due_yesterday in rows
        assert rows[due_yesterday]["overdue_days"] == 1, (
            f"KST 어제 문항의 지연 일수가 KST 기준이 아니다 (세션 TZ {zone})"
        )

        # 기대값을 SQL AT TIME ZONE 식으로 다시 계산해 비교한다.
        for due_on, expected in ((kst, 0), (kst - dt.timedelta(days=1), 1)):
            computed = db_conn.execute(
                "SELECT (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Seoul')::date - %s::date AS overdue",
                (due_on,),
            ).fetchone()["overdue"]
            assert computed == expected
    finally:
        db_conn.execute("RESET TIME ZONE")


def test_stats_review_due_api_uses_kst_date(db_conn, restorer, live_client):
    """`/api/stats/review-due` 의 대상·overdueDays 가 KST 오늘/어제 기준인지 본다."""
    kst = kst_date(db_conn)
    due_today, due_yesterday, due_future = pick_question_ids(
        db_conn, 3, exclude=set(restorer.states)
    )
    restorer.set_due(due_today, kst)
    restorer.set_due(due_yesterday, kst - dt.timedelta(days=1))
    restorer.set_due(due_future, kst + dt.timedelta(days=1))

    response = live_client.get("/api/stats/review-due", params={"limit": 200})
    assert response.status_code == 200, response.text
    items = {item["questionId"]: item for item in response.json()}

    assert due_today in items, "복습 예정일이 KST 오늘인 문항이 목록에 없다"
    assert items[due_today]["overdueDays"] == 0
    assert items[due_today]["reviewDueOn"] == kst.isoformat()

    assert due_yesterday in items, "복습 예정일이 KST 어제인 문항이 목록에 없다"
    assert items[due_yesterday]["overdueDays"] == 1
    assert items[due_yesterday]["reviewDueOn"] == (kst - dt.timedelta(days=1)).isoformat()

    assert due_future not in items, "아직 오지 않은 복습 예정일이 목록에 나왔다"
