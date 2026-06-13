"""Load eval datasets from `evals/datasets/*.jsonl`."""

from __future__ import annotations

import json
from pathlib import Path

from evals.schema import DATASET_CATEGORIES, Category, EvalCase

_DATASETS_DIR = Path(__file__).resolve().parent / "datasets"

CANONICAL_LIVE_IDS: frozenset[str] = frozenset(
    {
        "canonical_install",
        "canonical_compatibility",
        "canonical_troubleshooting",
        "canonical_purchase_handoff",
        "canonical_grounding_failure",
        "canonical_order_status",
    }
)


def _dataset_path(category: Category) -> Path:
    return _DATASETS_DIR / f"{category}.jsonl"


def load_category(category: Category) -> list[EvalCase]:
    path = _dataset_path(category)
    if not path.is_file():
        raise FileNotFoundError(f"Missing eval dataset: {path}")
    cases: list[EvalCase] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
            cases.append(EvalCase.model_validate(raw))
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_no}: invalid eval case: {exc}") from exc
    return cases


def load_all_cases() -> list[EvalCase]:
    cases: list[EvalCase] = []
    for category in DATASET_CATEGORIES:
        cases.extend(load_category(category))
    canonical_path = _DATASETS_DIR / "canonical.jsonl"
    if canonical_path.is_file():
        for line_no, line in enumerate(
            canonical_path.read_text(encoding="utf-8").splitlines(), start=1,
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                raw = json.loads(stripped)
                cases.append(EvalCase.model_validate(raw))
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(
                    f"{canonical_path}:{line_no}: invalid eval case: {exc}"
                ) from exc
    return cases


def load_trajectory_cases() -> list[EvalCase]:
    """All dataset cases used for routing + optional graph trajectory eval."""
    return load_all_cases()


def load_live_cases(*, canonical_only: bool = False) -> list[EvalCase]:
    """Cases for live E2E eval (requires DB + Anthropic API key)."""
    all_cases = load_all_cases()
    if canonical_only:
        return [case for case in all_cases if case.id in CANONICAL_LIVE_IDS]
    return [
        case
        for case in all_cases
        if case.category != "out_of_scope"
        and case.category != "injection"
        and not case.expect_refusal
    ]
