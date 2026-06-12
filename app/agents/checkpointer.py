"""LangGraph Postgres checkpointer (multi-turn conversation memory)."""

from __future__ import annotations

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None
_connection: AsyncConnection | None = None


async def init_checkpointer() -> AsyncPostgresSaver:
    """Create checkpoint tables and return a process-wide saver."""
    global _checkpointer, _connection
    if _checkpointer is not None:
        return _checkpointer

    _connection = await AsyncConnection.connect(
        settings.database_url_sync,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    _checkpointer = AsyncPostgresSaver(conn=_connection)
    await _checkpointer.setup()
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpointer, _connection
    _checkpointer = None
    if _connection is not None:
        await _connection.close()
        _connection = None


def get_checkpointer() -> AsyncPostgresSaver | None:
    return _checkpointer
