"""Graph node implementations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import RunnableConfig

from app.agents.conversation import (
    build_working_query,
    format_recent_transcript,
    format_session_context,
    get_session_context,
    has_troubleshooting_minimum_context,
    is_vague_troubleshooting,
    merge_session_context,
)
from app.agents.follow_ups import generate_suggested_follow_ups
from app.agents.grounding import grounded_ps_numbers, ps_numbers_in_text
from app.agents.state import AgentState, Intent
from app.agents.status import NODE_STATUS, SUPPORT_STATUS, emit_status
from app.agents.tool_router import detect_purchase_intent
from app.core.config import is_llm_configured
from app.core.llm import get_chat_model, get_guardrail_model
from app.guardrails.input import run_input_guardrails
from app.guardrails.output import validate_output
from app.guardrails.refusal import RefusalCode, refusal_context, refusal_fallback
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


def _heuristic_route(text: str, state: AgentState | None = None) -> dict[str, Any]:
    lowered = text.lower()
    ps_match = PS_RE.search(text)
    model_match = None
    for candidate in MODEL_RE.finditer(text):
        token = candidate.group(1).upper()
        if not token.startswith("PS"):
            model_match = candidate
            break

    intent: Intent = "product_search"
    if detect_purchase_intent(text):
        intent = "transaction"
    elif "install" in lowered or "how do i replace" in lowered or "how to replace" in lowered:
        intent = "installation"
    elif any(
        w in lowered
        for w in (
            "compatible",
            "compatibility",
            "fit my",
            "fit model",
            "work with my",
            "fit with",
        )
    ):
        intent = "compatibility"
    elif model_match and re.search(r"\bfit\b", lowered):
        intent = "compatibility"
    elif any(
        w in lowered
        for w in (
            "diagnose",
            "diafnose",
            "diagnos",
            "not working",
            "won't",
            "wont",
            "fix",
            "broken",
            "leaking",
            "noisy",
            "noise",
            "rattling",
            "help me",
        )
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

    ps_number = ps_match.group(1).upper() if ps_match else None
    model_number = model_match.group(1).upper() if model_match else None
    if state:
        ps_number = ps_number or state.get("ps_number") or (
            state.get("session_context") or {}).get("ps_number")
        model_number = model_number or state.get("model_number") or (
            state.get("session_context") or {}).get("model_number")
        appliance_type = appliance_type or state.get("appliance_type") or (
            state.get("session_context") or {}).get("appliance_type")
        brand = brand or state.get("brand") or (
            state.get("session_context") or {}).get("brand")
        if (state.get("session_context") or {}).get("active_intent") == "troubleshooting" and intent == "product_search":
            intent = "troubleshooting"

    return {
        "intent": intent,
        "ps_number": ps_number,
        "model_number": model_number,
        "appliance_type": appliance_type,
        "brand": brand,
    }


def _merge_route_results(
    llm: dict[str, Any] | None,
    heuristic: dict[str, Any],
    *,
    state: AgentState,
) -> dict[str, Any]:
    """Combine LLM classification with deterministic extraction."""
    merged = dict(heuristic)
    if not llm:
        return merged

    for key in ("intent", "ps_number", "model_number", "appliance_type", "brand"):
        value = llm.get(key)
        if value is not None and value != "":
            merged[key] = value

    prior_intent = (state.get("session_context") or {}).get("active_intent")
    if heuristic.get("intent") == "troubleshooting" and merged.get("intent") in {
        "product_search",
        "clarification",
    }:
        merged["intent"] = "troubleshooting"
    elif prior_intent == "troubleshooting" and merged.get("intent") == "product_search":
        merged["intent"] = "troubleshooting"

    for key in ("appliance_type", "brand", "ps_number", "model_number"):
        if not merged.get(key) and heuristic.get(key):
            merged[key] = heuristic[key]

    return merged


async def _llm_route(state: AgentState, text: str) -> dict[str, Any] | None:
    if not is_llm_configured():
        return None

    model = get_guardrail_model()
    prompt = _prompt(
        "supervisor",
        user_message=text,
        conversation_history=format_recent_transcript(state),
        session_context=format_session_context(state),
    )
    try:
        resp = await model.ainvoke(prompt)
        content = resp.content if isinstance(
            resp.content, str) else str(resp.content)
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start: end + 1])
    except Exception:  # noqa: BLE001
        return None
    return None


async def input_guardrail_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["input_guardrail"])
    text = _last_user_text(state)
    verdict = run_input_guardrails(text)
    notes = [verdict.reason]
    if not verdict.in_scope or verdict.injection_detected:
        payload: dict[str, Any] = {
            "refused": True,
            "intent": "refusal",
            "guardrail_notes": notes,
        }
        if verdict.refusal_code:
            payload["refusal_code"] = verdict.refusal_code
        return payload
    return {"refused": False, "guardrail_notes": notes}


async def _compose_refusal(user_message: str, code: RefusalCode) -> str:
    if not is_llm_configured():
        return refusal_fallback(code)

    model = get_guardrail_model(max_tokens=256)
    prompt = _prompt(
        "refusal",
        user_message=user_message,
        refusal_context=refusal_context(code),
    )
    try:
        resp = await model.ainvoke(prompt)
        answer = resp.content if isinstance(
            resp.content, str) else str(resp.content)
        answer = answer.strip()
        return answer or refusal_fallback(code)
    except Exception:  # noqa: BLE001
        return refusal_fallback(code)


async def refusal_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["refusal"])
    user_message = _last_user_text(state)
    code: RefusalCode = state.get("refusal_code") or "unclear_scope"
    text = await _compose_refusal(user_message, code)
    return {"final_response": text, "messages": [AIMessage(content=text)]}


async def supervisor_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["supervisor"])
    text = _last_user_text(state)
    working_query = build_working_query(state)
    heuristic_routed = _heuristic_route(working_query or text, state)
    llm_routed = await _llm_route(state, text)
    routed = _merge_route_results(llm_routed, heuristic_routed, state=state)

    intent: Intent = routed.get("intent", "product_search")
    if intent not in {
        "product_search",
        "compatibility",
        "installation",
        "troubleshooting",
        "clarification",
        "transaction",
    }:
        intent = "product_search"

    ps_number = routed.get("ps_number") or state.get("ps_number")
    model_number = routed.get("model_number") or state.get("model_number")
    appliance_type = routed.get(
        "appliance_type") or state.get("appliance_type")
    brand = routed.get("brand") or state.get("brand")

    lowered = text.lower()
    if re.search(r"\b(this|that)\s+part\b", lowered) and any(
        w in lowered for w in ("compatible", "fit", "work with")
    ):
        intent = "compatibility"
        prior_ps = (state.get("session_context") or {}).get(
            "ps_number") or state.get("identified_part_id")
        if prior_ps and not ps_number:
            ps_number = prior_ps

    session_context = merge_session_context(
        state,
        intent=intent,
        ps_number=ps_number,
        model_number=model_number,
        appliance_type=appliance_type,
        brand=brand,
        latest_user_text=text,
    )

    return {
        "intent": intent,
        "ps_number": session_context.get("ps_number") or ps_number,
        "model_number": session_context.get("model_number") or model_number,
        "appliance_type": session_context.get("appliance_type") or appliance_type,
        "brand": session_context.get("brand") or brand,
        "session_context": session_context,
    }


async def clarification_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["clarification"])
    intent = state.get("intent")
    if intent == "compatibility":
        text = (
            "To check fitment I need both the PartSelect part number (PS…) and your "
            "appliance model number. What model is this part for?"
        )
    elif intent == "installation" and not state.get("ps_number"):
        text = (
            "I can walk you through installation — which PartSelect part number (PS…) "
            "are you installing?"
        )
    elif intent == "troubleshooting" or is_vague_troubleshooting(state):
        ctx = get_session_context(state)
        appliance = state.get("appliance_type") or ctx.get("appliance_type")
        if appliance and not has_troubleshooting_minimum_context(state):
            text = (
                f"Got it — a {appliance}. Can you describe the symptom more specifically? "
                "For example not cooling, leaking, won't drain, ice maker not working, "
                "or what kind of noise you're hearing."
            )
        else:
            text = (
                "I can help narrow down the right part. What appliance is this for, and "
                "what exactly is going wrong — for example not cooling, leaking, won't drain, "
                "or a specific noise?"
            )
    else:
        text = (
            "I need a bit more to help — share a PartSelect part number (PS…), "
            "your appliance model number, or describe what's going wrong."
        )
    return {"final_response": text, "messages": [AIMessage(content=text)]}


def needs_clarification(state: AgentState) -> bool:
    intent = state.get("intent")
    ps = state.get("ps_number")
    model = state.get("model_number")
    if intent == "clarification":
        return True
    if intent == "compatibility" and (not ps or not model):
        return True
    if intent == "installation" and not ps:
        return True
    if intent == "troubleshooting" and is_vague_troubleshooting(state):
        return True
    return False


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
    intent = state.get("intent")
    working_query = build_working_query(state) or text

    if intent == "compatibility" and ps and model:
        emit_status(SUPPORT_STATUS["compatibility"])
        compat = await catalog_svc.check_compatibility(
            session, ps_number=ps, model_number=model
        )
        payload["compatibility"] = compat.model_dump()
        allowed.add(compat.ps_number)

    if intent == "installation" and ps:
        emit_status(SUPPORT_STATUS["installation"])
        guide = await catalog_svc.get_installation_guide(
            session, ps_number=ps, query=working_query, limit=3
        )
        if guide:
            payload["installation"] = guide.model_dump()
            allowed.add(guide.ps_number)

    if intent == "troubleshooting":
        emit_status(SUPPORT_STATUS["diagnosis"])
        diagnosis = await catalog_svc.diagnose_symptom(
            session,
            symptom=working_query,
            appliance_type=state.get("appliance_type"),
            brand=state.get("brand"),
        )
        if diagnosis.candidate_parts:
            payload["diagnosis"] = diagnosis.model_dump()
            allowed.update(c.ps_number for c in diagnosis.candidate_parts)

    emit_status(SUPPORT_STATUS["documents"])
    docs = await retrieval_svc.search_documents(session, query=working_query, limit=5)
    other_docs = [d for d in docs if d.doc_type != "install_guide"]
    if other_docs:
        payload["documents"] = [d.model_dump() for d in other_docs]
        for doc in other_docs:
            if doc.part_ps_number:
                allowed.add(doc.part_ps_number.upper())
            allowed.update(ps_numbers_in_text(doc.content))


async def suggest_follow_ups_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["suggest_follow_ups"])
    return {"suggested_follow_ups": await generate_suggested_follow_ups(state)}


async def _invoke_composer(state: AgentState) -> str:
    text = _last_user_text(state)
    tool_payload = state.get("tool_payload") or {}
    prompt = _prompt(
        "composer",
        tool_payload=json.dumps(tool_payload, indent=2),
        user_message=text,
        conversation_history=format_recent_transcript(state),
    )
    resp = await get_chat_model(streaming=False).ainvoke(prompt)
    return resp.content if isinstance(resp.content, str) else str(resp.content)


async def composer_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["composer"])
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
                "Try a PS number or describe the symptom you're seeing."
            }

    if not is_llm_configured():
        return {"final_response": _LLM_UNAVAILABLE}

    try:
        answer = await _invoke_composer(state)
        return {"final_response": answer}
    except Exception:  # noqa: BLE001
        return {
            "final_response": (
                "I couldn't reach the language model. Check ANTHROPIC_API_KEY and try again."
            )
        }


async def output_guardrail_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    emit_status(NODE_STATUS["output_guardrail"])
    text = state.get("final_response") or ""
    allowed = grounded_ps_numbers(
        tool_payload=state.get("tool_payload") or {},
        tool_results=state.get("tool_results") or {},
        extra=set(state.get("allowed_ps_numbers") or []),
    )
    if state.get("ps_number"):
        allowed.add(state["ps_number"].upper())

    verdict = validate_output(
        text,
        allowed_ps_numbers=allowed,
    )
    notes = list(state.get("guardrail_notes") or [])
    notes.append(verdict.reason)

    if not verdict.ok:
        if is_llm_configured():
            try:
                retry_text = await _invoke_composer(state)
                retry_verdict = validate_output(
                    retry_text, allowed_ps_numbers=allowed)
                notes.append(retry_verdict.reason)
                if retry_verdict.ok:
                    final = retry_verdict.sanitized_text or retry_text
                    return {
                        "final_response": final,
                        "guardrail_notes": notes,
                        "messages": [AIMessage(content=final)],
                    }
                if retry_verdict.sanitized_text:
                    return {
                        "final_response": retry_verdict.sanitized_text,
                        "guardrail_notes": notes,
                        "messages": [AIMessage(content=retry_verdict.sanitized_text)],
                    }
            except Exception:  # noqa: BLE001
                pass

        safe = (
            "I want to give you accurate, catalog-backed help. "
            "Can you share your appliance model or describe the symptom in a bit more detail?"
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
