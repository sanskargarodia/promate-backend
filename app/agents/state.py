"""LangGraph agent state schema."""

from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

Intent = Literal[
    "product_search",
    "compatibility",
    "installation",
    "troubleshooting",
    "clarification",
    "refusal",
]


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    intent: Intent
    ps_number: str | None
    model_number: str | None
    appliance_type: str | None
    brand: str | None
    tool_payload: dict[str, object]
    allowed_ps_numbers: list[str]
    guardrail_notes: list[str]
    final_response: str
    refused: bool
