"""Refusal messaging — structured categories, LLM context, and deterministic fallbacks."""

from __future__ import annotations

from typing import Literal

from app.agents.voice import CAPABILITIES, EXPANSION_NOTE, PROMATE_INTRO

RefusalCode = Literal[
    "prompt_injection",
    "unsupported_appliance",
    "unsupported_topic",
    "unclear_scope",
]

REFUSAL_CONTEXT: dict[RefusalCode, str] = {
    "prompt_injection": (
        "The message tried to override assistant instructions or extract hidden prompts."
    ),
    "unsupported_appliance": (
        "The user asked about an appliance category not yet available in the connected catalog."
    ),
    "unsupported_topic": (
        "The user asked about a topic unrelated to appliance parts or PartSelect."
    ),
    "unclear_scope": (
        "The message could not be matched to an appliance parts support query."
    ),
}

FALLBACK_RESPONSES: dict[RefusalCode, str] = {
    "prompt_injection": (
        f"{PROMATE_INTRO} "
        f"I can help with {CAPABILITIES}. "
        "Share a PartSelect part number (PS…), your appliance model, or describe what's going wrong "
        "and I'll pull catalog-backed answers."
    ),
    "unsupported_appliance": (
        "I don't have catalog coverage for that appliance category yet — "
        f"{EXPANSION_NOTE} "
        f"In the meantime, I can help with {CAPABILITIES} for parts in our catalog. "
        "Do you have a part number, model number, or repair question I can look up?"
    ),
    "unsupported_topic": (
        f"{PROMATE_INTRO} "
        f"I focus on appliance parts — {CAPABILITIES}. "
        "Share a part number, model, or symptom and I'll get started."
    ),
    "unclear_scope": (
        "I want to make sure I give you accurate, catalog-backed help. "
        f"{CAPABILITIES.capitalize()}. "
        "What PartSelect part number (PS…), appliance model, or symptom should we start with?"
    ),
}


def refusal_context(code: RefusalCode) -> str:
    return REFUSAL_CONTEXT[code]


def refusal_fallback(code: RefusalCode) -> str:
    return FALLBACK_RESPONSES[code]
