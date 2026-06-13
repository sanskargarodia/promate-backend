"""Output guardrail tests."""

from app.guardrails.output import strip_unverified_ps_numbers, validate_output


def test_validate_output_allows_grounded_ps() -> None:
    verdict = validate_output(
        "Try PS11752778 for the bin.",
        allowed_ps_numbers={"PS11752778"},
    )
    assert verdict.ok


def test_validate_output_strips_unverified_ps_when_possible() -> None:
    verdict = validate_output(
        "Try PS11752778 and also PS99999999.",
        allowed_ps_numbers={"PS11752778"},
    )
    assert verdict.ok
    assert verdict.sanitized_text is not None
    assert "PS11752778" in verdict.sanitized_text
    assert "PS99999999" not in verdict.sanitized_text


def test_strip_unverified_ps_numbers() -> None:
    cleaned = strip_unverified_ps_numbers(
        "Part PS11111111 and PS22222222",
        allowed_ps_numbers={"PS11111111"},
    )
    assert "PS11111111" in cleaned
    assert "PS22222222" not in cleaned
