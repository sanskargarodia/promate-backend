"""Run deterministic agent smoke evals (tool routing)."""

from __future__ import annotations

import sys

from app.agents.tool_router import plan_transactional_tools
from evals.cases import SMOKE_CASES


def _check_tool_routing() -> list[str]:
    failures: list[str] = []
    for case in SMOKE_CASES:
        state = {"messages": [
            {"role": "user", "content": case.message}], **case.state}
        planned = [c.name for c in plan_transactional_tools(state)]
        if list(case.expected_tools) != planned:
            failures.append(
                f"{case.id}: expected tools {case.expected_tools}, got {tuple(planned)}"
            )
    return failures


def main() -> int:
    failures = _check_tool_routing()
    if failures:
        print("SMOKE EVAL FAILED")
        for line in failures:
            print(f"  - {line}")
        return 1
    print(f"SMOKE EVAL PASSED ({len(SMOKE_CASES)} routing cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
