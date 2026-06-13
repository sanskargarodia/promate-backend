"""Upsert parsed catalog data into Postgres (idempotent)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.core.embeddings import get_embedder
from app.db.init_schema import init_schema_sync
from app.models.catalog import ApplianceModel
from ingestion.cache_store import read_cached
from ingestion.parse import (
    parse_model_page,
    parse_part_page,
    parse_repair_help_page,
    part_to_documents,
)
from ingestion.persist import (
    SyncSession,
    link_compatibility,
    persist_scraped_part,
    upsert_document,
    upsert_model,
)
from ingestion.seeds import manifest_for_ps_numbers
from ingestion.types import CrawlManifest

logger = logging.getLogger(__name__)


def load_part_from_cache(url: str, session, embedder: object) -> bool:
    html = read_cached(url, kind="parts")
    if not html:
        return False
    part = parse_part_page(html, source_url=url)
    docs = part_to_documents(part)
    persist_scraped_part(session, part, embedder=embedder, documents=docs)
    return True


def load_model_from_cache(url: str, session) -> None:
    html = read_cached(url, kind="models")
    if not html:
        logger.warning("No cached HTML for model %s", url)
        return
    scraped = parse_model_page(html, source_url=url)
    upsert_model(
        session,
        ApplianceModel(
            model_number=scraped.model_number,
            brand=scraped.brand,
            appliance_type=scraped.appliance_type,
            title=scraped.title,
            source_url=scraped.source_url,
        ),
    )
    for ps in scraped.part_ps_numbers:
        link_compatibility(session, ps, scraped.model_number)


def load_repair_help_from_cache(url: str, session, embedder: object) -> bool:
    html = read_cached(url, kind="repair_help")
    if not html:
        return False
    docs = parse_repair_help_page(html, source_url=url)
    if not docs:
        return False
    if embedder is not None:
        vectors = embedder.embed_documents(
            [d.content for d in docs])  # type: ignore[attr-defined]
        for doc, vector in zip(docs, vectors, strict=True):
            upsert_document(session, doc, vector)
    return True


def load_parts_by_ps(
    ps_numbers: Iterable[str],
    *,
    embedder: object | None = None,
) -> dict[str, int]:
    """Re-enrich specific parts from cached HTML (install stories, compat, embeddings)."""
    init_schema_sync()
    embedder = embedder or get_embedder()
    manifest = manifest_for_ps_numbers(list(ps_numbers))

    counts = {"parts": 0, "models": 0, "missing": 0}
    with SyncSession() as session:
        for url in manifest.part_urls:
            if load_part_from_cache(url, session, embedder):
                counts["parts"] += 1
            else:
                counts["missing"] += 1
                logger.warning(
                    "No cached HTML for %s — run: uv run python -m ingestion scrape --ps %s",
                    url,
                    url,
                )
        session.commit()

    logger.info(
        "Part enrichment: %s loaded, %s missing cache",
        counts["parts"],
        counts["missing"],
    )
    return counts


def load_manifest(manifest: CrawlManifest) -> dict[str, int]:
    """Load all cached pages from a manifest into Postgres (HTML enrichment)."""
    init_schema_sync()
    embedder = get_embedder()

    counts = {"parts": 0, "models": 0, "repair_help": 0}
    with SyncSession() as session:
        for url in manifest.part_urls:
            if load_part_from_cache(url, session, embedder):
                counts["parts"] += 1
        for url in manifest.model_urls:
            load_model_from_cache(url, session)
            counts["models"] += 1
        for url in manifest.repair_help_urls:
            if load_repair_help_from_cache(url, session, embedder):
                counts["repair_help"] += 1
        session.commit()

    logger.info(
        "Cache enrichment loaded %s parts, %s models, %s repair-help articles",
        counts["parts"],
        counts["models"],
        counts["repair_help"],
    )
    return counts


def ensure_required_parts_loaded(required_ps: Iterable[str]) -> list[str]:
    """Return PS numbers still missing from the database."""
    missing: list[str] = []
    with SyncSession() as session:
        from app.models.catalog import Part

        for ps in required_ps:
            ps_number = ps.strip().upper()
            if not ps_number.startswith("PS"):
                ps_number = f"PS{ps_number}"
            if session.get(Part, ps_number) is None:
                missing.append(ps_number)
    return missing
