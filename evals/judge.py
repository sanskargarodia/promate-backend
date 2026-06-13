"""LLM-as-judge scoring for live eval responses (stretch layer)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.core.config import is_llm_configured
from app.core.llm import get_guardrail_model
from evals.schema import EvalCase

JUDGE_PROMPT = """You are an evaluation judge for a PartSelect appliance-parts chat agent.
Score the assistant response on three criteria (1-5 scale, 5 is best):
- groundedness: uses only catalog-backed facts, no invented part numbers or prices
- helpfulness: addresses the user's question directly
- tone: polite, professional, appropriate for customer support

User message:
{user_message}

Assistant response:
{assistant_response}

Return ONLY JSON: {{"groundedness": N, "helpfulness": N, "tone": N, "pass": true/false, "reason": "..."}}
Set pass=true only if all scores are >= 3 and no fabricated catalog facts are present."""


@dataclass(frozen=True)
class JudgeVerdict:
    groundedness: int
    helpfulness: int
    tone: int
    pass_: bool
    reason: str


def _parse_judge_json(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


async def judge_response(case: EvalCase, response: str) -> JudgeVerdict | None:
    """Score a live response with Haiku. Returns None if LLM unavailable."""
    if not is_llm_configured() or not response.strip():
        return None

    message = case.routing_message()
    prompt = JUDGE_PROMPT.format(user_message=message, assistant_response=response)
    model = get_guardrail_model(max_tokens=512)
    try:
        resp = await model.ainvoke(prompt)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        parsed = _parse_judge_json(content)
        if not parsed:
            return None
        return JudgeVerdict(
            groundedness=int(parsed.get("groundedness", 0)),
            helpfulness=int(parsed.get("helpfulness", 0)),
            tone=int(parsed.get("tone", 0)),
            pass_=bool(parsed.get("pass", False)),
            reason=str(parsed.get("reason", "")),
        )
    except Exception:  # noqa: BLE001
        return None


def heuristic_checks(case: EvalCase, response: str, events: list[dict]) -> list[str]:
    """Deterministic post-run checks before/alongside LLM judge."""
    failures: list[str] = []
    lowered = response.lower()

    for needle in case.expect_contains:
        if needle.lower() not in lowered:
            failures.append(f"response missing expected substring: {needle}")

    for needle in case.expect_not_contains:
        if needle.lower() in lowered:
            failures.append(f"response contains forbidden substring: {needle}")

    event_types = [e.get("type") for e in events]
    for expected in case.expect_events:
        if expected not in event_types:
            failures.append(f"missing SSE event: {expected}")

    if case.expect_grounding_failure:
        if "cannot find" not in lowered:
            failures.append("expected grounding failure message")
    elif case.expects_handoff() and "purchase_handoff" not in event_types:
        failures.append("expected purchase_handoff event")

    return failures
