"""Live end-to-end eval CLI — full agent turn with DB + Anthropic API."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import is_llm_configured
from app.core.db import SessionLocal
from evals.loader import load_live_cases
from evals.live import run_live_suite


def _configure_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

def _print_results(results: list) -> list[str]:
    failures: list[str] = []
    passed = 0
    for result in results:
        if result.passed:
            passed += 1
            judge_note = ""
            if result.judge_pass is not None:
                judge_note = f" (judge={'pass' if result.judge_pass else 'fail'})"
            print(f"  OK  {result.case_id}{judge_note}")
        else:
            print(f"  FAIL {result.case_id}")
            for failure in result.failures:
                failures.append(f"{result.case_id}: {failure}")
                print(f"       - {failure}")
    print(f"Live eval: {passed}/{len(results)} passed")
    return failures


async def _run(*, canonical_only: bool, no_judge: bool) -> int:
    if not is_llm_configured():
        print("ANTHROPIC_API_KEY not set — live eval requires the composer LLM.")
        return 2

    cases = load_live_cases(canonical_only=canonical_only)
    async with SessionLocal() as session:
        results = await run_live_suite(
            cases,
            session,
            use_judge=not no_judge,
        )

    failures = _print_results(results)
    if failures:
        print("LIVE EVAL FAILED")
        return 1
    print(f"LIVE EVAL PASSED ({len(cases)} cases)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run live E2E agent evals")
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="Run only the six canonical demo prompts",
    )
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="Skip LLM-as-judge scoring (heuristic checks only)",
    )
    args = parser.parse_args(argv)
    _configure_event_loop()
    return asyncio.run(_run(canonical_only=args.canonical, no_judge=args.no_judge))


if __name__ == "__main__":
    sys.exit(main())
