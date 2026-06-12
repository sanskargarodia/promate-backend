"""Deterministic smoke tests for canonical demo flows."""

import pytest

from app.agents.tool_router import plan_transactional_tools
from app.guardrails.input import run_input_guardrails
from evals.cases import GUARDRAIL_CASES, SMOKE_CASES


@pytest.mark.parametrize("case", SMOKE_CASES, ids=lambda c: c.id)
def test_demo_tool_routing(case) -> None:
    state = {"messages": [{"role": "user", "content": case.message}], **case.state}
    planned = [c.name for c in plan_transactional_tools(state)]
    assert planned == list(case.expected_tools)


@pytest.mark.parametrize("case", GUARDRAIL_CASES, ids=lambda c: c.id)
def test_demo_guardrails(case) -> None:
    verdict = run_input_guardrails(case.message)
    assert verdict.in_scope == case.in_scope
