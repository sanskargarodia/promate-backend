"""Create Postgres extensions and ORM tables (idempotent)."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import settings
from app.core.db import Base, engine
from app.models import catalog  # noqa: F401 — register ORM metadata


def _sync_engine() -> Engine:
    return create_engine(settings.sqlalchemy_sync_database_url, pool_pre_ping=True)


def init_schema_sync(db_engine: Engine | None = None) -> None:
    """Enable pgvector and create all tables (sync — safe on Windows for batch jobs)."""
    active = db_engine or _sync_engine()
    with active.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        Base.metadata.create_all(conn)


async def init_schema(db_engine: AsyncEngine | None = None) -> None:
    """Enable pgvector and create all tables if missing (async FastAPI path)."""
    active = db_engine or engine
    async with active.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    # Async psycopg requires SelectorEventLoop; Windows defaults to ProactorEventLoop.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    init_schema_sync()


if __name__ == "__main__":
    main()
