"""LangGraph Postgres checkpointer (multi-turn conversation memory)."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_pool: AsyncConnectionPool | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    """Create checkpoint tables and return a process-wide saver."""
    global _checkpointer, _pool
    if _checkpointer is not None:
        return _checkpointer

    _pool = AsyncConnectionPool(
        conninfo=settings.database_url_sync,
        kwargs={
            "autocommit": True,
            "prepare_threshold": 0,
            "row_factory": dict_row,
        },
        min_size=1,
        max_size=4,
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await _pool.open()
    await _pool.wait()

    _checkpointer = AsyncPostgresSaver(conn=_pool)
    try:
        await _checkpointer.setup()
    except Exception as exc:
        # AgentCore scales workers in parallel; migration insert can race.
        msg = str(exc)
        if "checkpoint_migrations_pkey" not in msg and "already exists" not in msg:
            raise
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpointer, _pool
    _checkpointer = None
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_checkpointer() -> AsyncPostgresSaver | None:
    return _checkpointer
