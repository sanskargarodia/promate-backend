"""Structured payloads returned by transactional agent tools (never LLM prose)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PartDetails(BaseModel):
    """Ground-truth part row from catalog (CSV → Postgres)."""

    part_id: str
    name: str
    description: str | None = None
    price_cents: int | None = None
    in_stock: bool = False
    brand: str | None = None
    appliance_type: str
    image_urls: list[str] = Field(default_factory=list)
    source_url: str | None = None
    found: bool = True


class PartNotFound(BaseModel):
    part_id: str
    found: bool = False
    message: str = "I cannot find that part in our catalog"


class SearchPartsResult(BaseModel):
    query: str
    parts: list[PartDetails] = Field(default_factory=list)
    found: bool = True


class OrderStatusResult(BaseModel):
    order_id: str
    status: str
    found: bool = True
    total_cents: int | None = None
    message: str


class PurchaseHandoffPayload(BaseModel):
    action: Literal["purchase_handoff"] = "purchase_handoff"
    allowed: bool
    ps_number: str | None = None
    source_url: str | None = None
    price_cents: int | None = None
    in_stock: bool | None = None
    reason: str | None = None
