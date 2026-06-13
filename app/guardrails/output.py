"""Output guardrails — grounded part numbers in responses."""

from __future__ import annotations

import re
from dataclasses import dataclass

PS_IN_TEXT = re.compile(r"\b(PS\d{5,})\b", re.I)


@dataclass(frozen=True)
class OutputGuardrailVerdict:
    ok: bool
    reason: str
    sanitized_text: str | None = None


def strip_unverified_ps_numbers(text: str, *, allowed_ps_numbers: set[str]) -> str:
    """Remove PS tokens that are not in the grounded allow-list."""
    allowed = {ps.upper() for ps in allowed_ps_numbers}

    def replacer(match: re.Match[str]) -> str:
        token = match.group(1).upper()
        return match.group(0) if token in allowed else ""

    cleaned = PS_IN_TEXT.sub(replacer, text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def validate_output(
    text: str,
    *,
    allowed_ps_numbers: set[str],
) -> OutputGuardrailVerdict:
    mentioned = {m.upper() for m in PS_IN_TEXT.findall(text)}
    allowed_upper = {ps.upper() for ps in allowed_ps_numbers}
    unknown = mentioned - allowed_upper
    if unknown:
        sanitized = strip_unverified_ps_numbers(
            text, allowed_ps_numbers=allowed_ps_numbers)
        remaining = {m.upper() for m in PS_IN_TEXT.findall(sanitized)}
        if remaining <= allowed_upper:
            return OutputGuardrailVerdict(
                ok=True,
                reason=f"Removed unverified part numbers: {', '.join(sorted(unknown))}.",
                sanitized_text=sanitized,
            )
        return OutputGuardrailVerdict(
            ok=False,
            reason=f"Unverified part numbers in response: {', '.join(sorted(unknown))}.",
        )

    return OutputGuardrailVerdict(ok=True, reason="Output grounded.")
