"""Streaming chat endpoint (SSE)."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.agents.run import run_agent_turn
from app.core.db import get_session
from app.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(
    body: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> EventSourceResponse:
    async def event_generator():
        try:
            async for event in run_agent_turn(
                message=body.message,
                session=session,
                thread_id=body.thread_id,
            ):
                yield {"event": event.get("type", "message"), "data": json.dumps(event)}
        except Exception as exc:  # noqa: BLE001
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "content": str(exc)}),
            }
            yield {"event": "done", "data": json.dumps({"type": "done"})}

    return EventSourceResponse(event_generator())
