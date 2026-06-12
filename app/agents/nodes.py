"""Graph node implementations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import RunnableConfig

from app.agents.state import AgentState, Intent
from app.core.config import is_llm_configured
from app.core.llm import get_chat_model, get_guardrail_model
from app.guardrails.input import run_input_guardrails
from app.guardrails.output import validate_output
from app.services import catalog as catalog_svc
from app.services import retrieval as retrieval_svc

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
    if intent in {"installation", "product_search"} and not ps:
        return True
    return intent == "compatibility" and (not ps or not model)


async def worker_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Gather catalog context from extracted entities — intent-agnostic."""
    session = config["configurable"]["session"]
    text = _last_user_text(state)
    ps = state.get("ps_number")
    model = state.get("model_number")

    payload: dict[str, object] = {}
    allowed: set[str] = set()

    parts = await catalog_svc.search_parts(
        session,
        query=text,
        appliance_type=state.get("appliance_type"),
        limit=8,
    )
    if parts:
        payload["matching_parts"] = [r.model_dump() for r in parts]
        allowed.update(r.ps_number for r in parts)

    if ps:
        part = await catalog_svc.get_part(session, ps)
        if part:
            payload["part"] = part.model_dump()
            allowed.add(ps)
        guide = await catalog_svc.get_installation_guide(
            session, ps_number=ps, query=text, limit=3
        )
        if guide:
            payload["installation"] = guide.model_dump()
            allowed.add(guide.ps_number)

    if ps and model:
        compat = await catalog_svc.check_compatibility(
            session, ps_number=ps, model_number=model
        )
        payload["compatibility"] = compat.model_dump()
        allowed.add(compat.ps_number)

    diagnosis = await catalog_svc.diagnose_symptom(
        session,
        symptom=text,
        appliance_type=state.get("appliance_type"),
        brand=state.get("brand"),
    )
    if diagnosis.candidate_parts:
        payload["diagnosis"] = diagnosis.model_dump()
        allowed.update(c.ps_number for c in diagnosis.candidate_parts)

    if not ps:
        install_hits = await retrieval_svc.search_documents(
            session,
            query=text,
            doc_type="install_guide",
            limit=5,
        )
        if install_hits:
            payload["install_stories"] = [d.model_dump() for d in install_hits]
            allowed.update(
                d.part_ps_number for d in install_hits if d.part_ps_number
            )

    docs = await retrieval_svc.search_documents(session, query=text, limit=5)
    other_docs = [d for d in docs if d.doc_type != "install_guide"]
    if other_docs:
        payload["documents"] = [d.model_dump() for d in other_docs]

    return {"tool_payload": payload, "allowed_ps_numbers": sorted(allowed)}


async def composer_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = _last_user_text(state)
    tool_payload = state.get("tool_payload") or {}

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
