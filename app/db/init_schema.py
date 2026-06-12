"""Create Postgres extensions and ORM tables (idempotent)."""

from __future__ import annotations

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import Base, engine
from app.models import catalog  # noqa: F401 — register ORM metadata


async def init_schema(db_engine: AsyncEngine | None = None) -> None:
    """Enable pgvector and create all tables if missing."""
    active = db_engine or engine
    async with active.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)


def main() -> None:
    asyncio.run(init_schema())


if __name__ == "__main__":
    main()
