"""Tests for LLM follow-up suggestion parsing."""

from app.agents.follow_ups import parse_follow_up_response


def test_parse_json_array() -> None:
    prompts = parse_follow_up_response(
        'Here are ideas:\n["How do I install PS11752778?", "I\'m ready to buy it"]'
    )
    assert len(prompts) == 2
    assert "PS11752778" in prompts[0]


def test_parse_json_object_wrapper() -> None:
    prompts = parse_follow_up_response(
        '{"prompts": ["Will it fit WDT780SAEM1?", "Check order ORD-DEMO-001"]}'
    )
    assert len(prompts) == 2


def test_parse_dedupes_and_limits() -> None:
    raw = '["Same question", "Same question", "Another one", "Third", "Fourth", "Fifth"]'
    prompts = parse_follow_up_response(raw, max_count=3)
    assert len(prompts) == 3
    assert prompts[0] == "Same question"


def test_parse_empty_on_garbage() -> None:
    assert parse_follow_up_response("not json at all") == []
