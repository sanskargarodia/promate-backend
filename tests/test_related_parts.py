"""LLM + RAG related part recommendation tests."""

import pytest

from app.services.related_parts import (
    _format_retrieved_context,
    _parse_recommendations,
    find_related_parts,
)
from app.schemas.catalog import DocumentChunk, PartResult


def test_parse_recommendations_from_json() -> None:
    content = """
    Here are my picks:
    {"recommendations": [{"ps_number": "PS11739891", "reason": "Door hinge if sagging."}]}
    """
    recs = _parse_recommendations(content)
    assert len(recs) == 1
    assert recs[0].ps_number == "PS11739891"


def test_format_retrieved_context_includes_doc_body() -> None:
    text = _format_retrieved_context(
        [
            DocumentChunk(
                doc_type="install_guide",
                title="Install shelf bin",
                content="You may also need PS11739891 hinge.",
                part_ps_number="PS11752778",
            )
        ]
    )
    assert "PS11739891" in text
    assert "Install shelf bin" in text


@pytest.mark.asyncio
async def test_find_related_parts_uses_llm_and_catalog(monkeypatch) -> None:
    chunks = [
        DocumentChunk(
            doc_type="install_guide",
            title="Install",
            content="Replace PS11739891 hinge if the door sags.",
            part_ps_number="PS11752778",
        )
    ]

    async def fake_retrieve(*_args, **_kwargs):
        return chunks

    async def fake_llm(**_kwargs):
        return _parse_recommendations(
            '{"recommendations": [{"ps_number": "PS11739891", "reason": "Door hinge if sagging."}]}'
        )

    async def fake_get_part(_session, ps_number: str):
        if ps_number == "PS11739891":
            return PartResult(
                ps_number="PS11739891",
                name="Center Door Hinge",
                appliance_type="refrigerator",
                price_cents=4423,
                in_stock=True,
            )
        return None

    monkeypatch.setattr(
        "app.services.related_parts.is_llm_configured", lambda: True)
    monkeypatch.setattr(
        "app.services.related_parts._retrieve_companion_context", fake_retrieve
    )
    monkeypatch.setattr(
        "app.services.related_parts._llm_recommendations", fake_llm)
    monkeypatch.setattr(
        "app.services.related_parts.catalog_svc.get_part", fake_get_part)

    related = await find_related_parts(
        session=None,  # type: ignore[arg-type]
        ps_number="PS11752778",
        part_name="Door Shelf Bin",
        user_message="Tell me about PS11752778",
    )
    assert len(related) == 1
    assert related[0].ps_number == "PS11739891"
    assert related[0].recommendation_reason == "Door hinge if sagging."


@pytest.mark.asyncio
async def test_find_related_parts_skips_ps_not_in_retrieved_context(monkeypatch) -> None:
    async def fake_retrieve(*_args, **_kwargs):
        return [
            DocumentChunk(
                doc_type="install_guide",
                title="Install",
                content="Snap the bin into place.",
                part_ps_number="PS11752778",
            )
        ]

    async def fake_llm(**_kwargs):
        return _parse_recommendations(
            '{"recommendations": [{"ps_number": "PS99999999", "reason": "Random part."}]}'
        )

    monkeypatch.setattr(
        "app.services.related_parts.is_llm_configured", lambda: True)
    monkeypatch.setattr(
        "app.services.related_parts._retrieve_companion_context", fake_retrieve
    )
    monkeypatch.setattr(
        "app.services.related_parts._llm_recommendations", fake_llm)

    related = await find_related_parts(
        session=None,  # type: ignore[arg-type]
        ps_number="PS11752778",
        part_name="Door Shelf Bin",
        user_message="Tell me about PS11752778",
    )
    assert related == []
