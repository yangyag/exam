"""FastAPI 앱 조립.

실행(개발):
    cd back
    .venv/Scripts/python -m uvicorn app.main:app --port 8092 --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .config import get_settings
from .routers import exams, progress, questions, stats, tags

logger = logging.getLogger(__name__)

DESCRIPTION = """
정보처리기사 필기 기출문제 조회·채점·진도 API.

- 데이터: PostgreSQL `app` DB 의 `ipe` 스키마 (문항 1,300 / 보기 5,200)
- 조회 응답에는 정답 번호·해설·보기별 해설이 들어가지 않습니다. 채점(`POST /api/questions/{id}/answer`)에서만 돌려줍니다.
- `EXAM_API_TOKEN` 환경변수를 설정하면 쓰기 엔드포인트가 `X-Exam-Token` 헤더를 요구합니다(미설정이면 인증 없음).
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.open_pool()
    try:
        yield
    finally:
        db.close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="정보처리기사 필기 문제 API",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(exams.router)
    app.include_router(questions.router)
    app.include_router(progress.router)
    app.include_router(stats.router)
    app.include_router(tags.router)

    if settings.figures_dir.is_dir():
        app.mount("/figures", StaticFiles(directory=str(settings.figures_dir)), name="figures")
    else:
        logger.warning("그림 디렉터리가 없어 /figures 를 마운트하지 않습니다: %s", settings.figures_dir)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {"service": "ipe-api", "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health", tags=["meta"], summary="헬스체크")
    def health() -> JSONResponse:
        reachable = db.ping()
        payload = {
            "status": "ok" if reachable else "degraded",
            "database": "ok" if reachable else "unavailable",
            "dbUrlSource": get_settings().db_url_source,
        }
        return JSONResponse(payload, status_code=200 if reachable else 503)

    return app


app = create_app()
