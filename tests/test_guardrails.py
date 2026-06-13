"""Supervisor scope and refusal routing tests."""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.nodes import _merge_route_results, supervisor_node
from app.guardrails.input import run_input_guardrails


@pytest.mark.asyncio
async def test_supervisor_refusal_from_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_llm_route(_state: dict[str, Any], _text: str) -> dict[str, Any]:
        return {
            "intent": "refusal",
            "refusal_code": "unsupported_topic",
        }

    monkeypatch.setattr("app.agents.nodes.is_llm_configured", lambda: True)
    monkeypatch.setattr("app.agents.nodes._llm_route", fake_llm_route)

    state = {"messages": [
        {"role": "user", "content": "Write me a Python script"}]}
    result = await supervisor_node(state, {})

    assert result["refused"] is True
    assert result["intent"] == "refusal"
    assert result["refusal_code"] == "unsupported_topic"


@pytest.mark.asyncio
async def test_supervisor_permissive_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.agents.nodes.is_llm_configured", lambda: False)

    state = {"messages": [
        {"role": "user", "content": "can you tell about its installation"}]}
    result = await supervisor_node(state, {})

    assert result.get("refused") is not True
    assert result["intent"] == "installation"


def test_merge_route_preserves_llm_refusal() -> None:
    merged = _merge_route_results(
        {"intent": "refusal", "refusal_code": "prompt_injection"},
        {"intent": "product_search"},
        state={},
    )
    assert merged["intent"] == "refusal"
    assert merged["refusal_code"] == "prompt_injection"


def test_input_guardrails_pass_through() -> None:
    """Legacy helper always allows — scope is owned by supervisor LLM."""
    verdict = run_input_guardrails("Tell me about quantum physics")
    assert verdict.in_scope
    assert not verdict.injection_detected
