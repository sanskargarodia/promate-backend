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


def test_troubleshooting_needs_detail_for_vague_symptom() -> None:
    state = {
        "intent": "troubleshooting",
        "session_context": {"symptom_summary": "help me diagnose the problem"},
    }
    assert needs_clarification(state)


def test_troubleshooting_proceeds_with_appliance_and_noise() -> None:
    state = {
        "intent": "troubleshooting",
        "appliance_type": "refrigerator",
        "session_context": {
            "symptom_summary": "My refrigerator is making weird noises",
            "appliance_type": "refrigerator",
        },
    }
    assert not needs_clarification(state)


def test_troubleshooting_ready_with_specific_symptom() -> None:
    state = {
        "intent": "troubleshooting",
        "appliance_type": "refrigerator",
        "session_context": {
            "symptom_summary": "ice maker not working",
            "appliance_type": "refrigerator",
        },
    }
    assert not needs_clarification(state)
