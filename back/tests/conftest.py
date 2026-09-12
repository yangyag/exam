"""공용 픽스처.

- 단위 테스트는 DB 없이 돈다: lifespan(커넥션 풀)을 실행하지 않는 TestClient 를
  쓰고, DB 가 필요한 라우터는 `fake_db` 로 가짜 커넥션을 주입한다.
- 실제 DB 에 붙는 테스트는 `test_integration_db.py` 에 모으고 integration 마커를 붙인다.
- 통합 테스트의 접속 대상은 **`TEST_DB_URL`(환경변수 또는 저장소 루트 `.env`)이 우선**이다.
  없으면 지금까지처럼 `EXAM_DB_URL` → `DATABASE_URL` 순서를 그대로 쓴다.
  앱에서 쓰는 DB 로 돌더라도 테스트는 자기 행만 만들고 끝나면 지우며, 이미 진행 중인
  사이클이 있으면 그 사실을 알려 건너뛴다(test_integration_cycles 의 require_free_subject).
- 접속할 수 없는 DB 는 `PGCONNECT_TIMEOUT`(5초) 안에 포기하고 skip 한다. 없으면 localhost 의
  IPv6 주소(::1) 같은 죽은 주소마다 OS 기본 타임아웃(약 2분)을 기다려 통합 35건이 한 시간 넘게 걸린다.
"""
from __future__ import annotations

import os
import re

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings, load_env_file
from app.deps import get_conn
from app.main import create_app

from fake_db import FakeConnection

TEST_DB_ENV = "TEST_DB_URL"
# libpq 의 기본 접속 타임아웃(초). 이 프로세스가 만드는 커넥션(앱 풀 포함)에 모두 적용된다.
CONNECT_TIMEOUT_SECONDS = 5
os.environ.setdefault("PGCONNECT_TIMEOUT", str(CONNECT_TIMEOUT_SECONDS))
# 접속 문자열에서 비밀번호를 가린다(tools/load_db.py 의 redact 와 같은 규칙).
_CREDENTIALS_RE = re.compile(r"://([^:/@]+):[^@]*@")


def redact_db_url(url: str) -> str:
    """보고용 접속 문자열. 비밀번호는 `***` 로 가린다."""
    return _CREDENTIALS_RE.sub(r"://\1:***@", url) if url else "libpq PG* 환경변수"


def prefer_test_database() -> str | None:
    """TEST_DB_URL 이 있으면 통합 테스트의 접속 대상을 그 DB 로 바꾼다.

    - 환경변수 `TEST_DB_URL` 이 저장소 루트 `.env` 의 값보다 우선한다.
    - 앱 코드(app/config.py)는 EXAM_DB_URL/DATABASE_URL 만 보므로 운영 동작은 건드리지 않는다.
      테스트 프로세스에서 EXAM_DB_URL 을 TEST_DB_URL 값으로 승격해 접속 대상만 바꾼다.
    - TEST_DB_URL 이 없으면 아무것도 하지 않는다(기존: EXAM_DB_URL → DATABASE_URL).
    """
    load_env_file()  # .env 의 값을 환경변수로 올린다(이미 설정된 변수는 유지)
    test_url = os.environ.get(TEST_DB_ENV)
    if not test_url:
        return None
    os.environ["EXAM_DB_URL"] = test_url
    return test_url


TEST_DB_URL_USED = prefer_test_database()
# 위 승격 전에 app.main import 가 만들어 둔 설정 캐시를 비운다(첫 get_settings 부터 반영).
get_settings.cache_clear()


def pytest_report_header(config) -> str:
    """통합 테스트가 어느 DB 에 붙는지 먼저 알려준다(비밀번호는 가림)."""
    settings = get_settings()
    source = TEST_DB_ENV if TEST_DB_URL_USED else settings.db_url_source
    return f"통합 테스트 DB: {redact_db_url(settings.db_url)} (출처: {source})"


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    """get_settings 는 lru_cache 라 테스트 사이에 캐시를 비워 환경변수 변경이 반영되게 한다."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def api_app():
    """단위 테스트용 앱. lifespan 을 실행하지 않으므로 DB 접속이 일어나지 않는다."""
    return create_app()


@pytest.fixture()
def client(api_app):
    """lifespan 없이 요청만 보내는 TestClient(DB 없음)."""
    return TestClient(api_app)


@pytest.fixture()
def fake_db(api_app):
    """가짜 커넥션을 get_conn 의존성에 끼워 넣는다.

    사용법: `fake = fake_db({...규칙...})` → 반환된 FakeConnection 으로 실행된 SQL 을 검사한다.
    """

    def install(rules=None) -> FakeConnection:
        fake = FakeConnection(rules)
        api_app.dependency_overrides[get_conn] = lambda: fake
        return fake

    yield install
    api_app.dependency_overrides.clear()
