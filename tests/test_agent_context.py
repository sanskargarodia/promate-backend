"""Multi-turn context merge tests."""

from app.agents.nodes import needs_clarification


def test_compatibility_with_prior_ps_in_state() -> None:
    state = {
        "intent": "compatibility",
        "ps_number": "PS11752778",
        "model_number": "WDT780SAEM1",
    }
    assert not needs_clarification(state)


def test_compatibility_needs_model_when_only_ps_known() -> None:
    state = {"intent": "compatibility", "ps_number": "PS11752778"}
    assert needs_clarification(state)
