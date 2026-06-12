"""Import the full refrigerator + dishwasher catalog from a public scraped dataset.

PartSelect blocks many automated crawlers (403). This module is the fallback ladder
from PLAN.md: load real PartSelect rows from an existing public scrape (~7k parts)
while live Playwright scraping enriches HTML/RAG when the network allows.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from collections.abc import Iterable

import httpx
from sqlalchemy import text

from app.core.embeddings import get_embedder
from app.db.init_schema import init_schema_sync
from ingestion.parse import part_to_documents
from ingestion.persist import (
    SyncSession,
    bulk_link_compatibilities,
    upsert_document,
    upsert_part,
    upsert_symptoms,
)
from ingestion.types import ScrapedPart

logger = logging.getLogger(__name__)

# Real scraped PartSelect export (refrigerator + dishwasher only, ~7.1k rows).
DEFAULT_CATALOG_CSV_URL = (
    "https://raw.githubusercontent.com/JeffreyLiang321/PartsSelect/main/data/parts.csv"
)

ALLOWED_APPLIANCE_TYPES = frozenset({"refrigerator", "dishwasher"})

# Prevents two CLI runs from deadlocking on bulk INSERT (Postgres transaction locks).
_CATALOG_IMPORT_LOCK_ID = 42_424_242


def _parse_price_cents(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(round(float(value) * 100))
    except ValueError:
        return None


def _parse_install_minutes(value: str) -> int | None:
    from ingestion.parse import INSTALL_TIME_MAP

    lowered = value.lower()
    for label, minutes in INSTALL_TIME_MAP.items():
        if label in lowered:
            return minutes
    match = re.search(r"(\d+)", lowered)
    return int(match.group(1)) if match else None


def _split_pipe(value: str) -> list[str]:
    return [p.strip() for p in value.split("|") if p.strip()]


def _split_models(value: str) -> list[str]:
    if not value.strip():
        return []
    return [m.strip().upper() for m in re.split(r"\s*\|\s*", value) if m.strip()]


def row_to_scraped_part(row: dict[str, str]) -> ScrapedPart | None:
    appliance_type = (row.get("appliance_type") or row.get("appliance_types") or "").lower()
    if appliance_type not in ALLOWED_APPLIANCE_TYPES:
        return None

    part_id = row.get("part_id", "").strip().upper()
    if not part_id.startswith("PS"):
        return None

    symptoms = _split_pipe(row.get("symptoms", ""))
    replaced = [p.strip() for p in re.split(r",\s*", row.get("replace_parts", "")) if p.strip()]
    image_url = row.get("image_url", "").strip()
    in_stock_raw = row.get("in_stock", "").strip()

    return ScrapedPart(
        ps_number=part_id,
        manufacturer_part_number=row.get("mpn_id") or None,
        name=row.get("part_name") or part_id,
        brand=row.get("brand") or None,
        appliance_type=appliance_type,
        price_cents=_parse_price_cents(row.get("part_price", "")),
        in_stock=in_stock_raw in {"1", "true", "True", "yes"},
        image_urls=[image_url] if image_url else [],
        install_difficulty=row.get("install_difficulty") or None,
        install_time_minutes=_parse_install_minutes(row.get("install_time", "")),
        video_url=row.get("install_video_url") or None,
        rating=float(row["rating"]) if row.get("rating") else None,
        rating_count=int(row["review_count"]) if row.get("review_count") else None,
        description=row.get("description") or None,
        replaced_part_numbers=replaced,
        symptoms_fixed=symptoms,
        compatible_models=_split_models(row.get("compatible_models", "")),
        source_url=row.get("product_url") or f"https://www.partselect.com/{part_id}.htm",
    )


def download_catalog_csv(url: str = DEFAULT_CATALOG_CSV_URL) -> str:
    logger.info("Downloading public catalog CSV from %s", url)
    response = httpx.get(url, timeout=120.0, follow_redirects=True)
    response.raise_for_status()
    size_mb = len(response.content) / (1024 * 1024)
    logger.info("Downloaded catalog CSV (%.1f MB)", size_mb)
    csv_text = response.text
    from app.catalog.csv_schema import validate_parts_csv_text

    validation = validate_parts_csv_text(csv_text, min_rows=100)
    if not validation.ok:
        raise ValueError(f"Catalog CSV failed validation: {'; '.join(validation.errors)}")
    return csv_text


def iter_catalog_parts(csv_text: str) -> Iterable[ScrapedPart]:
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        part = row_to_scraped_part(row)
        if part is not None:
            yield part


def load_public_catalog(
    *,
    csv_url: str = DEFAULT_CATALOG_CSV_URL,
    embed_documents: bool = True,
    batch_size: int = 100,
    link_models: bool = True,
) -> dict[str, int]:
    """Load the full fridge + dishwasher catalog into Postgres."""
    init_schema_sync()
    csv_text = download_catalog_csv(csv_url)

    parts = list(iter_catalog_parts(csv_text))
    total = len(parts)
    logger.info("Parsed %s refrigerator + dishwasher parts from CSV", total)
    if total == 0:
        return {"parts": 0, "models_linked": 0}

    embedder = None
    if embed_documents:
        logger.info("Loading embedding model (first run may take 1–2 minutes)...")
        embedder = get_embedder()
        logger.info("Embedding model ready — importing parts in batches of %s", batch_size)
    else:
        logger.info("Skipping embeddings — importing parts in batches of %s", batch_size)

    counts = {"parts": 0, "models_linked": 0}

    with SyncSession() as session:
        if not session.scalar(text("SELECT pg_try_advisory_lock(:id)"), {"id": _CATALOG_IMPORT_LOCK_ID}):
            raise RuntimeError(
                "Another catalog import is already running (or was interrupted). "
                "Stop the other ingestion process, or run: "
                "docker exec promate-backend-postgres-1 psql -U promate -d promate "
                "-c \"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname='promate' AND state='idle in transaction';\""
            )

        try:
            for start in range(0, total, batch_size):
                batch = parts[start : start + batch_size]
                loaded, linked = _flush_batch(
                    session,
                    batch,
                    embedder,
                    link_models=link_models,
                )
                counts["parts"] += loaded
                counts["models_linked"] += linked
                session.commit()
                done = min(start + batch_size, total)
                logger.info("Imported %s / %s parts (%.0f%%)", done, total, 100 * done / total)
        finally:
            session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": _CATALOG_IMPORT_LOCK_ID})
            session.commit()

    logger.info(
        "Public catalog loaded: %s parts (%s model links)",
        counts["parts"],
        counts["models_linked"],
    )
    return counts


def _flush_batch(
    session,
    batch: list[ScrapedPart],
    embedder: object | None,
    *,
    link_models: bool,
) -> tuple[int, int]:
    from ingestion.types import ScrapedDocument

    loaded = 0
    all_docs: list[ScrapedDocument] = []

    for part in batch:
        upsert_part(session, part)
        upsert_symptoms(session, part)
        if embedder is not None:
            all_docs.extend(part_to_documents(part))
        loaded += 1

    if embedder is not None and all_docs:
        vectors = embedder.embed_documents([d.content for d in all_docs])  # type: ignore[attr-defined]
        for doc, vector in zip(all_docs, vectors, strict=True):
            upsert_document(session, doc, vector)

    linked = 0
    if link_models:
        linked = bulk_link_compatibilities(session, batch)

    return loaded, linked


def catalog_part_urls(csv_url: str = DEFAULT_CATALOG_CSV_URL) -> list[str]:
    """All PartSelect product URLs from the public catalog export."""
    csv_text = download_catalog_csv(csv_url)
    urls: list[str] = []
    for part in iter_catalog_parts(csv_text):
        urls.append(part.source_url)
    return urls
