"""Application settings, loaded from environment / .env via pydantic-settings.

This is the single source of truth for every tunable. The "scale without rewrites"
story lives here: flipping LLM_PROVIDER, EMBEDDINGS_PROVIDER, or DATABASE_URL moves
the system from local (Anthropic API + local Postgres/pgvector + fastembed) to cloud
(Bedrock Claude + Aurora + Titan) without touching agent or tool code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "postgres"})


def _normalize_libpq_url(url: str) -> str:
    """Strip SQLAlchemy driver suffix so raw psycopg conninfo parses correctly."""
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+psycopg2://",
        "postgres+psycopg://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url.removeprefix(prefix)
    if url.startswith("postgres://"):
        return "postgresql://" + url.removeprefix("postgres://")
    return url


def _remote_db_host(url: str) -> str | None:
    """Best-effort host extraction from a Postgres URL."""
    if "://" not in url or "@" not in url:
        return None
    host_port = url.split("@", 1)[1].split("/", 1)[0]
    return host_port.rsplit(":", 1)[0].lower()


def _needs_db_ssl(url: str, *, app_env: str) -> bool:
    """True when the target host is remote and should use TLS."""
    if "rds.amazonaws.com" in url or ".amazonaws.com" in url:
        return True
    host = _remote_db_host(url)
    if host is None or host in _LOCAL_DB_HOSTS:
        return False
    return app_env == "production"


def _with_db_ssl(url: str, *, app_env: str) -> str:
    """Append sslmode=require for Aurora and other remote production databases."""
    if "sslmode=" in url or not _needs_db_ssl(url, app_env=app_env):
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sslmode=require"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = "local"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3001, http://localhost:3000"

    # ── LLM (app/core/llm.py) ────────────────────────────────────────────────
    # The agent's LLM is ALWAYS the Anthropic API — both locally and when the
    # agent is hosted on Bedrock AgentCore. AgentCore is the agent *host* (a
    # serverless runtime), NOT a model provider; we never call Bedrock-served
    # models. The same ANTHROPIC_API_KEY is injected wherever the agent runs.
    anthropic_api_key: str | None = None
    anthropic_model_id: str = "claude-sonnet-4-6"
    anthropic_guardrail_model_id: str = "claude-haiku-4-5"
    # AWS region for the AgentCore Runtime deploy/invoke path (not model serving).
    aws_region: str = "us-east-1"

    # ── Embeddings (app/core/embeddings.py) ──────────────────────────────────
    # "fastembed" (local default) or "bedrock" (Titan). Agent/tools never import
    # embedders directly — only `get_embedder()`.
    embeddings_provider: str = "fastembed"
    fastembed_model: str = "BAAI/bge-small-en-v1.5"
    bedrock_embeddings_model_id: str = "amazon.titan-embed-text-v2:0"
    # bge-small = 384; Titan v2 = 1024 — pgvector column must match
    embedding_dim: int = 384

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = "postgresql+psycopg://promate:promate@localhost:5433/promate"
    # libpq conninfo for LangGraph PostgresSaver / psycopg pools (postgresql://…).
    database_url_sync: str = "postgresql://promate:promate@localhost:5433/promate"

    @model_validator(mode="after")
    def normalize_database_urls(self) -> Self:
        self.database_url = _with_db_ssl(
            self.database_url, app_env=self.app_env)
        sync = _normalize_libpq_url(self.database_url_sync)
        self.database_url_sync = _with_db_ssl(sync, app_env=self.app_env)
        return self

    @property
    def sqlalchemy_sync_database_url(self) -> str:
        """Sync SQLAlchemy URL using psycopg3 (not psycopg2)."""
        url = self.database_url_sync
        if "+psycopg" in url or "+psycopg2" in url:
            return url
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        if url.startswith("postgres://"):
            return "postgresql+psycopg://" + url.removeprefix("postgres://")
        return url

    catalog_csv_path: str | None = None

    # ── Observability ────────────────────────────────────────────────────────
    langsmith_tracing: bool = False
    langsmith_api_key: str | None = None
    langsmith_project: str = "promate"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def is_llm_configured() -> bool:
    """True when the Anthropic API key is set and the composer can run."""
    return bool(settings.anthropic_api_key)
