"""LLM-generated follow-up prompt suggestions after each agent reply."""

from __future__ import annotations

import json
from pathlib import Path

from app.agents.conversation import format_recent_transcript, format_session_context
from app.agents.state import AgentState
from app.core.config import is_llm_configured
from app.core.llm import get_guardrail_model

_MAX_SUGGESTIONS = 4
_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _prompt(name: str, **kwargs: str) -> str:
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8").format(**kwargs)


def _tool_context(state: AgentState) -> str:
    payload = {
        "intent": state.get("intent"),
        "ps_number": state.get("ps_number"),
        "model_number": state.get("model_number"),
        "appliance_type": state.get("appliance_type"),
        "brand": state.get("brand"),
        "identified_part_id": state.get("identified_part_id"),
        "transaction_phase": state.get("transaction_phase"),
        "tool_payload": state.get("tool_payload"),
        "purchase_handoffs": state.get("purchase_handoffs"),
        "refused": state.get("refused"),
    }
    return json.dumps(payload, indent=2, default=str)


def parse_follow_up_response(text: str, *, max_count: int = _MAX_SUGGESTIONS) -> list[str]:
    """Parse model output into deduped suggestion strings."""
    stripped = text.strip()
    if not stripped:
        return []

    candidates: list[str] = []
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(stripped[start:end + 1])
            if isinstance(parsed, list):
                candidates = [str(item).strip() for item in parsed]
        except json.JSONDecodeError:
            pass

    if not candidates:
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                raw = obj.get("prompts") or obj.get(
                    "suggestions") or obj.get("follow_ups")
                if isinstance(raw, list):
                    candidates = [str(item).strip() for item in raw]
        except json.JSONDecodeError:
            pass

    return _dedupe(candidates)[:max_count]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


async def generate_suggested_follow_ups(state: AgentState) -> list[str]:
    """Ask Haiku for contextual follow-up chips — empty when LLM unavailable."""
    if not is_llm_configured():
        return []

    assistant_response = (state.get("final_response") or "").strip()
    if not assistant_response:
        return []

    prompt = _prompt(
        "follow_ups",
        max_count=str(_MAX_SUGGESTIONS),
        session_context=format_session_context(state),
        tool_context=_tool_context(state),
        conversation_history=format_recent_transcript(state),
        assistant_response=assistant_response,
    )

    model = get_guardrail_model(max_tokens=512)
    try:
        resp = await model.ainvoke(prompt)
        content = resp.content if isinstance(
            resp.content, str) else str(resp.content)
        return parse_follow_up_response(content)
    except Exception:  # noqa: BLE001
        return []
