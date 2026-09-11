"""psycopg3 커넥션 풀.

`yangyag` 역할의 search_path 는 english,public 이므로 세션 search_path 를 ipe,public 으로 고정한다.
읽기는 autocommit 으로 바로 돌려보내고, 여러 문장을 묶어야 하는 쓰기는 conn.transaction() 을 쓴다.
"""
from __future__ import annotations

import logging
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

logger = logging.getLogger(__name__)

SEARCH_PATH = "ipe,public"
POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 10

_pool: ConnectionPool | None = None


def _connect_kwargs() -> dict[str, Any]:
    return {
        "autocommit": True,
        "row_factory": dict_row,
        "options": f"-c search_path={SEARCH_PATH}",
    }


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        logger.info("DB 풀 생성 (출처: %s, search_path=%s)", settings.db_url_source, SEARCH_PATH)
        _pool = ConnectionPool(
            conninfo=settings.db_url,
            min_size=POOL_MIN_SIZE,
            max_size=POOL_MAX_SIZE,
            open=False,
            kwargs=_connect_kwargs(),
        )
        _pool.open()
    return _pool


def get_pool() -> ConnectionPool | None:
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def ping(timeout: float = 2.0) -> bool:
    """헬스체크용. 풀이 없거나 timeout 안에 연결하지 못하면 False."""
    pool = _pool
    if pool is None:
        return False
    try:
        with pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        logger.warning("DB 헬스체크 실패", exc_info=True)
        return False
