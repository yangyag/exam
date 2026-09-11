"""설정 로딩 테스트. 접속 문자열 우선순위(EXAM_DB_URL → DATABASE_URL → PG* → 기본값)를 고정한다.

도구(tools/load_db.py)와 백엔드(app/config.py)가 같은 우선순위를 쓰는지가 핵심이다.
"""
from __future__ import annotations

import os

import pytest

from app import config


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    """실제 셸 환경변수와 저장소 .env 가 테스트에 새어 들어오지 않게 격리한다."""
    for var in ("EXAM_DB_URL", "DATABASE_URL", "EXAM_API_TOKEN", "EXAM_CORS_ORIGINS", *config.PG_ENV_VARS):
        monkeypatch.delenv(var, raising=False)
    # resolve_db_url() 이 저장소 .env 를 읽지 않게 no-op 으로 바꾼다.
    # (테스트가 경로를 직접 주고 부르는 호출은 원본 함수로 통과시킨다)
    original = config.load_env_file
    monkeypatch.setattr(
        config,
        "load_env_file",
        lambda path=None: set() if path is None else original(path),
    )
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)


def test_load_env_file_reads_and_strips_quotes(tmp_path):
    """.env 파일: 주석·빈 줄·공백·따옴표를 정리해 환경변수로 올린다."""
    env = tmp_path / ".env"
    env.write_text(
        "# 주석\n"
        "\n"
        'EXAM_DB_URL = "postgresql://yangyag@localhost:5432/app" \n'
        "QUOTED_SINGLE='값'\n"
        "NO_EQUALS\n",
        encoding="utf-8",
    )
    loaded = config.load_env_file(env)
    assert loaded == {"EXAM_DB_URL", "QUOTED_SINGLE"}
    assert os.environ["EXAM_DB_URL"] == "postgresql://yangyag@localhost:5432/app"
    assert os.environ["QUOTED_SINGLE"] == "값"
    assert "NO_EQUALS" not in os.environ


def test_load_env_file_keeps_existing_env(tmp_path, monkeypatch):
    """이미 설정된 환경변수는 .env 값으로 덮어쓰지 않는다."""
    monkeypatch.setenv("EXAM_DB_URL", "postgresql://이미-설정됨")
    env = tmp_path / ".env"
    env.write_text("EXAM_DB_URL=postgresql://파일값\n", encoding="utf-8")
    loaded = config.load_env_file(env)
    assert "EXAM_DB_URL" not in loaded
    assert os.environ["EXAM_DB_URL"] == "postgresql://이미-설정됨"


def test_load_env_file_missing_file_is_noop(tmp_path):
    assert config.load_env_file(tmp_path / "없는파일.env") == set()


def test_resolve_prefers_exam_db_url(monkeypatch):
    monkeypatch.setenv("EXAM_DB_URL", "postgresql://exam")
    monkeypatch.setenv("DATABASE_URL", "postgresql://database")
    url, source = config.resolve_db_url()
    assert url == "postgresql://exam"
    assert source == "EXAM_DB_URL"


def test_resolve_falls_back_to_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://database")
    url, source = config.resolve_db_url()
    assert url == "postgresql://database"
    assert source == "DATABASE_URL"


def test_resolve_marks_env_file_origin(monkeypatch):
    """저장소 .env 에서 온 값이면 출처에 (.env) 가 붙는다."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://from-file")
    monkeypatch.setattr(config, "load_env_file", lambda *args, **kwargs: {"DATABASE_URL"})
    url, source = config.resolve_db_url()
    assert url == "postgresql://from-file"
    assert source == "DATABASE_URL (.env)"


@pytest.mark.parametrize("var", config.PG_ENV_VARS)
def test_resolve_uses_libpq_env(monkeypatch, var):
    """URL 이 없고 PG* 만 있으면 빈 문자열(=libpq 환경변수 사용)을 돌려준다."""
    monkeypatch.setenv(var, "값")
    url, source = config.resolve_db_url()
    assert url == ""
    assert source == "libpq PG* 환경변수"


def test_resolve_falls_back_to_default():
    url, source = config.resolve_db_url()
    assert url == config.DEFAULT_DB_URL
    assert source == "기본값"


def test_settings_api_token_empty_means_none(monkeypatch):
    monkeypatch.setenv("EXAM_API_TOKEN", "")
    assert config.get_settings().api_token is None
    config.get_settings.cache_clear()
    monkeypatch.setenv("EXAM_API_TOKEN", "비밀토큰")
    assert config.get_settings().api_token == "비밀토큰"


def test_settings_cors_origins_normalized(monkeypatch):
    """기본 오리진은 유지되고, 추가분은 공백·끝 슬래시 제거 후 중복이 걸러진다."""
    origins = config.get_settings().cors_origins
    assert origins == list(config.DEFAULT_CORS_ORIGINS)

    config.get_settings.cache_clear()
    monkeypatch.setenv(
        "EXAM_CORS_ORIGINS",
        "https://양약.example, http://localhost:8091/, https://양약.example",
    )
    origins = config.get_settings().cors_origins
    assert origins == ["http://localhost:8091", "https://양약.example"]


def test_settings_points_at_dataset_figures():
    settings = config.get_settings()
    assert settings.figures_dir == config.FIGURES_DIR
    assert settings.db_url_source in {"EXAM_DB_URL", "DATABASE_URL", "libpq PG* 환경변수", "기본값"}
