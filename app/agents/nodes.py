"""Graph node implementations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import RunnableConfig

from app.agents.state import AgentState, Intent
from app.agents.tool_router import plan_transactional_tools
from app.agents.transaction_state import TransactionPhase, TransactionStateMachine
from app.core.config import is_llm_configured
from app.core.llm import get_chat_model, get_guardrail_model
from app.guardrails.input import run_input_guardrails
from app.guardrails.output import validate_output
from app.services import catalog as catalog_svc
from app.services import retrieval as retrieval_svc
from app.tools import transactional as txn_tools

PS_RE = re.compile(r"\b(PS\d+)\b", re.I)
MODEL_RE = re.compile(r"\b([A-Z]{2,}\d{3,}[A-Z0-9]*)\b")

_LLM_UNAVAILABLE = (
    "The assistant needs an Anthropic API key to compose answers from catalog data. "
    "Add ANTHROPIC_API_KEY to promate-backend/.env and restart the server."
)


def _prompt(name: str, **kwargs: str) -> str:
    path = Path(__file__).resolve().parent / "prompts" / f"{name}.txt"
    return path.read_text(encoding="utf-8").format(**kwargs)


def _last_user_text(state: AgentState) -> str:
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage):
            content = msg.content
            return content if isinstance(content, str) else str(content)
        if isinstance(msg, dict) and msg.get("role") == "user":
            return str(msg.get("content", ""))
    return ""


def _heuristic_route(text: str) -> dict[str, Any]:
    lowered = text.lower()
    ps_match = PS_RE.search(text)
    model_match = None
    for candidate in MODEL_RE.finditer(text):
        token = candidate.group(1).upper()
        if not token.startswith("PS"):
            model_match = candidate
            break

    intent: Intent = "product_search"
    if "install" in lowered and ps_match:
        intent = "installation"
    elif any(w in lowered for w in ("compatible", "compatibility", "fit my", "work with my")):
        intent = "compatibility"
    elif any(
        w in lowered
        for w in ("not working", "won't", "wont", "fix", "broken", "leaking", "noisy")
    ):
        intent = "troubleshooting"
    elif ps_match and not model_match:
        intent = "product_search"

    appliance_type = None
    if "dishwasher" in lowered:
        appliance_type = "dishwasher"
    elif "fridge" in lowered or "refrigerator" in lowered:
        appliance_type = "refrigerator"

    brand = None
    for candidate in ("Whirlpool", "KitchenAid", "Maytag", "GE", "Samsung", "LG", "Frigidaire"):
        if candidate.lower() in lowered:
            brand = candidate
            break

    return {
        "intent": intent,
        "ps_number": ps_match.group(1).upper() if ps_match else None,
        "model_number": model_match.group(1).upper() if model_match else None,
        "appliance_type": appliance_type,
        "brand": brand,
    }


async def _llm_route(text: str) -> dict[str, Any] | None:
    if not is_llm_configured():
        return None

    model = get_guardrail_model()
    prompt = _prompt("supervisor", user_message=text)
    try:
        resp = await model.ainvoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
    except Exception:  # noqa: BLE001
        return None
    return None


async def input_guardrail_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = _last_user_text(state)
    verdict = run_input_guardrails(text)
    notes = [verdict.reason]
    if not verdict.in_scope or verdict.injection_detected:
        return {"refused": True, "intent": "refusal", "guardrail_notes": notes}
    return {"refused": False, "guardrail_notes": notes}


async def refusal_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    reason = (state.get("guardrail_notes") or ["that topic"])[0]
    text = _prompt("refusal", reason=reason)
    return {"final_response": text, "messages": [AIMessage(content=text)]}


async def supervisor_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = _last_user_text(state)
    routed = await _llm_route(text) or _heuristic_route(text)

    intent: Intent = routed.get("intent", "product_search")
    if intent not in {
        "product_search",
        "compatibility",
        "installation",
        "troubleshooting",
        "clarification",
    }:
        intent = "product_search"

    ps_number = routed.get("ps_number") or state.get("ps_number")
    model_number = routed.get("model_number") or state.get("model_number")

    lowered = text.lower()
    if re.search(r"\b(this|that)\s+part\b", lowered) and any(
        w in lowered for w in ("compatible", "fit", "work with")
    ):
        intent = "compatibility"

    return {
        "intent": intent,
        "ps_number": ps_number,
        "model_number": model_number,
        "appliance_type": routed.get("appliance_type") or state.get("appliance_type"),
        "brand": routed.get("brand") or state.get("brand"),
    }


async def clarification_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = (
        "I need a bit more to help — share a PartSelect part number (PS…), "
        "your appliance model number, or describe what's going wrong."
    )
    return {"final_response": text, "messages": [AIMessage(content=text)]}


def needs_clarification(state: AgentState) -> bool:
    intent = state.get("intent")
    ps = state.get("ps_number")
    model = state.get("model_number")
    return intent == "compatibility" and (not ps or not model)


async def _gather_support_context(
    state: AgentState,
    session,
    text: str,
    payload: dict[str, object],
    allowed: set[str],
) -> None:
    """Non-transactional catalog context (compatibility, install, troubleshooting)."""
    ps = state.get("ps_number")
    model = state.get("model_number")

    if ps and model:
        compat = await catalog_svc.check_compatibility(
            session, ps_number=ps, model_number=model
        )
        payload["compatibility"] = compat.model_dump()
        allowed.add(compat.ps_number)

    if ps and state.get("intent") == "installation":
        guide = await catalog_svc.get_installation_guide(
            session, ps_number=ps, query=text, limit=3
        )
        if guide:
            payload["installation"] = guide.model_dump()
            allowed.add(guide.ps_number)

    if state.get("intent") == "troubleshooting":
        diagnosis = await catalog_svc.diagnose_symptom(
            session,
            symptom=text,
            appliance_type=state.get("appliance_type"),
            brand=state.get("brand"),
        )
        if diagnosis.candidate_parts:
            payload["diagnosis"] = diagnosis.model_dump()
            allowed.update(c.ps_number for c in diagnosis.candidate_parts)

    docs = await retrieval_svc.search_documents(session, query=text, limit=5)
    other_docs = [d for d in docs if d.doc_type != "install_guide"]
    if other_docs:
        payload["documents"] = [d.model_dump() for d in other_docs]


async def transactional_tools_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Execute mandatory transactional tools; never let the LLM guess inventory or pricing."""
    session = config["configurable"]["session"]
    text = _last_user_text(state)

    phase_raw = state.get("transaction_phase") or TransactionPhase.SEARCHING
    machine = TransactionStateMachine(phase_raw)

    tool_results: dict[str, object] = dict(state.get("tool_results") or {})
    purchase_handoffs: list[dict[str, object]] = list(state.get("purchase_handoffs") or [])
    allowed: set[str] = set(state.get("allowed_ps_numbers") or [])
    identified_part_id = state.get("identified_part_id")
    catalog_grounded = True

    for call in plan_transactional_tools(state):
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


