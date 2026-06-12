"""Shared Postgres upsert helpers for ingestion pipelines."""

from __future__ import annotations

import logging
import re

from sqlalchemy import create_engine, delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.catalog import (
    ApplianceModel,
    Document,
    Part,
    PartModelCompatibility,
    PartSymptom,
    Symptom,
)
from ingestion.types import ScrapedDocument, ScrapedPart

logger = logging.getLogger(__name__)

sync_engine = create_engine(settings.sqlalchemy_sync_database_url, pool_pre_ping=True)
SyncSession = sessionmaker(sync_engine, expire_on_commit=False)

# Scrape requests often use short /PS123.htm URLs; CSV product_url has the canonical slug.
_SHORT_PARTSELECT_URL = re.compile(r"^https://www\.partselect\.com/PS\d+\.htm/?$", re.I)


def _pick_source_url(existing: str | None, incoming: str) -> str:
    if not existing:
        return incoming
    if _SHORT_PARTSELECT_URL.match(incoming) and not _SHORT_PARTSELECT_URL.match(existing):
        return existing
    return incoming


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:120] or "symptom"


def upsert_part(session: Session, part: ScrapedPart) -> None:
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
    row.source_url = _pick_source_url(row.source_url, part.source_url)


def upsert_model(session: Session, model: ApplianceModel) -> None:
    existing = session.get(ApplianceModel, model.model_number)
    if existing is None:
        session.add(model)
        return
    existing.brand = model.brand
    existing.appliance_type = model.appliance_type
    existing.title = model.title
    existing.source_url = model.source_url


def link_compatibility(session: Session, ps_number: str, model_number: str) -> None:
    if session.get(Part, ps_number) is None:
        return
    model = session.get(ApplianceModel, model_number)
    if model is None:
        session.add(
            ApplianceModel(
                model_number=model_number,
                appliance_type="unknown",
                title=model_number,
                source_url=f"https://www.partselect.com/Models/{model_number}/",
            )
        )
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


def bulk_link_compatibilities(session: Session, parts: list[ScrapedPart]) -> int:
    """Insert model rows and compatibility links for a batch (single flush + bulk insert)."""
    model_meta: dict[str, tuple[str | None, str]] = {}
    pairs: set[tuple[str, str]] = set()

    for part in parts:
        for raw in part.compatible_models:
            model_number = raw.strip().upper()
            if not model_number:
                continue
            pairs.add((part.ps_number, model_number))
            if model_number not in model_meta:
                model_meta[model_number] = (part.brand, part.appliance_type)

    if not pairs:
        return 0

    existing_models = {
        row
        for row in session.scalars(
            select(ApplianceModel.model_number).where(
                ApplianceModel.model_number.in_(model_meta.keys())
            )
        )
    }
    for model_number, (brand, appliance_type) in model_meta.items():
        if model_number in existing_models:
            continue
        session.add(
            ApplianceModel(
                model_number=model_number,
                appliance_type=appliance_type,
                brand=brand,
                title=model_number,
                source_url=f"https://www.partselect.com/Models/{model_number}/",
            )
        )

    session.flush()

    stmt = insert(PartModelCompatibility).values(
        [
            {
                "part_ps_number": ps_number,
                "model_number": model_number,
                "compatible": True,
            }
            for ps_number, model_number in pairs
        ]
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["part_ps_number", "model_number"],
    )
    session.execute(stmt)
    return len(pairs)


def upsert_symptoms(session: Session, part: ScrapedPart) -> None:
    for description in part.symptoms_fixed:
        slug = slugify(description)
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


def clear_install_guide_documents(session: Session, part_ps_number: str) -> None:
    session.execute(
        delete(Document).where(
            Document.part_ps_number == part_ps_number,
            Document.doc_type == "install_guide",
        )
    )


def upsert_document(session: Session, doc: ScrapedDocument, vector: list[float]) -> None:
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


def persist_scraped_part(
    session: Session,
    part: ScrapedPart,
    *,
    embedder: object | None = None,
    documents: list[ScrapedDocument] | None = None,
    compatible_models: list[str] | None = None,
) -> None:
    """Upsert a part, symptoms, optional docs/embeddings, and model fitment."""
    upsert_part(session, part)
    upsert_symptoms(session, part)

    for model_number in compatible_models or part.compatible_models:
        model_number = model_number.strip().upper()
        if not model_number:
            continue
        upsert_model(
            session,
            ApplianceModel(
                model_number=model_number,
                appliance_type=part.appliance_type,
                brand=part.brand,
                title=model_number,
                source_url=f"https://www.partselect.com/Models/{model_number}/",
            ),
        )
        link_compatibility(session, part.ps_number, model_number)

    docs = documents if documents is not None else []
    if embedder is not None and docs:
        if any(d.doc_type == "install_guide" for d in docs):
            clear_install_guide_documents(session, part.ps_number)
        vectors = embedder.embed_documents([d.content for d in docs])  # type: ignore[attr-defined]
        for doc, vector in zip(docs, vectors, strict=True):
            upsert_document(session, doc, vector)
