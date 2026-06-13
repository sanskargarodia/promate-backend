"""Tests for eval dataset loading and routing trajectory."""

from __future__ import annotations

import pytest

from evals.loader import CANONICAL_LIVE_IDS, load_all_cases, load_category, load_live_cases
from evals.schema import DATASET_CATEGORIES
from evals.trajectory import run_routing_suite


@pytest.mark.parametrize("category", DATASET_CATEGORIES)
def test_dataset_files_load(category: str) -> None:
    cases = load_category(category)
    assert cases, f"{category} dataset is empty"


def test_all_cases_unique_ids() -> None:
    cases = load_all_cases()
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))


def test_canonical_live_subset() -> None:
    canonical = load_live_cases(canonical_only=True)
    assert len(canonical) == len(CANONICAL_LIVE_IDS)
    assert {case.id for case in canonical} == set(CANONICAL_LIVE_IDS)


def test_routing_trajectory_passes() -> None:
    cases = load_all_cases()
    results = run_routing_suite(cases)
    failures = [f for result in results if not result.passed for f in result.failures]
    assert not failures, failures
