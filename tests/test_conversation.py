"""Conversation memory tests."""

from app.agents.conversation import (
    build_working_query,
    format_recent_transcript,
    has_troubleshooting_minimum_context,
    is_vague_troubleshooting,
    merge_session_context,
)


def test_format_recent_transcript_includes_prior_turns() -> None:
    state = {
        "messages": [
            {"role": "user", "content": "help me diagnose"},
            {"role": "assistant", "content": "What appliance and symptom?"},
            {"role": "user", "content": "My refrigerator is making weird noise"},
        ]
    }
    transcript = format_recent_transcript(state)
    assert "help me diagnose" in transcript
    assert "weird noise" in transcript


def test_build_working_query_accumulates_symptom_context() -> None:
    state = {
        "messages": [{"role": "user", "content": "My refrigerator is making weird noise"}],
        "session_context": {
            "active_intent": "troubleshooting",
            "symptom_summary": "help me diagnose",
            "appliance_type": "refrigerator",
        },
    }
    query = build_working_query(state)
    assert "refrigerator" in query
    assert "weird noise" in query


def test_merge_session_context_keeps_troubleshooting_across_turns() -> None:
    state = {
        "session_context": {"active_intent": "troubleshooting", "symptom_summary": "help me diagnose"},
        "messages": [{"role": "user", "content": "My refrigerator is making weird noise"}],
    }
    merged = merge_session_context(
        state,
        intent="troubleshooting",
        ps_number=None,
        model_number=None,
        appliance_type="refrigerator",
        brand=None,
        latest_user_text="My refrigerator is making weird noise",
    )
    assert merged["active_intent"] == "troubleshooting"
    assert merged["appliance_type"] == "refrigerator"


def test_vague_troubleshooting_detects_weird_noise() -> None:
    state = {
        "intent": "troubleshooting",
        "appliance_type": "refrigerator",
        "session_context": {
            "symptom_summary": "My refrigerator is making weird noise",
            "appliance_type": "refrigerator",
        },
    }
    assert not is_vague_troubleshooting(state)
    assert has_troubleshooting_minimum_context(state)


def test_vague_troubleshooting_still_true_for_meta_only() -> None:
    state = {
        "intent": "troubleshooting",
        "session_context": {"symptom_summary": "help me diagnose the problem"},
    }
    assert is_vague_troubleshooting(state)


def test_minimum_context_infers_appliance_from_message() -> None:
    state = {
        "intent": "troubleshooting",
        "messages": [{"role": "user", "content": "My refrigerator is making weird noises"}],
    }
    assert has_troubleshooting_minimum_context(state)
    assert not is_vague_troubleshooting(state)
