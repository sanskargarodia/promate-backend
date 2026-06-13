"""Refusal node and messaging tests."""

import pytest

from app.agents.nodes import _compose_refusal, refusal_node, supervisor_node
from app.guardrails.refusal import refusal_fallback


@pytest.mark.asyncio
async def test_refusal_node_uses_fallback_without_llm(monkeypatch) -> None:
    monkeypatch.setattr("app.agents.nodes.is_llm_configured", lambda: False)

    state = {
        "messages": [{"role": "user", "content": "My washing machine is leaking"}],
        "refusal_code": "unsupported_appliance",
    }
    result = await refusal_node(state, {})

    expected = refusal_fallback("unsupported_appliance")
    assert result["final_response"] == expected
    assert "Query appears outside" not in result["final_response"]
    assert result["messages"][0].content == expected


@pytest.mark.asyncio
async def test_supervisor_routes_refusal_to_refusal_code(monkeypatch) -> None:
    async def fake_llm_route(_state, _text: str):
        return {"intent": "refusal", "refusal_code": "unsupported_topic"}

    monkeypatch.setattr("app.agents.nodes.is_llm_configured", lambda: True)
    monkeypatch.setattr("app.agents.nodes._llm_route", fake_llm_route)

    state = {"messages": [
        {"role": "user", "content": "Write me a Python script"}]}
    result = await supervisor_node(state, {})

    assert result["refused"] is True
    assert result["refusal_code"] == "unsupported_topic"


@pytest.mark.asyncio
async def test_compose_refusal_fallback_on_empty_llm_response(monkeypatch) -> None:
    class _FakeResp:
        content = "   "

    class _FakeModel:
        async def ainvoke(self, _prompt: str) -> _FakeResp:
            return _FakeResp()

    monkeypatch.setattr("app.agents.nodes.is_llm_configured", lambda: True)
    monkeypatch.setattr("app.agents.nodes.get_guardrail_model",
                        lambda **_kwargs: _FakeModel())

    text = await _compose_refusal("My dryer belt broke", "unsupported_appliance")
    assert text == refusal_fallback("unsupported_appliance")


def test_refusal_fallbacks_avoid_narrow_scope_messaging() -> None:
    narrow_phrases = (
        "refrigerator and dishwasher",
        "fridge or dishwasher",
        "only support",
        "scoped to",
        "specialized for",
    )
    for code in ("prompt_injection", "unsupported_appliance", "unsupported_topic", "unclear_scope"):
        text = refusal_fallback(code)  # type: ignore[arg-type]
        lowered = text.lower()
        for phrase in narrow_phrases:
            assert phrase not in lowered, f"{code} fallback mentions '{phrase}'"
