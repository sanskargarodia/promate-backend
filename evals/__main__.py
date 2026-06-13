"""Eval package entrypoint.

Usage:
  uv run python -m evals              # smoke (routing + guardrails, no API key)
  uv run python -m evals trajectory   # full dataset routing trajectory
  uv run python -m evals trajectory --graph  # + DB graph tool execution
  uv run python -m evals live --canonical    # live E2E (API key + DB)
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    command = args[0] if args else "smoke"
    rest = args[1:] if len(args) > 1 else []

    if command in {"smoke", "routing"}:
        from evals.run_smoke import main as smoke_main

        return smoke_main()

    if command == "trajectory":
        from evals.run_trajectory import main as trajectory_main

        return trajectory_main(rest)

    if command == "live":
        from evals.run_live import main as live_main

        return live_main(rest)

    print(f"Unknown eval command: {command}")
    print("Commands: smoke (default), trajectory, live")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
