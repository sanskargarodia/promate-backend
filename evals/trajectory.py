"""Trajectory evaluation — routing, clarification path, and optional graph tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage

from app.agents.conversation import build_working_query, merge_session_context
from app.agents.nodes import (
    _heuristic_route,
    _merge_route_results,
    input_guardrail_node,
    needs_clarification,
)
from app.agents.workers import transactional_tools_node
from app.agents.tool_router import plan_transactional_tools
from app.guardrails.input import run_input_guardrails
from evals.schema import EvalCase


@dataclass
class TrajectoryResult:
    case_id: str
    passed: bool
    failures: list[str] = field(default_factory=list)


def _build_state(case: EvalCase, message: str) -> dict[str, Any]:
    return {
        "messages": [{"role": "user", "content": message}],
        **case.state,
    }


def _build_graph_state(case: EvalCase) -> dict[str, Any]:
    """Initial graph state — full multi-turn transcript when provided."""
    if case.turns:
        messages = [HumanMessage(content=turn) for turn in case.turns]
    else:
        messages = [HumanMessage(content=case.primary_message())]
    return {"messages": messages, **case.state}


def _apply_heuristic_supervisor_state(state: dict[str, Any], message: str) -> dict[str, Any]:
    """Deterministic supervisor routing — no LLM (graph eval must stay fast/offline)."""
    working = build_working_query(state) or message
    heuristic = _heuristic_route(working, state)
    routed = _merge_route_results(None, heuristic, state=state)

    intent = routed.get("intent", "product_search")
    session_context = merge_session_context(
        state,
        intent=intent,
        ps_number=routed.get("ps_number"),
        model_number=routed.get("model_number"),
        appliance_type=routed.get("appliance_type"),
        brand=routed.get("brand"),
        latest_user_text=message,
    )

    return {
        **state,
        "intent": intent,
        "ps_number": session_context.get("ps_number") or routed.get("ps_number"),
        "model_number": session_context.get("model_number") or routed.get("model_number"),
        "appliance_type": session_context.get("appliance_type") or routed.get("appliance_type"),
        "brand": session_context.get("brand") or routed.get("brand"),
        "session_context": session_context,
    }


def _check_routing_case(case: EvalCase) -> TrajectoryResult:
    result = TrajectoryResult(case_id=case.id, passed=True)
    message = case.routing_message()

    if case.expect_refusal or not case.in_scope:
        verdict = run_input_guardrails(message)
        if verdict.in_scope != case.in_scope:
            result.failures.append(
                f"expected in_scope={case.in_scope}, got {verdict.in_scope}"
            )
        return result

    state = _build_state(case, message)
    working = build_working_query(state) or message
    heuristic = _heuristic_route(working, state)
    routed = _merge_route_results(None, heuristic, state=state)
    merged = {**state, **routed}

    if case.expect_intent and merged.get("intent") != case.expect_intent:
        result.failures.append(
            f"expected intent {case.expect_intent}, got {merged.get('intent')}"
        )

    if case.expect_clarification:
        if not needs_clarification(merged):
            result.failures.append("expected clarification path")
    elif needs_clarification(merged) and case.expect_tools:
        result.failures.append("unexpected clarification path")

    if case.expect_tools and not case.expect_clarification:
        planned = [call.name for call in plan_transactional_tools(merged)]
        if planned != case.expect_tools:
            result.failures.append(
                f"expected tools {case.expect_tools}, got {planned}"
            )

    if result.failures:
        result.passed = False
    return result


def run_routing_suite(cases: list[EvalCase]) -> list[TrajectoryResult]:
    return [_check_routing_case(case) for case in cases]


async def _run_graph_case(case: EvalCase, session: Any) -> TrajectoryResult:
    result = TrajectoryResult(case_id=case.id, passed=True)
    config: dict[str, Any] = {"configurable": {"session": session}}
    message = case.routing_message()
    state: dict[str, Any] = _build_graph_state(case)

    guard = await input_guardrail_node(state, config)
    state = {**state, **guard}

    if case.expect_refusal or not case.in_scope:
        if not guard.get("refused"):
            result.failures.append("expected refusal at input guardrail")
        if result.failures:
            result.passed = False
        return result

    if guard.get("refused"):
        result.failures.append("unexpected refusal at input guardrail")
        result.passed = False
        return result

    state = _apply_heuristic_supervisor_state(state, message)

    if case.expect_intent and state.get("intent") != case.expect_intent:
        result.failures.append(
            f"expected intent {case.expect_intent}, got {state.get('intent')}"
        )

    clarifies = needs_clarification(state)
    if case.expect_clarification:
        if not clarifies:
            result.failures.append("expected clarification path")
        if result.failures:
            result.passed = False
        return result

    if clarifies:
        result.failures.append("unexpected clarification path")
        result.passed = False
        return result

    if not case.expect_tools:
        if result.failures:
            result.passed = False
        return result

    txn = await transactional_tools_node(state, config)
    tool_results = txn.get("tool_results") or {}
    actual = list(tool_results.keys())
    for tool in case.expect_tools:
        if tool not in actual:
            result.failures.append(f"missing tool execution: {tool}")

    if result.failures:
        result.passed = False
    return result


async def run_graph_suite(
    cases: list[EvalCase],
    session: Any,
    *,
    verbose: bool = True,
) -> list[TrajectoryResult]:
    """Run graph through transactional_tools (DB required, no composer LLM)."""
    runnable = [
        case
        for case in cases
        if not case.expect_refusal
        and case.in_scope
        and not case.expect_clarification
        and case.expect_tools
    ]
    results: list[TrajectoryResult] = []
    for index, case in enumerate(runnable, start=1):
        if verbose:
            print(f"  graph [{index}/{len(runnable)}] {case.id}…", flush=True)
        results.append(await _run_graph_case(case, session))
    return results
