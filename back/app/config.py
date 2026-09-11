"""백엔드 설정. 접속 문자열 우선순위는 tools/load_db.py 와 맞춘다.

    1) EXAM_DB_URL (환경변수 또는 저장소 루트 .env)
    2) DATABASE_URL
    3) libpq PG* 환경변수 (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)
    4) 기본값 postgresql://yangyag@localhost:5432/app
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# back/app/config.py → back/app → back → 저장소 루트
ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
FIGURES_DIR = ROOT / "data" / "figures"
DEFAULT_DB_URL = "postgresql://yangyag@localhost:5432/app"
PG_ENV_VARS = ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD")
DEFAULT_CORS_ORIGINS = ("http://localhost:8091",)


def load_env_file(path: Path = ENV_FILE) -> set[str]:
    """`.env` 를 환경변수로 올린다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    loaded: set[str] = set()
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded


def resolve_db_url() -> tuple[str, str]:
    """(접속 문자열, 출처). 문자열이 비면 libpq PG* 환경변수를 쓴다는 뜻이다."""
    from_file = load_env_file()
    for var in ("EXAM_DB_URL", "DATABASE_URL"):
        if os.environ.get(var):
            return os.environ[var], var + (" (.env)" if var in from_file else "")
    if any(os.environ.get(v) for v in PG_ENV_VARS):
        return "", "libpq PG* 환경변수"
    return DEFAULT_DB_URL, "기본값"


def _cors_origins() -> list[str]:
    origins = list(DEFAULT_CORS_ORIGINS)
    for item in os.environ.get("EXAM_CORS_ORIGINS", "").split(","):
        item = item.strip().rstrip("/")
        if item and item not in origins:
            origins.append(item)
    return origins


@dataclass(frozen=True)
class Settings:
    db_url: str
    db_url_source: str
    api_token: str | None
    cors_origins: list[str]
    figures_dir: Path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    db_url, source = resolve_db_url()
    return Settings(
        db_url=db_url,
        db_url_source=source,
        api_token=os.environ.get("EXAM_API_TOKEN") or None,
        cors_origins=_cors_origins(),
        figures_dir=FIGURES_DIR,
    )
