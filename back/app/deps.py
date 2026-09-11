"""FastAPI 의존성: 커넥션 풀, 선택적 토큰 가드."""
from __future__ import annotations

import logging
import secrets
from typing import Annotated, Iterator

import psycopg
from fastapi import Depends, Header, HTTPException, status
from psycopg_pool import PoolTimeout

from . import db
from .config import Settings, get_settings

logger = logging.getLogger(__name__)


def _unavailable(exc: Exception) -> HTTPException:
    """DB 접속 실패를 /api/health 와 같은 503 으로 맞춘다.

    DB 가 내려가 있으면 요청마다 500 이 나가고 프론트에는 서버 버그로 보이므로,
    접속 실패는 전부 503(서비스 불가)으로 변환한다.
    """
    logger.warning("DB 커넥션을 얻지 못해 503 을 반환합니다: %s", exc)
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DB 에 연결할 수 없습니다",
    )


def get_conn() -> Iterator[psycopg.Connection]:
    pool = db.get_pool()
    if pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB 커넥션 풀이 초기화되지 않았습니다")
    try:
        # 풀 타임아웃(PoolTimeout 은 OperationalError 의 하위 클래스)과 실제 연결
        # 실패(OperationalError)를 모두 잡는다. 풀이 없을 때와 같은 503 이다.
        with pool.connection() as conn:
            yield conn
    except (PoolTimeout, psycopg.OperationalError) as exc:
        raise _unavailable(exc) from exc


Conn = Annotated[psycopg.Connection, Depends(get_conn)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def require_token(
    settings: SettingsDep,
    x_exam_token: Annotated[str | None, Header(alias="X-Exam-Token")] = None,
) -> None:
    """EXAM_API_TOKEN 이 설정된 경우에만 쓰기 요청에 X-Exam-Token 을 요구한다.

    미설정(단일 사용자 개발 기본값)이면 아무것도 검사하지 않는다.
    """
    if not settings.api_token:
        return
    if x_exam_token is None or not secrets.compare_digest(x_exam_token, settings.api_token):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "쓰기 요청에는 유효한 X-Exam-Token 헤더가 필요합니다")
