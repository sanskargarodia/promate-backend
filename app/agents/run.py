"""Shared agent invocation for FastAPI and AgentCore entrypoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_compiled_graph
from app.schemas.catalog import PartResult


async def run_agent_turn(
    *,
    message: str,
    session: AsyncSession,
    thread_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream high-level agent events for the chat SSE contract."""
    graph = get_compiled_graph()
    tid = thread_id or str(uuid4())
    config = {"configurable": {"thread_id": tid, "session": session}}

    yield {"type": "session", "thread_id": tid}

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )

    final = result.get("final_response") or ""
    if final:
        yield {"type": "token", "content": final}

    tool_payload = result.get("tool_payload") or {}
    parts_raw = tool_payload.get("parts")
    if isinstance(parts_raw, list):
        for item in parts_raw[:3]:
            if isinstance(item, dict):
                card = PartResult.model_validate(item)
                yield {
                    "type": "product_card",
                    "part": card.model_dump(),
                }

    yield {"type": "done"}
