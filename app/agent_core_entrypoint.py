"""Bedrock AgentCore Runtime entrypoint — same graph as FastAPI (app/main.py).

Deploy target: invoke this handler from AgentCore; local dev uses POST /api/v1/chat.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.agents.run import run_agent_turn
from app.core.db import SessionLocal


async def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one agent turn and return collected SSE-style events."""
    message = str(payload.get("message") or payload.get("prompt") or "").strip()
    if not message:
        return {"error": "message is required", "events": []}

    thread_id = payload.get("thread_id")
    events: list[dict[str, Any]] = []
    async with SessionLocal() as session:
        async for event in run_agent_turn(
            message=message,
            session=session,
            thread_id=str(thread_id) if thread_id else None,
        ):
            events.append(event)

    tid = next((e.get("thread_id") for e in events if e.get("type") == "session"), None)
    return {"thread_id": tid, "events": events}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """AgentCore-compatible sync handler."""
    _ = context
    return asyncio.run(invoke(event))
