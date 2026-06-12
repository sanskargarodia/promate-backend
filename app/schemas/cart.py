"""Cart schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AddToCartRequest(BaseModel):
    ps_number: str
    quantity: int = Field(default=1, ge=1, le=99)
    session_id: str | None = None


class CartResponse(BaseModel):
    session_id: str
    items: list[dict[str, object]]
    item_count: int
