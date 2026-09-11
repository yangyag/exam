"""FastAPI 의존성: 커넥션 풀, 선택적 토큰 가드."""
from __future__ import annotations

import secrets
from typing import Annotated, Iterator

import psycopg
from fastapi import Depends, Header, HTTPException, status

from . import db
from .config import Settings, get_settings


def get_conn() -> Iterator[psycopg.Connection]:
    pool = db.get_pool()
    if pool is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "DB 커넥션 풀이 초기화되지 않았습니다")
    with pool.connection() as conn:
        yield conn


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
