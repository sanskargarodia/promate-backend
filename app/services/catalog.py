"""Async catalog queries over Postgres (structured data — no LLM)."""

from __future__ import annotations

import re

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import Document, Part, PartModelCompatibility
from app.schemas.catalog import (
    CompatibilityResult,
    DiagnosisCandidate,
    DiagnosisResult,
    InstallationGuide,
    InstallStep,
    PartResult,
)

PS_RE = re.compile(r"PS\d+", re.I)


def _part_to_result(part: Part) -> PartResult:
    return PartResult(
        ps_number=part.ps_number,
        name=part.name,
        brand=part.brand,
        appliance_type=part.appliance_type,
        price_cents=part.price_cents,
        in_stock=part.in_stock,
        image_urls=list(part.image_urls or []),
        install_difficulty=part.install_difficulty,
        install_time_minutes=part.install_time_minutes,
        rating=part.rating,
        rating_count=part.rating_count,
        source_url=part.source_url,
    )


async def get_part(session: AsyncSession, ps_number: str) -> PartResult | None:
    ps = ps_number.strip().upper()
    if not ps.startswith("PS"):
        ps = f"PS{ps.removeprefix('PS')}"
    row = await session.get(Part, ps)
    return _part_to_result(row) if row else None


async def list_featured_parts(
    session: AsyncSession,
    *,
    appliance_type: str | None = None,
    limit: int = 20,
) -> list[PartResult]:
    stmt = select(Part)
    if appliance_type:
        stmt = stmt.where(Part.appliance_type == appliance_type.lower())
    stmt = stmt.order_by(Part.rating.desc().nullslast(), Part.name).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return [_part_to_result(p) for p in rows]


async def search_parts(
    session: AsyncSession,
    *,
    query: str,
    appliance_type: str | None = None,
    limit: int = 8,
) -> list[PartResult]:
    q = query.strip()
    if not q:
        return []

    stmt = select(Part)
    if appliance_type:
        stmt = stmt.where(Part.appliance_type == appliance_type.lower())

    ps_match = PS_RE.search(q)
    if ps_match:
        stmt = stmt.where(Part.ps_number == ps_match.group(0).upper())
    else:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Part.name.ilike(pattern),
                Part.description.ilike(pattern),
                Part.manufacturer_part_number.ilike(pattern),
                Part.symptoms_fixed.astext.ilike(pattern),
            )
        )

    stmt = stmt.order_by(Part.rating.desc().nullslast(), Part.name).limit(limit)
    rows = (await session.scalars(stmt)).all()
    return [_part_to_result(p) for p in rows]


async def check_compatibility(
    session: AsyncSession,
    *,
    ps_number: str,
    model_number: str,
) -> CompatibilityResult:
    ps = ps_number.strip().upper()
    model = model_number.strip().upper()

    part = await session.get(Part, ps)
    if part is None:
        return CompatibilityResult(
            ps_number=ps,
            model_number=model,
            compatible=None,
            message=f"Part {ps} was not found in the catalog.",
        )

    link = await session.scalar(
        select(PartModelCompatibility).where(
            PartModelCompatibility.part_ps_number == ps,
            PartModelCompatibility.model_number == model,
        )
    )
    if link is None:
        return CompatibilityResult(
            ps_number=ps,
            model_number=model,
            compatible=False,
            part_name=part.name,
            message=f"{ps} is not listed as compatible with model {model}.",
        )

    return CompatibilityResult(
        ps_number=ps,
        model_number=model,
        compatible=link.compatible,
        part_name=part.name,
        message=f"{ps} is compatible with model {model}.",
    )


def _steps_from_text(text: str) -> list[InstallStep]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    steps: list[InstallStep] = []
    for idx, line in enumerate(lines, start=1):
        cleaned = re.sub(r"^\d+[\).\s]+", "", line)
        steps.append(InstallStep(order=idx, text=cleaned))
    return steps


async def get_installation_guide(
    session: AsyncSession,
    *,
    ps_number: str,
) -> InstallationGuide | None:
    ps = ps_number.strip().upper()
    part = await session.get(Part, ps)
    if part is None:
        return None

    doc = await session.scalar(
        select(Document)
        .where(
            Document.part_ps_number == ps,
            Document.doc_type == "install_guide",
        )
        .limit(1)
    )

    steps: list[InstallStep] = []
    sources: list[str] = []
    if doc and doc.content:
        steps = _steps_from_text(doc.content)
        if doc.source_url:
            sources.append(doc.source_url)
    elif part.install_instructions:
        steps = _steps_from_text(part.install_instructions)
        if part.source_url:
            sources.append(part.source_url)

    if not steps and part.install_difficulty:
        steps = [
            InstallStep(
                order=1,
                text=(
                    f"Follow the manufacturer instructions for {part.name}. "
                    f"Rated {part.install_difficulty}."
                ),
            )
        ]

    return InstallationGuide(
        ps_number=ps,
        part_name=part.name,
        difficulty=part.install_difficulty,
        time_minutes=part.install_time_minutes,
        video_url=part.video_url,
        steps=steps,
        sources=sources,
    )


async def diagnose_symptom(
    session: AsyncSession,
    *,
    symptom: str,
    appliance_type: str | None = None,
    brand: str | None = None,
    limit: int = 6,
) -> DiagnosisResult:
    pattern = f"%{symptom.strip()}%"
    stmt = select(Part).where(Part.symptoms_fixed.astext.ilike(pattern))
    if appliance_type:
        stmt = stmt.where(Part.appliance_type == appliance_type.lower())
    if brand:
        stmt = stmt.where(Part.brand.ilike(brand))

    stmt = stmt.order_by(Part.rating.desc().nullslast()).limit(limit)
    parts = (await session.scalars(stmt)).all()

    candidates = [
        DiagnosisCandidate(
            ps_number=p.ps_number,
            name=p.name,
            relevance=symptom,
            price_cents=p.price_cents,
            in_stock=p.in_stock,
        )
        for p in parts
    ]

    references: list[str] = []
    if parts:
        doc = await session.scalar(
            select(Document)
            .where(
                Document.part_ps_number == parts[0].ps_number,
                Document.doc_type == "troubleshooting",
            )
            .limit(1)
        )
        if doc and doc.source_url:
            references.append(doc.source_url)

    return DiagnosisResult(
        symptom=symptom,
        appliance_type=appliance_type,
        brand=brand,
        likely_causes=[symptom] if candidates else [],
        candidate_parts=candidates,
        references=references,
    )
