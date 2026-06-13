"""Health/readiness endpoints under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.agents.checkpointer import get_checkpointer
from app.core.db import ping

router = APIRouter()


@router.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Readiness probe: reports app + database + conversation memory status."""
    try:
        db_up = await ping()
    except Exception:  # noqa: BLE001 - readiness must never raise
        db_up = False
    memory = "enabled" if get_checkpointer() is not None else "disabled"
    return {
        "status": "ok",
        "database": "up" if db_up else "down",
        "conversation_memory": memory,
    }
