"""공용 픽스처.

- 단위 테스트는 DB 없이 돈다: lifespan(커넥션 풀)을 실행하지 않는 TestClient 를
  쓰고, DB 가 필요한 라우터는 `fake_db` 로 가짜 커넥션을 주입한다.
- 실제 DB 에 붙는 테스트는 `test_integration_db.py` 에 모으고 integration 마커를 붙인다.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.deps import get_conn
from app.main import create_app

from fake_db import FakeConnection


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
