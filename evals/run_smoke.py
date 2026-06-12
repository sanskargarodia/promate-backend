"""Run deterministic agent smoke evals (tool routing + guardrails)."""

from __future__ import annotations

import sys

from app.agents.tool_router import plan_transactional_tools
from app.guardrails.input import run_input_guardrails
from evals.cases import GUARDRAIL_CASES, SMOKE_CASES


def _check_tool_routing() -> list[str]:
    failures: list[str] = []
    for case in SMOKE_CASES:
        state = {"messages": [{"role": "user", "content": case.message}], **case.state}
        planned = [c.name for c in plan_transactional_tools(state)]
        if list(case.expected_tools) != planned:
            failures.append(
                f"{case.id}: expected tools {case.expected_tools}, got {tuple(planned)}"
            )
    return failures


def _check_guardrails() -> list[str]:
    failures: list[str] = []
    for case in GUARDRAIL_CASES:
        verdict = run_input_guardrails(case.message)
        if verdict.in_scope != case.in_scope:
            failures.append(
                f"{case.id}: expected in_scope={case.in_scope}, got {verdict.in_scope}"
            )
    return failures


def main() -> int:
    failures = _check_tool_routing() + _check_guardrails()
    if failures:
        print("SMOKE EVAL FAILED")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(f"SMOKE EVAL PASSED ({len(SMOKE_CASES)} routing + {len(GUARDRAIL_CASES)} guardrail cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
