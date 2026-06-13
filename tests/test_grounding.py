"""Grounding helper tests."""

from app.agents.grounding import grounded_ps_numbers


def test_grounded_ps_from_documents_and_diagnosis() -> None:
    allowed = grounded_ps_numbers(
        tool_payload={
            "documents": [
                {"part_ps_number": "PS11111111", "content": "Also see PS22222222"},
            ],
            "diagnosis": {
                "candidate_parts": [{"ps_number": "PS33333333"}],
            },
        },
        tool_results={
            "search_parts": {"parts": [{"part_id": "PS44444444"}]},
        },
    )
    assert "PS11111111" in allowed
    assert "PS22222222" in allowed
    assert "PS33333333" in allowed
    assert "PS44444444" in allowed
