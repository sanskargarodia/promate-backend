"""Shared agent invocation for FastAPI and AgentCore entrypoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from langchain_core.messages import HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.graph import get_compiled_graph
from app.schemas.catalog import PartResult


def _part_dict_to_card(item: dict[str, object]) -> dict[str, object]:
    return PartResult.model_validate(
        {
            "ps_number": item.get("part_id") or item.get("ps_number"),
            "name": item.get("name", ""),
            "brand": item.get("brand"),
            "appliance_type": item.get("appliance_type", "refrigerator"),
            "price_cents": item.get("price_cents"),
            "in_stock": item.get("in_stock", False),
            "image_urls": item.get("image_urls") or [],
            "source_url": item.get("source_url"),
        }
    ).model_dump()


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

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )

    for handoff in result.get("purchase_handoffs") or []:
        if isinstance(handoff, dict) and handoff.get("action") == "purchase_handoff":
            yield {"type": "purchase_handoff", **handoff}

    final = result.get("final_response") or ""
    if final:
        yield {"type": "token", "content": final}

    tool_payload = result.get("tool_payload") or {}
    emitted: set[str] = set()

    primary = tool_payload.get("part")
    if isinstance(primary, dict) and primary.get("found", True):
        card = _part_dict_to_card(primary)
        emitted.add(str(card["ps_number"]))
        yield {"type": "product_card", "part": card}

    parts_raw = tool_payload.get("matching_parts") or tool_payload.get("parts")
    if isinstance(parts_raw, list):
        for item in parts_raw[:3]:
            if not isinstance(item, dict):
                continue
            card = _part_dict_to_card(item)
            ps = str(card["ps_number"])
            if ps in emitted:
                continue
            emitted.add(ps)
            yield {"type": "product_card", "part": card}

    yield {"type": "done"}
