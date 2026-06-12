"""
Transactional agent tools — the only source of inventory, pricing, and handoff URLs.

The LLM must never invent part numbers or prices; it composes prose from these payloads.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.transaction_state import TransactionPhase, TransactionStateMachine
from app.schemas.catalog import PartResult
from app.schemas.transactional import (
    PartDetails,
    PartNotFound,
    PurchaseHandoffPayload,
    SearchPartsResult,
)
from app.services import catalog as catalog_svc
from app.services import mock_orders as orders_svc
from app.services import retrieval as retrieval_svc

PS_RE = re.compile(r"\b(PS\d+)\b", re.I)


def _normalize_part_id(part_id: str) -> str:
    token = part_id.strip().upper()
    if not token.startswith("PS"):
        token = f"PS{token.removeprefix('PS')}"
    return token


def _part_result_to_details(part: PartResult) -> PartDetails:
    return PartDetails(
        part_id=part.ps_number,
        name=part.name,
        description=None,
        price_cents=part.price_cents,
        in_stock=part.in_stock,
        brand=part.brand,
        appliance_type=part.appliance_type,
        image_urls=list(part.image_urls or []),
        source_url=part.source_url,
        found=True,
    )


async def get_part_details(db: AsyncSession, part_id: str) -> PartDetails | PartNotFound:
    """Fetch price, stock, and metadata for a PS number from the catalog."""
    ps = _normalize_part_id(part_id)
    part = await catalog_svc.get_part(db, ps)
    if part is None:
        return PartNotFound(part_id=ps)
    return _part_result_to_details(part)


async def search_parts(
    db: AsyncSession,
    symptom_or_model: str,
    *,
    appliance_type: str | None = None,
    limit: int = 8,
) -> SearchPartsResult:
    """Map symptoms or model text to catalog parts (keyword + semantic retrieval)."""
    query = symptom_or_model.strip()
    if not query:
        return SearchPartsResult(query=query, parts=[], found=False)

    keyword_hits = await catalog_svc.search_parts(
        db, query=query, appliance_type=appliance_type, limit=limit
    )
    seen: set[str] = set()
    parts: list[PartDetails] = []

    for hit in keyword_hits:
        if hit.ps_number in seen:
            continue
        seen.add(hit.ps_number)
        parts.append(_part_result_to_details(hit))

    if len(parts) < limit:
        docs = await retrieval_svc.search_documents(db, query=query, limit=limit)
        for doc in docs:
            ps = doc.part_ps_number
            if not ps or ps in seen:
                continue
            part = await catalog_svc.get_part(db, ps)
            if part is None:
                continue
            seen.add(ps)
            parts.append(_part_result_to_details(part))
            if len(parts) >= limit:
                break

    return SearchPartsResult(
        query=query,
        parts=parts,
        found=len(parts) > 0,
    )


async def get_order_status(db: AsyncSession, order_id: str):
    return await orders_svc.get_order_status(db, order_id)


async def prepare_purchase_handoff(
    db: AsyncSession,
    *,
    part_id: str | None,
    machine: TransactionStateMachine,
) -> PurchaseHandoffPayload:
    """Build a PartSelect.com handoff when the customer is ready to buy."""
    if not part_id:
        return PurchaseHandoffPayload(
            allowed=False,
            reason="Please tell me which part (PS number) you'd like to order.",
        )

    if machine.phase not in {
        TransactionPhase.IDENTIFIED,
        TransactionPhase.COMPATIBILITY_CONFIRMED,
        TransactionPhase.PURCHASE_READY,
    }:
        return PurchaseHandoffPayload(
            allowed=False,
            reason=machine.handoff_blocked_reason(),
        )

    ps = _normalize_part_id(part_id)
    part = await catalog_svc.get_part(db, ps)
    if part is None:
        return PurchaseHandoffPayload(
            allowed=False,
            reason="I cannot find that part in our catalog",
        )

    machine.after_purchase_intent()
    payload = PurchaseHandoffPayload(
        allowed=True,
        ps_number=part.ps_number,
        source_url=part.source_url,
        price_cents=part.price_cents,
        in_stock=part.in_stock,
        reason=f"Order {part.ps_number} on PartSelect.com",
    )
    machine.after_handoff(payload)
    return payload
