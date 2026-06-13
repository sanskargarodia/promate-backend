"""Input guardrails — legacy module; scope screening now lives in the supervisor LLM."""

from __future__ import annotations

from dataclasses import dataclass

from app.guardrails.refusal import RefusalCode


@dataclass(frozen=True)
class InputGuardrailVerdict:
    in_scope: bool
    injection_detected: bool
    reason: str
    refusal_code: RefusalCode | None = None


def run_input_guardrails(text: str) -> InputGuardrailVerdict:
    """Deprecated pass-through — supervisor LLM owns scope and injection screening."""
    _ = text
    return InputGuardrailVerdict(
        in_scope=True,
        injection_detected=False,
        reason="Scope screening delegated to supervisor LLM.",
    )
