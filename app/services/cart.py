"""In-memory shopping cart (session-scoped; Stripe checkout in a later phase)."""

from __future__ import annotations

from threading import Lock
from uuid import uuid4

from pydantic import BaseModel, Field

from app.schemas.catalog import PartResult


class CartLineItem(BaseModel):
    ps_number: str
    quantity: int = Field(ge=1, le=99)
    part: PartResult | None = None


class Cart(BaseModel):
    session_id: str
    items: list[CartLineItem] = Field(default_factory=list)


_lock = Lock()
_carts: dict[str, Cart] = {}


def get_or_create_cart(session_id: str | None) -> Cart:
    with _lock:
        sid = session_id or str(uuid4())
        if sid not in _carts:
            _carts[sid] = Cart(session_id=sid)
        return _carts[sid]


def save_cart(cart: Cart) -> None:
    with _lock:
        _carts[cart.session_id] = cart
