"""Session cart API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.cart import AddToCartRequest, CartResponse
from app.services import cart as cart_svc
from app.services import catalog as catalog_svc

router = APIRouter(prefix="/cart", tags=["cart"])


def _cart_to_response(cart: cart_svc.Cart) -> CartResponse:
    items = [
        {
            "ps_number": i.ps_number,
            "quantity": i.quantity,
            "part": i.part.model_dump() if i.part else None,
        }
        for i in cart.items
    ]
    return CartResponse(
        session_id=cart.session_id,
        items=items,
        item_count=sum(i.quantity for i in cart.items),
    )


@router.get("", response_model=CartResponse)
async def get_cart(
    session_id: str | None = Query(None),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
) -> CartResponse:
    cart = cart_svc.get_or_create_cart(session_id or x_session_id)
    return _cart_to_response(cart)


@router.post("/items", response_model=CartResponse)
async def add_to_cart(
    body: AddToCartRequest,
    db: AsyncSession = Depends(get_session),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
) -> CartResponse:
    cart = cart_svc.get_or_create_cart(body.session_id or x_session_id)
    part = await catalog_svc.get_part(db, body.ps_number)
    if part is None:
        raise HTTPException(status_code=404, detail="Part not found")

    existing = next((i for i in cart.items if i.ps_number == part.ps_number), None)
    if existing:
        existing.quantity = min(99, existing.quantity + body.quantity)
        existing.part = part
    else:
        cart.items.append(
            cart_svc.CartLineItem(
                ps_number=part.ps_number,
                quantity=body.quantity,
                part=part,
            )
        )

    cart_svc.save_cart(cart)
    return _cart_to_response(cart)
