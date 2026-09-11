"""DB 접속 불가 시 503 을 반환하는지 고정하는 테스트.

수정 전에는 데이터 엔드포인트가 커넥션 풀 기본 타임아웃(30초)을 기다린 뒤 처리되지 않은
`psycopg_pool.PoolTimeout` 으로 500(`Internal Server Error`)을 돌려줬다. 이제는 커넥션 풀이
아직 없을 때와 똑같이 503 이면서 `db.POOL_TIMEOUT`(2초) 안에 끝나야 한다 — `/api/health` 와
같은 상태 코드라서 프론트가 DB 장애와 서버 버그를 구분할 수 있다.
"""
from __future__ import annotations

import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg_pool import PoolTimeout

from app import db
from app.config import get_settings
from app.main import create_app

# 1번 포트에는 아무것도 듣지 않으므로 접속이 즉시 거절된다(실제 DB 는 건드리지 않는다).
UNREACHABLE_DSN = "postgresql://nobody@127.0.0.1:1/nowhere"
# 풀 타임아웃 2초에 여유를 둔 상한. 30초짜리 회귀가 돌아오면 여기서 걸린다.
MAX_RESPONSE_SECONDS = 5.0
UNAVAILABLE_DETAIL = "DB 에 연결할 수 없습니다"


class FailingPool:
    """`connection()` 이 항상 주어진 예외를 내는 가짜 풀."""

    def __init__(self, exc: Exception):
        self.exc = exc

    def connection(self, timeout: float | None = None):
        raise self.exc


@pytest.fixture()
def unreachable_pool(monkeypatch):
    """접속할 수 없는 주소를 가리키는 진짜 커넥션 풀을 열어 둔다.

    `EXAM_DB_URL` 이 저장소 루트 `.env` 보다 우선하므로 실제 DB 접속 정보가 있어도 안전하다.
    끝나면 풀을 닫아 다음 테스트로 새지 않게 한다.
    """
    monkeypatch.setenv("EXAM_DB_URL", UNREACHABLE_DSN)
    get_settings.cache_clear()
    db.close_pool()
    pool = db.open_pool()
    try:
        yield pool
    finally:
        db.close_pool()


@pytest.mark.parametrize(
    "exc",
    [
        PoolTimeout("couldn't get a connection after 2.00 sec"),
        psycopg.OperationalError("connection to server failed: no password supplied"),
    ],
    ids=["pool-timeout", "operational-error"],
)
def test_data_endpoint_returns_503_when_pool_fails(client, monkeypatch, exc):
    """풀이 예외를 내면 조회 엔드포인트는 500 이 아니라 503 을 돌려준다."""
    monkeypatch.setattr(db, "get_pool", lambda: FailingPool(exc))
    response = client.get("/api/exams")
    assert response.status_code == 503
    assert response.json()["detail"] == UNAVAILABLE_DETAIL


def test_write_endpoint_returns_503_when_pool_fails(client, monkeypatch):
    """쓰기 엔드포인트도 같은 503 규약을 따른다."""
    monkeypatch.setattr(db, "get_pool", lambda: FailingPool(psycopg.OperationalError("connection failed")))
    response = client.post("/api/sessions", json={"mode": "random"})
    assert response.status_code == 503
    assert response.json()["detail"] == UNAVAILABLE_DETAIL


def test_data_endpoint_returns_503_when_pool_not_initialized(client, monkeypatch):
    """풀이 아직 만들어지지 않았을 때도 503 이다(기존 동작 고정)."""
    monkeypatch.setattr(db, "get_pool", lambda: None)
    response = client.get("/api/exams")
    assert response.status_code == 503
    assert response.json()["detail"] == "DB 커넥션 풀이 초기화되지 않았습니다"


def test_health_returns_503_when_pool_fails(client, monkeypatch):
    """헬스체크도 같은 503 이라 두 종류 엔드포인트의 상태 코드가 어긋나지 않는다."""
    monkeypatch.setattr(db, "_pool", FailingPool(PoolTimeout("couldn't get a connection")))
    response = client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"


def test_unreachable_db_returns_503_within_pool_timeout(unreachable_pool):
    """진짜 풀 + 진짜 lifespan 으로: 접속 불가 DB 에서 2초대 503 이 나온다.

    수정 전에는 이 요청이 30초를 기다린 뒤 500 이었다.
    """
    assert unreachable_pool.timeout == db.POOL_TIMEOUT
    app = create_app()
    with TestClient(app) as client:  # lifespan 이 db.open_pool() 을 부르지만 이미 열린 풀을 그대로 쓴다
        started = time.monotonic()
        response = client.get("/api/exams")
        elapsed = time.monotonic() - started
    assert response.status_code == 503
    assert response.json()["detail"] == UNAVAILABLE_DETAIL
    assert elapsed < MAX_RESPONSE_SECONDS, f"{elapsed:.2f}초 걸렸다 — 수정 전 30초짜리 회귀"
