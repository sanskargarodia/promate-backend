"""Per-intent worker nodes — tool execution split by supervisor routing."""

from __future__ import annotations

from typing import Any

from langgraph.types import RunnableConfig

from app.agents.conversation import build_working_query
from app.agents.nodes import (
    _gather_support_context,
    _last_user_text,
)
from app.agents.state import AgentState
from app.agents.status import NODE_STATUS, emit_status, tool_status
from app.agents.tool_router import plan_transactional_tools
from app.agents.transaction_state import TransactionPhase, TransactionStateMachine
from app.core.config import is_llm_configured
from app.services import related_parts as related_parts_svc
from app.tools import transactional as txn_tools

WORKER_NODE_KEYS = (
    "product_search_worker",
    "compatibility_worker",
    "installation_worker",
    "troubleshooting_worker",
    "transaction_worker",
    "order_status_worker",
)


async def _execute_worker_tools(
    state: AgentState,
    config: RunnableConfig,
    *,
    worker_key: str,
) -> dict[str, Any]:
    """Run planned transactional tools and assemble tool_payload for the composer."""
    emit_status(NODE_STATUS.get(
        worker_key, NODE_STATUS["transactional_tools"]))
    session = config["configurable"]["session"]
    text = _last_user_text(state)
    working_query = build_working_query(state)

    phase_raw = state.get("transaction_phase") or TransactionPhase.SEARCHING
    machine = TransactionStateMachine(phase_raw)

    tool_results: dict[str, object] = {}
    purchase_handoffs: list[dict[str, object]] = []
    allowed: set[str] = set()
    identified_part_id = state.get("identified_part_id")
    catalog_grounded = True

    for call in plan_transactional_tools(state):
        emit_status(tool_status(
            call.name, **{k: str(v) for k, v in call.arguments.items()}))
        if call.name == "get_part_details":
            result = await txn_tools.get_part_details(session, call.arguments["part_id"])
            tool_results["get_part_details"] = result.model_dump()
            if result.found:
                machine.after_part_details(result)
                identified_part_id = result.part_id
                allowed.add(result.part_id)
            else:
                catalog_grounded = False

        elif call.name == "search_parts":
            result = await txn_tools.search_parts(
                session,
                call.arguments["symptom_or_model"],
                appliance_type=call.arguments.get("appliance_type"),
            )
            tool_results["search_parts"] = result.model_dump()
            machine.after_search(parts_found=len(result.parts))
            if not result.found:
                catalog_grounded = False
            for part in result.parts:
                allowed.add(part.part_id)
            if len(result.parts) == 1:
                machine.after_part_details(result.parts[0])
                identified_part_id = result.parts[0].part_id

        elif call.name == "get_order_status":
            result = await txn_tools.get_order_status(
                session, call.arguments["order_id"]
            )
            tool_results["get_order_status"] = result.model_dump()

        elif call.name == "purchase_handoff":
            part_id = call.arguments.get("part_id") or identified_part_id
            handoff = await txn_tools.prepare_purchase_handoff(
                session,
                part_id=part_id,
                machine=machine,
            )
            tool_results["purchase_handoff"] = handoff.model_dump()
            if handoff.allowed and handoff.ps_number:
                identified_part_id = handoff.ps_number
                allowed.add(handoff.ps_number)
                purchase_handoffs.append(handoff.model_dump())

    tool_payload: dict[str, object] = {
        "tool_results": tool_results,
        "transaction_phase": machine.phase.value,
    }
    if tool_results.get("search_parts"):
        sr = tool_results["search_parts"]
        if isinstance(sr, dict) and sr.get("parts"):
            tool_payload["matching_parts"] = sr["parts"]
    if tool_results.get("get_part_details"):
        details = tool_results["get_part_details"]
        if isinstance(details, dict) and details.get("found"):
            tool_payload["part"] = details

    await _gather_support_context(state, session, text, tool_payload, allowed)

    primary = tool_payload.get("part")
    if isinstance(primary, dict) and primary.get("found"):
        ps = str(primary.get("part_id") or primary.get("ps_number") or "")
        if ps and is_llm_configured():
            related = await related_parts_svc.find_related_parts(
                session,
                ps_number=ps,
                part_name=str(primary.get("name") or ""),
                user_message=working_query or text,
                limit=2,
            )
            if related:
                tool_payload["related_parts"] = [p.model_dump()
                                                 for p in related]
                allowed.update(p.ps_number for p in related)

    compat = tool_payload.get("compatibility")
    if isinstance(compat, dict):
        machine.after_compatibility(compatible=compat.get("compatible"))

    tool_payload["transaction_phase"] = machine.phase.value

    return {
        "transaction_phase": machine.phase.value,
        "identified_part_id": identified_part_id,
        "tool_results": tool_results,
        "tool_payload": tool_payload,
        "purchase_handoffs": purchase_handoffs,
        "allowed_ps_numbers": sorted(allowed),
        "catalog_grounded": catalog_grounded,
    }


async def product_search_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="product_search_worker")


async def compatibility_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="compatibility_worker")


async def installation_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="installation_worker")


async def troubleshooting_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="troubleshooting_worker")


async def transaction_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="transaction_worker")


async def order_status_worker_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    return await _execute_worker_tools(state, config, worker_key="order_status_worker")


async def transactional_tools_node(
    state: AgentState, config: RunnableConfig,
) -> dict[str, Any]:
    """Backward-compatible alias — routes to the shared worker executor."""
    return await _execute_worker_tools(state, config, worker_key="transactional_tools")
