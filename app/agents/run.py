"""Shared agent invocation for FastAPI and AgentCore entrypoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_compiled_graph
from app.agents.product_cards import select_product_cards


def _yield_result_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Build terminal SSE events from the final graph state."""
    events: list[dict[str, Any]] = []

    for handoff in result.get("purchase_handoffs") or []:
        if isinstance(handoff, dict) and handoff.get("action") == "purchase_handoff":
            events.append({"type": "purchase_handoff", **handoff})

    final = result.get("final_response") or ""
    if final:
        events.append({"type": "token", "content": final})

    for card in select_product_cards(result):
        events.append(
            {
                "type": "product_card",
                "part": card["part"],
                "card_role": card["card_role"],
            }
        )

    follow_ups = result.get("suggested_follow_ups") or []
    if follow_ups:
        events.append({"type": "suggestions", "prompts": list(follow_ups)})

    return events


async def run_agent_turn(
    *,
    message: str,
    session: AsyncSession,
    thread_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream high-level agent events for the chat SSE contract."""
    graph = get_compiled_graph()
    tid = thread_id or str(uuid4())
    config = {
        "configurable": {
            "thread_id": tid,
            "session": session,
        }
    }

    yield {"type": "session", "thread_id": tid}
    yield {"type": "status", "message": "Starting…"}

    result: dict[str, Any] = {}
    async for mode, chunk in graph.astream(
        {"messages": [HumanMessage(content=message)]},
        config=config,
        stream_mode=["custom", "values"],
    ):
        if mode == "custom" and isinstance(chunk, dict):
            status_message = chunk.get("message")
            if status_message:
                yield {"type": "status", "message": str(status_message)}
        elif mode == "values" and isinstance(chunk, dict):
            result = chunk

    for event in _yield_result_events(result):
        yield event

    yield {"type": "done"}