async def worker_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Alias for transactional tool execution (tool-first architecture)."""
    return await transactional_tools_node(state, config)


async def composer_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = _last_user_text(state)
    tool_payload = state.get("tool_payload") or {}

    if state.get("catalog_grounded") is False:
        tr = state.get("tool_results") or {}
        details = tr.get("get_part_details")
        if isinstance(details, dict) and details.get("found") is False:
            return {"final_response": "I cannot find that part in our catalog."}
        search = tr.get("search_parts")
        if (
            isinstance(search, dict)
            and search.get("found") is False
            and state.get("intent") in {"product_search", "transaction"}
        ):
            return {
                "final_response": "I cannot find that part in our catalog. "
                "Try a PS number or describe your refrigerator/dishwasher issue."
            }

    if not is_llm_configured():
        return {"final_response": _LLM_UNAVAILABLE}

    model = get_chat_model(streaming=False)
    prompt = _prompt(
        "composer",
        tool_payload=json.dumps(tool_payload, indent=2),
        user_message=text,
    )
    try:
        resp = await model.ainvoke(prompt)
        answer = resp.content if isinstance(resp.content, str) else str(resp.content)
        return {"final_response": answer}
    except Exception:  # noqa: BLE001
        return {
            "final_response": (
                "I couldn't reach the language model. Check ANTHROPIC_API_KEY and try again."
            )
        }


async def output_guardrail_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = state.get("final_response") or ""
    allowed = set(state.get("allowed_ps_numbers") or [])
    if state.get("ps_number"):
        allowed.add(state["ps_number"])

    tool_payload = state.get("tool_payload") or {}
    requires_safety = is_llm_configured() and bool(
        tool_payload.get("installation")
        or tool_payload.get("install_stories")
        or tool_payload.get("diagnosis")
    )
    verdict = validate_output(
        text,
        allowed_ps_numbers=allowed,
        requires_safety=requires_safety,
    )
    notes = list(state.get("guardrail_notes") or [])
    notes.append(verdict.reason)

    if not verdict.ok:
        safe = (
            "I couldn't verify all part numbers in that answer. "
            "Please ask again and I'll pull fresh catalog data."
        )
        return {
            "final_response": safe,
            "guardrail_notes": notes,
            "messages": [AIMessage(content=safe)],
        }

    final = verdict.sanitized_text or text
    return {
        "final_response": final,
        "guardrail_notes": notes,
        "messages": [AIMessage(content=final)],
    }
