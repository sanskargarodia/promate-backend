"""Deterministic tool routing — agent logic selects tools; tools return data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agents.state import AgentState

PS_RE = re.compile(r"\b(PS\d+)\b", re.I)
ORDER_RE = re.compile(r"\b(ORD-[A-Z0-9-]+)\b", re.I)

PURCHASE_INTENT_PHRASES = (
    "ready to buy",
    "ready to order",
    "i'll buy",
    "i will buy",
    "want to buy",
    "want to order",
    "where can i purchase",
    "where can i buy",
    "purchase this",
    "buy this part",
    "order this part",
    "i'd like to order",
    "i would like to order",
)


@dataclass(frozen=True)
class PlannedToolCall:
    name: str
    arguments: dict[str, Any]


def _last_user_text(state: AgentState) -> str:
    from app.agents.nodes import _last_user_text as last_text

    return last_text(state)


def detect_purchase_intent(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in PURCHASE_INTENT_PHRASES)


def plan_transactional_tools(state: AgentState) -> list[PlannedToolCall]:
    """Map user utterance + state to mandatory tool invocations."""
    text = _last_user_text(state)
    lowered = text.lower()
    ps = state.get("ps_number") or state.get("identified_part_id")
    if not ps:
        match = PS_RE.search(text)
        ps = match.group(1).upper() if match else None

    calls: list[PlannedToolCall] = []

    if any(
        w in lowered
        for w in ("order status", "track order", "where is my order", "status of order")
    ) or (ORDER_RE.search(text) and "status" in lowered):
        order_match = ORDER_RE.search(text)
        order_id = order_match.group(1) if order_match else text.strip()
        calls.append(PlannedToolCall("get_order_status", {"order_id": order_id}))
        return calls

    if detect_purchase_intent(text):
        if ps:
            calls.append(PlannedToolCall("get_part_details", {"part_id": ps}))
        calls.append(PlannedToolCall("purchase_handoff", {"part_id": ps}))
        return calls

    if ps and (
        state.get("intent") in {"product_search", "installation", "compatibility"}
        or "price" in lowered
        or "cost" in lowered
        or "stock" in lowered
        or "details" in lowered
    ):
        calls.append(PlannedToolCall("get_part_details", {"part_id": ps}))

    if not calls:
        calls.append(
            PlannedToolCall(
                "search_parts",
                {
                    "symptom_or_model": text,
                    "appliance_type": state.get("appliance_type"),
                },
            )
        )
    elif state.get("intent") == "troubleshooting" and not any(
        c.name == "get_part_details" for c in calls
    ):
        calls.append(
            PlannedToolCall(
                "search_parts",
                {
                    "symptom_or_model": text,
                    "appliance_type": state.get("appliance_type"),
                },
            )
        )

    return calls
