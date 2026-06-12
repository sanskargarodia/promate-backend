"""Semantic search over pgvector document embeddings."""

from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.embeddings import get_embedder
from app.models.catalog import Document
from app.schemas.catalog import DocumentChunk


async def search_documents(
    session: AsyncSession,
    *,
    query: str,
    doc_type: str | None = None,
    part_ps_number: str | None = None,
    limit: int = 5,
) -> list[DocumentChunk]:
    embedder = get_embedder()
    vector = await asyncio.to_thread(embedder.embed_query, query)

    stmt = select(
        Document,
        Document.embedding.cosine_distance(vector).label("distance"),
    )
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if part_ps_number:
        stmt = stmt.where(Document.part_ps_number == part_ps_number.upper())

    stmt = stmt.order_by("distance").limit(limit)
    rows = (await session.execute(stmt)).all()

    chunks: list[DocumentChunk] = []
    for doc, distance in rows:
        chunks.append(
            DocumentChunk(
                doc_type=doc.doc_type,
                title=doc.title,
                content=doc.content,
                part_ps_number=doc.part_ps_number,
                source_url=doc.source_url,
                score=float(1.0 - distance) if distance is not None else None,
            )
        )
    return chunks
