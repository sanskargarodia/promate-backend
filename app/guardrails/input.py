"""Input guardrails — scope and prompt-injection screening."""

from __future__ import annotations

import re
from dataclasses import dataclass

OUT_OF_SCOPE_PATTERNS = (
    re.compile(r"\b(washing machine|dryer|oven|microwave|hvac|plumb(ing|er))\b", re.I),
    re.compile(r"\b(write code|python script|leetcode|homework)\b", re.I),
    re.compile(r"\b(tesla|iphone|crypto|stock market)\b", re.I),
)

IN_SCOPE_HINTS = (
    re.compile(r"\b(refrigerator|fridge|dishwasher|partselect|appliance part)\b", re.I),
    re.compile(r"\bPS\d+\b", re.I),
    re.compile(r"\b(install|compatible|compatibility|ice maker|not working|symptom)\b", re.I),
    re.compile(r"\b[A-Z]{2,}\d{3,}[A-Z0-9]*\b"),  # model numbers e.g. WDT780SAEM1
)

INJECTION_PATTERNS = (
    re.compile(r"ignore (all )?(previous|prior|above) instructions", re.I),
    re.compile(r"disregard (your|the) (system|safety)", re.I),
    re.compile(r"you are now (?:a|an) ", re.I),
    re.compile(r"reveal (your|the) (system )?prompt", re.I),
    re.compile(r"<\s*/?\s*system\s*>", re.I),
)


@dataclass(frozen=True)
class InputGuardrailVerdict:
    in_scope: bool
    injection_detected: bool
    reason: str


def run_input_guardrails(text: str) -> InputGuardrailVerdict:
    """Cheap rule-based pre-check; fails closed when clearly out of scope."""
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return InputGuardrailVerdict(
                in_scope=False,
                injection_detected=True,
                reason="Prompt injection pattern detected.",
            )

    for pattern in OUT_OF_SCOPE_PATTERNS:
        if pattern.search(text):
            return InputGuardrailVerdict(
                in_scope=False,
                injection_detected=False,
                reason="Query appears outside refrigerator/dishwasher parts scope.",
            )

    if any(p.search(text) for p in IN_SCOPE_HINTS):
        return InputGuardrailVerdict(
            in_scope=True,
            injection_detected=False,
            reason="In-scope appliance/parts query.",
        )

    # Short greetings / vague — allow supervisor to clarify rather than refuse.
    if len(text.split()) <= 4:
        return InputGuardrailVerdict(
            in_scope=True,
            injection_detected=False,
            reason="Short utterance — allow clarification path.",
        )

    return InputGuardrailVerdict(
        in_scope=False,
        injection_detected=False,
        reason="Could not confirm refrigerator/dishwasher parts scope.",
    )
