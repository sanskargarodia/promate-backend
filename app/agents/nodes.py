"""Graph node implementations."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import RunnableConfig

from app.agents.state import AgentState, Intent
from app.core.llm import get_chat_model, get_guardrail_model
from app.guardrails.input import run_input_guardrails
from app.guardrails.output import validate_output
from app.services import catalog as catalog_svc
from app.services import retrieval as retrieval_svc

PS_RE = re.compile(r"\b(PS\d+)\b", re.I)
MODEL_RE = re.compile(r"\b([A-Z]{2,}\d{3,}[A-Z0-9]*)\b")


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
    from app.core.config import settings

    if not settings.anthropic_api_key:
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

    return {
        "intent": intent,
        "ps_number": routed.get("ps_number"),
        "model_number": routed.get("model_number"),
        "appliance_type": routed.get("appliance_type"),
        "brand": routed.get("brand"),
    }


async def clarification_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    intent = state.get("intent")
    if intent == "compatibility":
        text = (
            "To check compatibility I need both the part number (e.g. PS11752778) "
            "and your appliance model number (e.g. WDT780SAEM1). Which are you looking at?"
        )
    elif intent == "installation":
        text = "Which part number would you like installation steps for? (Example: PS11752778)"
    else:
        text = (
            "I can help with refrigerator and dishwasher parts — could you share a part number "
            "or describe the symptom and appliance brand?"
        )
    return {"final_response": text, "messages": [AIMessage(content=text)]}


def _needs_clarification(state: AgentState) -> bool:
    intent = state.get("intent")
    ps = state.get("ps_number")
    model = state.get("model_number")
    if intent in {"installation", "product_search"} and not ps:
        return True
    return intent == "compatibility" and (not ps or not model)


async def worker_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    session = config["configurable"]["session"]
    intent = state.get("intent", "product_search")
    text = _last_user_text(state)
    payload: dict[str, object] = {"intent": intent}
    allowed: set[str] = set()

    if intent == "product_search":
        results = await catalog_svc.search_parts(
            session,
            query=text,
            appliance_type=state.get("appliance_type"),
        )
        payload["parts"] = [r.model_dump() for r in results]
        allowed.update(r.ps_number for r in results)

    elif intent == "compatibility":
        ps = state.get("ps_number") or ""
        model = state.get("model_number") or ""
        result = await catalog_svc.check_compatibility(session, ps_number=ps, model_number=model)
        payload["compatibility"] = result.model_dump()
        allowed.add(result.ps_number)

    elif intent == "installation":
        ps = state.get("ps_number") or ""
        guide = await catalog_svc.get_installation_guide(session, ps_number=ps)
        if guide:
            payload["installation"] = guide.model_dump()
            allowed.add(guide.ps_number)
        docs = await retrieval_svc.search_documents(
            session, query=text, doc_type="install_guide", part_ps_number=ps, limit=3
        )
        payload["documents"] = [d.model_dump() for d in docs]

    elif intent == "troubleshooting":
        symptom = text
        diagnosis = await catalog_svc.diagnose_symptom(
            session,
            symptom=symptom,
            appliance_type=state.get("appliance_type"),
            brand=state.get("brand"),
        )
        payload["diagnosis"] = diagnosis.model_dump()
        allowed.update(c.ps_number for c in diagnosis.candidate_parts)
        docs = await retrieval_svc.search_documents(
            session, query=symptom, doc_type="troubleshooting", limit=4
        )
        payload["documents"] = [d.model_dump() for d in docs]

    return {"tool_payload": payload, "allowed_ps_numbers": sorted(allowed)}


async def composer_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = _last_user_text(state)
    tool_payload = state.get("tool_payload") or {}
    intent = state.get("intent", "product_search")

    from app.core.config import settings

    if settings.anthropic_api_key:
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
            pass

    # Template fallback when LLM unavailable.
    if intent == "compatibility" and "compatibility" in tool_payload:
        comp = tool_payload["compatibility"]
        if isinstance(comp, dict):
            answer = comp.get("message", "Compatibility could not be determined.")
            return {"final_response": str(answer)}

    if intent == "installation" and "installation" in tool_payload:
        guide = tool_payload["installation"]
        if isinstance(guide, dict):
            steps = guide.get("steps") or []
            lines = [
                f"Installation for {guide.get('part_name', 'part')} ({guide.get('ps_number')}):"
            ]
            for step in steps:
                if isinstance(step, dict):
                    lines.append(f"{step.get('order', '?')}. {step.get('text', '')}")
            if guide.get("video_url"):
                lines.append(f"Video: {guide['video_url']}")
            lines.append(
                "Unplug the appliance and shut off the water supply before servicing, "
                "when applicable."
            )
            return {"final_response": "\n".join(lines)}

    if intent == "troubleshooting" and "diagnosis" in tool_payload:
        diag = tool_payload["diagnosis"]
        if isinstance(diag, dict):
            parts = diag.get("candidate_parts") or []
            if not parts:
                return {
                    "final_response": (
                        "I couldn't match parts for that symptom yet. "
                        "Try adding your appliance brand or model number."
                    )
                }
            lines = ["Based on your symptom, these parts may help:"]
            for p in parts[:5]:
                if isinstance(p, dict):
                    lines.append(f"- {p.get('ps_number')}: {p.get('name')}")
            return {"final_response": "\n".join(lines)}

    if "parts" in tool_payload:
        parts = tool_payload["parts"]
        if isinstance(parts, list) and parts:
            lines = ["Here are matching parts:"]
            for p in parts[:5]:
                if isinstance(p, dict):
                    price = p.get("price_cents")
                    price_str = f"${price / 100:.2f}" if price else "price unavailable"
                    lines.append(f"- {p.get('ps_number')}: {p.get('name')} ({price_str})")
            return {"final_response": "\n".join(lines)}

    return {
        "final_response": (
            "I found some catalog data but need a bit more detail. "
            "Share a part number (PS…) or appliance model if you have one."
        )
    }


async def output_guardrail_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    _ = config
    text = state.get("final_response") or ""
    allowed = set(state.get("allowed_ps_numbers") or [])
    if state.get("ps_number"):
        allowed.add(state["ps_number"])

    requires_safety = state.get("intent") in {"installation", "troubleshooting"}
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
