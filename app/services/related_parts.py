"""LLM + RAG companion part recommendations."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import is_llm_configured
from app.core.llm import get_guardrail_model
from app.schemas.catalog import DocumentChunk, PartResult
from app.services import catalog as catalog_svc
from app.services import retrieval as retrieval_svc

PS_RE = re.compile(r"\bPS\d{5,}\b", re.I)


class RelatedPartRecommendation(BaseModel):
    ps_number: str
    reason: str = Field(min_length=1)


class _RecommendationResponse(BaseModel):
    recommendations: list[RelatedPartRecommendation] = Field(
        default_factory=list)


def _prompt(name: str, **kwargs: str) -> str:
    path = Path(__file__).resolve(
    ).parents[1] / "agents" / "prompts" / f"{name}.txt"
    return path.read_text(encoding="utf-8").format(**kwargs)


def _format_retrieved_context(chunks: list[DocumentChunk]) -> str:
    if not chunks:
        return "(No supporting documents retrieved.)"
    blocks: list[str] = []
    for chunk in chunks:
        header = f"[{chunk.doc_type}] {chunk.title}"
        if chunk.part_ps_number:
            header += f" ({chunk.part_ps_number})"
        blocks.append(f"{header}\n{chunk.content.strip()}")
    return "\n\n---\n\n".join(blocks)


def _ps_numbers_in_text(text: str) -> set[str]:
    return {match.upper() for match in PS_RE.findall(text)}


async def _retrieve_companion_context(
    session: AsyncSession,
    *,
    ps_number: str,
    part_name: str,
    user_message: str,
) -> list[DocumentChunk]:
    """Pull install/repair/support context for the primary part via RAG."""
    ps = ps_number.strip().upper()
    seen: set[tuple[str, str]] = set()
    chunks: list[DocumentChunk] = []

    async def add(query: str, *, doc_type: str | None = None, limit: int = 4) -> None:
        results = await retrieval_svc.search_documents(
            session,
            query=query,
            doc_type=doc_type,
            part_ps_number=ps,
            limit=limit,
        )
        for chunk in results:
            key = (chunk.title, chunk.content[:120])
            if key in seen:
                continue
            seen.add(key)
            chunks.append(chunk)

    await add(user_message, limit=4)
    await add(
        f"parts supplies tools required to install {part_name}",
        doc_type="install_guide",
        limit=4,
    )
    await add(f"companion parts commonly needed with {part_name}", limit=3)
    await add(f"related repair parts for {part_name}", limit=3)
    return chunks


def _parse_recommendations(content: str) -> list[RelatedPartRecommendation]:
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(content[start: end + 1])
        return _RecommendationResponse.model_validate(payload).recommendations
    except Exception:  # noqa: BLE001
        return []


async def _llm_recommendations(
    *,
    primary_ps: str,
    primary_name: str,
    user_message: str,
    chunks: list[DocumentChunk],
    limit: int,
) -> list[RelatedPartRecommendation]:
    model = get_guardrail_model(max_tokens=512)
    prompt = _prompt(
        "related_parts",
        primary_ps=primary_ps,
        primary_name=primary_name or primary_ps,
        user_message=user_message,
        retrieved_context=_format_retrieved_context(chunks),
        limit=str(limit),
    )
    try:
        resp = await model.ainvoke(prompt)
        content = resp.content if isinstance(
            resp.content, str) else str(resp.content)
        return _parse_recommendations(content)
    except Exception:  # noqa: BLE001
        return []


async def find_related_parts(
    session: AsyncSession,
    *,
    ps_number: str,
    part_name: str,
    user_message: str,
    limit: int = 2,
) -> list[PartResult]:
    """Use RAG + LLM to suggest catalog-grounded companion parts for the primary part."""
    if not is_llm_configured():
        return []

    ps = ps_number.strip().upper()
    chunks = await _retrieve_companion_context(
        session,
        ps_number=ps,
        part_name=part_name,
        user_message=user_message,
    )
    if not chunks:
        return []

    context_ps = _ps_numbers_in_text(_format_retrieved_context(chunks))
    recommendations = await _llm_recommendations(
        primary_ps=ps,
        primary_name=part_name,
        user_message=user_message,
        chunks=chunks,
        limit=limit,
    )

    related: list[PartResult] = []
    for rec in recommendations[:limit]:
        candidate_ps = rec.ps_number.strip().upper()
        if not candidate_ps.startswith("PS"):
            candidate_ps = f"PS{candidate_ps.removeprefix('PS')}"
        if candidate_ps == ps:
            continue
        if candidate_ps not in context_ps:
            continue

        part = await catalog_svc.get_part(session, candidate_ps)
        if part is None:
            continue

        related.append(
            part.model_copy(
                update={"recommendation_reason": rec.reason.strip()})
        )

    return related
