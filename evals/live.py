"""Live end-to-end eval — full agent turn with DB + Anthropic API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.agents.run import run_agent_turn
from app.core.config import is_llm_configured
from evals.judge import heuristic_checks, judge_response
from evals.schema import EvalCase


@dataclass
class LiveResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    response: str = ""
    judge_pass: bool | None = None
    events: list[dict[str, Any]] = field(default_factory=list)


async def _collect_turn_events(
    *,
    message: str,
    session: Any,
    thread_id: str,
) -> tuple[list[dict[str, Any]], str]:
    events: list[dict[str, Any]] = []
    response_parts: list[str] = []
    async for event in run_agent_turn(message=message, session=session, thread_id=thread_id):
        events.append(event)
        if event.get("type") == "token":
            response_parts.append(str(event.get("content", "")))
    return events, "".join(response_parts).strip()


async def run_live_case(case: EvalCase, session: Any, *, use_judge: bool = True) -> LiveResult:
    result = LiveResult(case_id=case.id, passed=True)
    thread_id = f"live-{case.id}-{uuid4().hex[:8]}"

    if case.is_multi_turn and case.turns:
        events: list[dict[str, Any]] = []
        response = ""
        for turn in case.turns:
            events, response = await _collect_turn_events(
                message=turn, session=session, thread_id=thread_id,
            )
    else:
        message = case.primary_message()
        events, response = await _collect_turn_events(
            message=message, session=session, thread_id=thread_id,
        )

    result.events = events
    result.response = response
    result.failures = heuristic_checks(case, response, events)

    if result.failures:
        result.passed = False

    if use_judge and is_llm_configured() and result.passed:
        verdict = await judge_response(case, response)
        if verdict is not None:
            result.judge_pass = verdict.pass_
            if not verdict.pass_:
                result.passed = False
                result.failures.append(f"judge: {verdict.reason}")

    return result


async def run_live_suite(
    cases: list[EvalCase],
    session: Any,
    *,
    use_judge: bool = True,
) -> list[LiveResult]:
    return [await run_live_case(case, session, use_judge=use_judge) for case in cases]
