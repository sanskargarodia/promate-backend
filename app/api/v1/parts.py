"""Catalog read API for storefront and debugging."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.catalog import CompatibilityResult, PartResult
from app.services import catalog as catalog_svc

router = APIRouter(prefix="/parts", tags=["parts"])


@router.get("", response_model=list[PartResult])
async def list_parts(
    q: str = Query("", max_length=200),
    appliance_type: str | None = Query(None, pattern="^(refrigerator|dishwasher)$"),
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[PartResult]:
    if not q.strip():
        return await catalog_svc.list_featured_parts(
            session, appliance_type=appliance_type, limit=limit
        )
    return await catalog_svc.search_parts(
        session, query=q, appliance_type=appliance_type, limit=limit
    )


@router.get("/{ps_number}", response_model=PartResult)
async def get_part(
    ps_number: str,
    session: AsyncSession = Depends(get_session),
) -> PartResult:
    part = await catalog_svc.get_part(session, ps_number)
    if part is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return part


@router.get("/{ps_number}/compatibility/{model_number}", response_model=CompatibilityResult)
async def part_compatibility(
    ps_number: str,
    model_number: str,
    session: AsyncSession = Depends(get_session),
) -> CompatibilityResult:
    return await catalog_svc.check_compatibility(
        session, ps_number=ps_number, model_number=model_number
    )
