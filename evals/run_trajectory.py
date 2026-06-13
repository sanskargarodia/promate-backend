"""Trajectory eval CLI — routing + optional graph path."""

from __future__ import annotations

import asyncio
import sys

from app.core.db import SessionLocal
from evals.loader import load_trajectory_cases
from evals.trajectory import run_graph_suite, run_routing_suite


def _configure_event_loop() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _warm_embedder() -> None:
    """Load fastembed once so the first search_parts case does not look hung."""
    from app.core.embeddings import get_embedder

    embedder = get_embedder()
    await asyncio.to_thread(embedder.embed_query, "warmup")


def _print_results(label: str, results: list) -> list[str]:
    failures: list[str] = []
    for result in results:
        if not result.passed:
            for failure in result.failures:
                failures.append(f"{result.case_id}: {failure}")
    passed = sum(1 for result in results if result.passed)
    print(f"{label}: {passed}/{len(results)} passed")
    return failures


def _runnable_graph_count(cases: list) -> int:
    return sum(
        1
        for case in cases
        if not case.expect_refusal
        and case.in_scope
        and not case.expect_clarification
        and case.expect_tools
    )


async def _run_graph() -> list[str]:
    cases = load_trajectory_cases()
    runnable_count = _runnable_graph_count(cases)
    print(
        f"Graph trajectory: {runnable_count} DB cases (heuristic routing, no LLM)…",
        flush=True,
    )
    print("Pre-loading embedding model (first run can take ~30s)…", flush=True)
    await _warm_embedder()
    print("Embedding model ready.", flush=True)
    async with SessionLocal() as session:
        results = await run_graph_suite(cases, session)
    return _print_results("Graph trajectory", results)


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    with_graph = "--graph" in args

    cases = load_trajectory_cases()
    routing_results = run_routing_suite(cases)
    failures = _print_results("Routing trajectory", routing_results)

    if with_graph:
        try:
            _configure_event_loop()
            failures.extend(asyncio.run(_run_graph()))
        except Exception as exc:  # noqa: BLE001
            print(f"Graph trajectory skipped: {exc}")
            failures.append(f"graph suite error: {exc}")

    if failures:
        print("TRAJECTORY EVAL FAILED")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"TRAJECTORY EVAL PASSED ({len(cases)} routing cases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
