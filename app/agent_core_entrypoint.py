"""Bedrock AgentCore Runtime entrypoint — same graph as FastAPI (app/main.py).

Deploy target: `python -m app.agent_core_entrypoint` (port 8080) via AgentCore Runtime
direct code deploy. Local dev uses POST /api/v1/chat on FastAPI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from bedrock_agentcore import BedrockAgentCoreApp, RequestContext

from app.agents.checkpointer import close_checkpointer, init_checkpointer
from app.agents.graph import build_graph, set_compiled_graph
from app.agents.run import run_agent_turn
from app.catalog.startup import ensure_catalog_ready
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: BedrockAgentCoreApp) -> AsyncIterator[None]:
    """Mirror FastAPI startup: catalog validation + LangGraph checkpointer."""
    configure_logging(settings.log_level)
    try:
        async with SessionLocal() as db_session:
            await ensure_catalog_ready(db_session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Catalog validation skipped: %s", exc)
    try:
        checkpointer = await init_checkpointer()
        set_compiled_graph(build_graph(checkpointer=checkpointer))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Postgres checkpointer unavailable (%s); multi-turn chat disabled.", exc
        )
        set_compiled_graph(build_graph(checkpointer=None))
    yield
    await close_checkpointer()


app = BedrockAgentCoreApp(lifespan=lifespan)


def extract_message(payload: dict[str, Any]) -> str:
    """Accept AgentCore `prompt` or our API `message` key."""
    return str(payload.get("message") or payload.get("prompt") or "").strip()


def resolve_thread_id(payload: dict[str, Any], context: RequestContext) -> str | None:
    """Prefer explicit thread_id; fall back to AgentCore session header."""
    thread_id = payload.get("thread_id")
    if thread_id:
        return str(thread_id)
    if context.session_id:
        return context.session_id
    return None


@app.entrypoint
async def invoke(
    payload: dict[str, Any],
    context: RequestContext,
) -> AsyncIterator[dict[str, Any]]:
    """Stream ProMate agent events (same contract as POST /api/v1/chat SSE payloads)."""
    message = extract_message(payload)
    if not message:
        yield {"type": "error", "content": "message or prompt is required"}
        yield {"type": "done"}
        return

    thread_id = resolve_thread_id(payload, context)
    try:
        async with SessionLocal() as session:
            async for event in run_agent_turn(
                message=message,
                session=session,
                thread_id=thread_id,
            ):
                yield event
    except Exception as exc:  # noqa: BLE001
        logger.exception("AgentCore invocation failed")
        yield {"type": "error", "content": str(exc)}
        yield {"type": "done"}


async def collect_events(
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Aggregate streamed events — useful for tests and non-streaming invoke clients."""
    context = RequestContext(session_id=session_id)
    events: list[dict[str, Any]] = []
    async for event in invoke(payload, context):
        events.append(event)
    thread_id = next((e.get("thread_id")
                     for e in events if e.get("type") == "session"), None)
    return {"thread_id": thread_id, "events": events}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Sync wrapper for direct/Lambda-style invocation (collects streamed events)."""
    session_id = getattr(context, "session_id",
                         None) if context is not None else None
    if session_id is None:
        session_id = event.get("session_id")
    return asyncio.run(collect_events(event, session_id=str(session_id) if session_id else None))


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    """Parse AgentCore `text/event-stream` lines into JSON event dicts."""
    events: list[dict[str, Any]] = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        events.append(json.loads(line.removeprefix("data: ").strip()))
    return events


if __name__ == "__main__":
    app.run()
