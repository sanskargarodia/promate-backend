"""Agent tools — thin async facades over catalog services (Pydantic out, never prose)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.catalog import (
    CompatibilityResult,
    DiagnosisResult,
    DocumentChunk,
    InstallationGuide,
    PartResult,
)
from app.services import catalog as catalog_svc
from app.services import retrieval as retrieval_svc


async def search_parts(
    session: AsyncSession,
    query: str,
    *,
    appliance_type: str | None = None,
    limit: int = 8,
) -> list[PartResult]:
    return await catalog_svc.search_parts(
        session, query=query, appliance_type=appliance_type, limit=limit
    )


async def get_part(session: AsyncSession, ps_number: str) -> PartResult | None:
    return await catalog_svc.get_part(session, ps_number)


async def check_compatibility(
    session: AsyncSession,
    ps_number: str,
    model_number: str,
) -> CompatibilityResult:
    return await catalog_svc.check_compatibility(
        session, ps_number=ps_number, model_number=model_number
    )


async def get_installation_guide(
    session: AsyncSession,
    ps_number: str,
) -> InstallationGuide | None:
    return await catalog_svc.get_installation_guide(session, ps_number=ps_number)


async def diagnose_symptom(
    session: AsyncSession,
    symptom: str,
    *,
    appliance_type: str | None = None,
    brand: str | None = None,
) -> DiagnosisResult:
    return await catalog_svc.diagnose_symptom(
        session, symptom=symptom, appliance_type=appliance_type, brand=brand
    )


async def search_documents(
    session: AsyncSession,
    query: str,
    *,
    doc_type: str | None = None,
    part_ps_number: str | None = None,
    limit: int = 5,
) -> list[DocumentChunk]:
    return await retrieval_svc.search_documents(
        session,
        query=query,
        doc_type=doc_type,
        part_ps_number=part_ps_number,
        limit=limit,
    )
