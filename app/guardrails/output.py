"""Output guardrails — grounded part numbers and safety notices."""

from __future__ import annotations

import re
from dataclasses import dataclass

PS_IN_TEXT = re.compile(r"\bPS\d{5,}\b", re.I)

SAFETY_NOTICE = (
    "Unplug the appliance and shut off the water supply before servicing, when applicable."
)


@dataclass(frozen=True)
class OutputGuardrailVerdict:
    ok: bool
    reason: str
    sanitized_text: str | None = None


def validate_output(
    text: str,
    *,
    allowed_ps_numbers: set[str],
    requires_safety: bool = False,
) -> OutputGuardrailVerdict:
    mentioned = {m.upper() for m in PS_IN_TEXT.findall(text)}
    unknown = mentioned - {ps.upper() for ps in allowed_ps_numbers}
    if unknown:
        return OutputGuardrailVerdict(
            ok=False,
            reason=f"Unverified part numbers in response: {', '.join(sorted(unknown))}.",
        )

    if requires_safety and SAFETY_NOTICE.lower() not in text.lower():
        augmented = text.rstrip() + f"\n\n{SAFETY_NOTICE}"
        return OutputGuardrailVerdict(
            ok=True,
            reason="Appended standard safety notice.",
            sanitized_text=augmented,
        )

    return OutputGuardrailVerdict(ok=True, reason="Output grounded.")
