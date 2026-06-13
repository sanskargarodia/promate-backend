"""Database URL normalization for Aurora / psycopg conninfo."""

from __future__ import annotations

from app.core.config import (
    Settings,
    _needs_db_ssl,
    _normalize_libpq_url,
    _with_db_ssl,
)

AURORA_HOST = (
    "promate-cluster.cluster-cmtsw84oojhj.us-east-1.rds.amazonaws.com:5432/promate"
)


def test_normalize_libpq_url_strips_sqlalchemy_driver() -> None:
    raw = f"postgresql+psycopg://user:pass@{AURORA_HOST}"
    assert _normalize_libpq_url(raw) == f"postgresql://user:pass@{AURORA_HOST}"


def test_with_db_ssl_appends_for_aurora() -> None:
    url = f"postgresql://user:pass@{AURORA_HOST}"
    assert _with_db_ssl(url, app_env="local") == f"{url}?sslmode=require"


def test_with_db_ssl_skips_localhost() -> None:
    url = "postgresql://promate:promate@localhost:5433/promate"
    assert _with_db_ssl(url, app_env="production") == url


def test_with_db_ssl_for_production_remote_host() -> None:
    url = "postgresql://user:pass@db.internal.example.com:5432/promate"
    assert _with_db_ssl(url, app_env="production") == f"{url}?sslmode=require"
    assert _with_db_ssl(url, app_env="local") == url


def test_settings_normalizes_sync_url_and_ssl() -> None:
    settings = Settings(
        app_env="production",
        database_url_sync=(
            f"postgresql+psycopg://user:pass@{AURORA_HOST}"
        ),
    )
    assert settings.database_url_sync.startswith("postgresql://")
    assert "postgresql+psycopg://" not in settings.database_url_sync
    assert "sslmode=require" in settings.database_url_sync


def test_needs_db_ssl_detects_aws_hosts() -> None:
    url = f"postgresql://user:pass@{AURORA_HOST}"
    assert _needs_db_ssl(url, app_env="local") is True
