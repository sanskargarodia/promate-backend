"""Conversation memory helpers — transcript and working query for multi-turn turns."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from app.agents.state import AgentState, Intent, SessionContext

PHYSICAL_SYMPTOM_SIGNALS = (
    "noise",
    "noisy",
    "rattling",
    "rattle",
    "sound",
    "humming",
    "buzzing",
    "grinding",
    "clicking",
    "not working",
    "won't",
    "wont",
    "broken",
    "leaking",
    "not cooling",
    "not draining",
    "no ice",
    "ice maker",
    "error",
    "vibrating",
)


def has_troubleshooting_minimum_context(state: AgentState) -> bool:
    """Enough appliance + symptom detail to run catalog search (not just meta-intent)."""
    ctx = get_session_context(state)
    text = build_working_query(state).lower()
    appliance = (
        state.get("appliance_type")
        or ctx.get("appliance_type")
        or _infer_appliance_from_text(text)
    )
    if not appliance:
        return False
    return any(signal in text for signal in PHYSICAL_SYMPTOM_SIGNALS)


def _infer_appliance_from_text(text: str) -> str | None:
    lowered = text.lower()
    if "dishwasher" in lowered:
        return "dishwasher"
    if "fridge" in lowered or "refrigerator" in lowered or "ice maker" in lowered:
        return "refrigerator"
    return None


def _message_text(msg: object) -> str:
    if isinstance(msg, HumanMessage):
        content = msg.content
        return content if isinstance(content, str) else str(content)
    if isinstance(msg, AIMessage):
        content = msg.content
        return content if isinstance(content, str) else str(content)
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    return str(msg)


def _message_role(msg: object) -> str | None:
    if isinstance(msg, HumanMessage):
        return "user"
    if isinstance(msg, AIMessage):
        return "assistant"
    if isinstance(msg, dict):
        role = msg.get("role")
        return str(role) if role else None
    return None


def format_recent_transcript(state: AgentState, *, max_turns: int = 6) -> str:
    """Format recent user/assistant turns for supervisor and composer prompts."""
    lines: list[str] = []
    for msg in state.get("messages") or []:
        role = _message_role(msg)
        text = _message_text(msg).strip()
        if not role or not text:
            continue
        label = "Customer" if role == "user" else "Assistant"
        lines.append(f"{label}: {text}")

    if not lines:
        return "(No prior conversation.)"

    if len(lines) > max_turns * 2:
        lines = lines[-(max_turns * 2):]
    return "\n".join(lines)


def get_session_context(state: AgentState) -> SessionContext:
    raw = state.get("session_context") or {}
    return SessionContext(
        active_intent=raw.get("active_intent"),
        symptom_summary=raw.get("symptom_summary"),
        appliance_type=raw.get("appliance_type"),
        brand=raw.get("brand"),
        ps_number=raw.get("ps_number"),
        model_number=raw.get("model_number"),
    )


def format_session_context(state: AgentState) -> str:
    ctx = get_session_context(state)
    parts: list[str] = []
    if ctx.get("active_intent"):
        parts.append(f"active_intent={ctx['active_intent']}")
    if ctx.get("appliance_type"):
        parts.append(f"appliance_type={ctx['appliance_type']}")
    if ctx.get("brand"):
        parts.append(f"brand={ctx['brand']}")
    if ctx.get("ps_number"):
        parts.append(f"ps_number={ctx['ps_number']}")
    if ctx.get("model_number"):
        parts.append(f"model_number={ctx['model_number']}")
    if ctx.get("symptom_summary"):
        parts.append(f"symptom_summary={ctx['symptom_summary']}")
    return ", ".join(parts) if parts else "(none yet)"


def build_working_query(state: AgentState) -> str:
    """Combine session context with the latest user message for search/RAG."""
    latest = ""
    for msg in reversed(state.get("messages") or []):
        if _message_role(msg) == "user":
            latest = _message_text(msg).strip()
            break

    ctx = get_session_context(state)
    chunks: list[str] = []
    if ctx.get("symptom_summary") and ctx["symptom_summary"] not in latest:
        chunks.append(ctx["symptom_summary"])
    if ctx.get("appliance_type") and ctx["appliance_type"] not in latest.lower():
        chunks.append(ctx["appliance_type"])
    if ctx.get("brand") and ctx["brand"].lower() not in latest.lower():
        chunks.append(ctx["brand"])
    if latest:
        chunks.append(latest)
    return " — ".join(chunks) if chunks else latest


def merge_session_context(
    state: AgentState,
    *,
    intent: Intent | None,
    ps_number: str | None,
    model_number: str | None,
    appliance_type: str | None,
    brand: str | None,
    latest_user_text: str,
) -> SessionContext:
    """Merge routed entities with prior session context across turns."""
    prior = get_session_context(state)
    merged: SessionContext = dict(prior)

    if intent and intent not in {"refusal", "clarification"}:
        if intent == "troubleshooting" or prior.get("active_intent") == "troubleshooting":
            merged["active_intent"] = "troubleshooting"
        else:
            merged["active_intent"] = intent
    elif intent:
        merged["active_intent"] = intent

    if ps_number:
        merged["ps_number"] = ps_number
    if model_number:
        merged["model_number"] = model_number
    if appliance_type:
        merged["appliance_type"] = appliance_type
    if brand:
        merged["brand"] = brand

    symptom = _extract_symptom(latest_user_text, intent)
    if symptom:
        if prior.get("symptom_summary") and symptom not in prior["symptom_summary"]:
            merged["symptom_summary"] = f"{prior['symptom_summary']}; {symptom}"
        else:
            merged["symptom_summary"] = symptom
    elif prior.get("symptom_summary") and _looks_like_diagnosis_intent(latest_user_text, intent):
        merged["symptom_summary"] = prior["symptom_summary"]

    return merged


def _looks_like_diagnosis_intent(text: str, intent: Intent | None) -> bool:
    lowered = text.lower()
    return intent == "troubleshooting" or any(
        term in lowered
        for term in ("diagnose", "diagnosis", "help me", "what's wrong", "what is wrong")
    )


def _extract_symptom(text: str, intent: Intent | None) -> str | None:
    lowered = text.lower().strip()
    if not lowered:
        return None
    if intent == "troubleshooting" or any(
        term in lowered
        for term in (
            "not working",
            "won't",
            "wont",
            "broken",
            "leaking",
            "noisy",
            "noise",
            "rattling",
            "diagnose",
            "diagnosis",
            "fix",
            "problem",
        )
    ):
        return text.strip()
    return None


def is_vague_troubleshooting(state: AgentState) -> bool:
    """True when troubleshooting still lacks appliance or a searchable symptom."""
    ctx = get_session_context(state)
    active = state.get("intent") or ctx.get("active_intent")
    if active != "troubleshooting":
        return False

    if has_troubleshooting_minimum_context(state):
        return False

    symptom = (ctx.get("symptom_summary")
               or build_working_query(state)).lower()
    meta_only = any(
        term in symptom
        for term in (
            "help me",
            "diafnose",
            "diagnose",
            "diagnosis",
            "the problem",
            "something wrong",
        )
    )
    appliance = (
        state.get("appliance_type")
        or ctx.get("appliance_type")
        or _infer_appliance_from_text(build_working_query(state))
    )
    if not appliance:
        return True
    return meta_only
