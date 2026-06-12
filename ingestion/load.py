"""Upsert parsed catalog data into Postgres (idempotent)."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.embeddings import get_embedder
from app.db.init_schema import init_schema
from app.models.catalog import (
    ApplianceModel,
    Document,
    Part,
    PartModelCompatibility,
    PartSymptom,
    Symptom,
)
from ingestion.cache_store import read_cached
from ingestion.parse import parse_model_page, parse_part_page, part_to_documents
from ingestion.types import CrawlManifest, ScrapedDocument, ScrapedPart

logger = logging.getLogger(__name__)

_sync_engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
SyncSession = sessionmaker(_sync_engine, expire_on_commit=False)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:120] or "symptom"


def _upsert_part(session: Session, part: ScrapedPart) -> None:
    row = session.get(Part, part.ps_number)
    if row is None:
        row = Part(ps_number=part.ps_number)
        session.add(row)

    row.manufacturer_part_number = part.manufacturer_part_number
    row.name = part.name
    row.brand = part.brand
    row.appliance_type = part.appliance_type
    row.price_cents = part.price_cents
    row.in_stock = part.in_stock
    row.image_urls = part.image_urls
    row.install_difficulty = part.install_difficulty
    row.install_time_minutes = part.install_time_minutes
    row.install_instructions = part.install_instructions
    row.video_url = part.video_url
    row.rating = part.rating
    row.rating_count = part.rating_count
    row.description = part.description
    row.replaced_part_numbers = part.replaced_part_numbers
    row.symptoms_fixed = part.symptoms_fixed
    row.source_url = part.source_url


def _upsert_model(session: Session, model: ApplianceModel) -> None:
    existing = session.get(ApplianceModel, model.model_number)
    if existing is None:
        session.add(model)
        return
    existing.brand = model.brand
    existing.appliance_type = model.appliance_type
    existing.title = model.title
    existing.source_url = model.source_url


def _link_compatibility(session: Session, ps_number: str, model_number: str) -> None:
    if session.get(Part, ps_number) is None or session.get(ApplianceModel, model_number) is None:
        return
    exists = session.scalar(
        select(PartModelCompatibility).where(
            PartModelCompatibility.part_ps_number == ps_number,
            PartModelCompatibility.model_number == model_number,
        )
    )
    if exists is None:
        session.add(
            PartModelCompatibility(
                part_ps_number=ps_number,
                model_number=model_number,
                compatible=True,
            )
        )


def _upsert_symptoms(session: Session, part: ScrapedPart) -> None:
    for description in part.symptoms_fixed:
        slug = _slugify(description)
        symptom = session.scalar(select(Symptom).where(Symptom.slug == slug))
        if symptom is None:
            symptom = Symptom(
                slug=slug,
                description=description,
                appliance_type=part.appliance_type,
                brand=part.brand,
            )
            session.add(symptom)
            session.flush()

        link = session.scalar(
            select(PartSymptom).where(
                PartSymptom.part_ps_number == part.ps_number,
                PartSymptom.symptom_id == symptom.id,
            )
        )
        if link is None:
            session.add(PartSymptom(part_ps_number=part.ps_number, symptom_id=symptom.id))


def _upsert_document(session: Session, doc: ScrapedDocument, vector: list[float]) -> None:
    existing = session.scalar(
        select(Document).where(
            Document.part_ps_number == doc.part_ps_number,
            Document.doc_type == doc.doc_type,
            Document.title == doc.title,
        )
    )
    if existing is None:
        existing = Document(
            doc_type=doc.doc_type,
            title=doc.title,
            part_ps_number=doc.part_ps_number,
        )
        session.add(existing)

    existing.content = doc.content
    existing.embedding = vector
    existing.model_number = doc.model_number
    existing.source_url = doc.source_url
    existing.metadata_ = doc.metadata


def load_part_from_cache(url: str, session: Session, embedder: object) -> ScrapedPart | None:
    html = read_cached(url, kind="parts")
    if not html:
        logger.warning("No cached HTML for part %s", url)
        return None
    part = parse_part_page(html, source_url=url)
    _upsert_part(session, part)
    _upsert_symptoms(session, part)

    for model_number in part.compatible_models:
        model_row = ApplianceModel(
            model_number=model_number,
            appliance_type=part.appliance_type,
            brand=part.brand,
            title=model_number,
            source_url=f"https://www.partselect.com/Models/{model_number}/",
        )
        _upsert_model(session, model_row)
        _link_compatibility(session, part.ps_number, model_number)

    docs = part_to_documents(part)
    if docs:
        vectors = embedder.embed_documents([d.content for d in docs])  # type: ignore[attr-defined]
        for doc, vector in zip(docs, vectors, strict=True):
            _upsert_document(session, doc, vector)

    return part


def load_model_from_cache(url: str, session: Session) -> None:
    html = read_cached(url, kind="models")
    if not html:
        logger.warning("No cached HTML for model %s", url)
        return
    scraped = parse_model_page(html, source_url=url)
    model_row = ApplianceModel(
        model_number=scraped.model_number,
        brand=scraped.brand,
        appliance_type=scraped.appliance_type,
        title=scraped.title,
        source_url=scraped.source_url,
    )
    _upsert_model(session, model_row)

    for ps in scraped.part_ps_numbers:
        if session.get(Part, ps) is not None:
            _link_compatibility(session, ps, scraped.model_number)


async def load_manifest(manifest: CrawlManifest) -> dict[str, int]:
    """Load all cached pages from a manifest into Postgres."""
    await init_schema()
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

    logger.info("Loaded %s parts and %s models", counts["parts"], counts["models"])
    return counts


def ensure_required_parts_loaded(required_ps: Iterable[str]) -> list[str]:
    """Return PS numbers still missing from the database."""
    missing: list[str] = []
    with SyncSession() as session:
        for ps in required_ps:
            if session.get(Part, ps.upper()) is None:
                missing.append(ps.upper())
    return missing
