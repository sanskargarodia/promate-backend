"""Deterministic smoke tests for canonical demo flows."""

import pytest

from app.agents.tool_router import plan_transactional_tools
from evals.cases import SMOKE_CASES


@pytest.mark.parametrize("case", SMOKE_CASES, ids=lambda c: c.id)
def test_demo_tool_routing(case) -> None:
    state = {"messages": [
        {"role": "user", "content": case.message}], **case.state}
    planned = [c.name for c in plan_transactional_tools(state)]
    assert planned == list(case.expected_tools)
