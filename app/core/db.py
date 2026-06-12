"""Async SQLAlchemy engine + session factory (Postgres/pgvector via psycopg3).

Same SQL locally and on Aurora Serverless v2 in the cloud — only DATABASE_URL
changes. ORM models (Phase 1) inherit from `Base`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


engine: AsyncEngine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a request-scoped async session."""
    async with SessionLocal() as session:
        yield session


async def ping() -> bool:
    """True if the database answers a trivial query."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
