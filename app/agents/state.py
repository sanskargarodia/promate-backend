"""LangGraph agent state schema."""

from __future__ import annotations

from typing import Annotated, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.agents.transaction_state import TransactionPhase

Intent = Literal[
    "product_search",
    "compatibility",
    "installation",
    "troubleshooting",
    "clarification",
    "refusal",
    "transaction",
]


class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    intent: Intent
    ps_number: str | None
    model_number: str | None
    appliance_type: str | None
    brand: str | None
    transaction_phase: TransactionPhase | str
    identified_part_id: str | None
    tool_results: dict[str, object]
    tool_payload: dict[str, object]
    purchase_handoffs: list[dict[str, object]]
    allowed_ps_numbers: list[str]
    catalog_grounded: bool
    guardrail_notes: list[str]
    final_response: str
    refused: bool
