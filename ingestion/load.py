"""Upsert parsed catalog data into Postgres (idempotent)."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from app.core.embeddings import get_embedder
from app.db.init_schema import init_schema_sync
from app.models.catalog import ApplianceModel
from ingestion.cache_store import read_cached
from ingestion.parse import parse_model_page, parse_part_page, part_to_documents
from ingestion.persist import SyncSession, link_compatibility, persist_scraped_part, upsert_model
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


def load_manifest(manifest: CrawlManifest) -> dict[str, int]:
    """Load all cached pages from a manifest into Postgres (HTML enrichment)."""
    init_schema_sync()
    embedder = get_embedder()

    counts = {"parts": 0, "models": 0}
    with SyncSession() as session:
        for url in manifest.part_urls:
            if load_part_from_cache(url, session, embedder):
                counts["parts"] += 1
        for url in manifest.model_urls:
            load_model_from_cache(url, session)
            counts["models"] += 1
        session.commit()

    logger.info("Cache enrichment loaded %s parts, %s models", counts["parts"], counts["models"])
    return counts


def ensure_required_parts_loaded(required_ps: Iterable[str]) -> list[str]:
    """Return PS numbers still missing from the database."""
    missing: list[str] = []
    with SyncSession() as session:
        from app.models.catalog import Part

        for ps in required_ps:
            if session.get(Part, ps.upper()) is None:
                missing.append(ps.upper())
    return missing
