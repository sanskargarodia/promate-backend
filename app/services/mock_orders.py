"""Mock order status lookups for demo conversations."""

from __future__ import annotations

from app.schemas.transactional import OrderStatusResult

_MOCK_ORDERS: dict[str, dict[str, object]] = {
    "ORD-DEMO-001": {
        "status": "shipped",
        "total_cents": 3608,
        "message": "Demo order ORD-DEMO-001 has shipped.",
    },
    "ORD-DEMO-002": {
        "status": "processing",
        "total_cents": 5200,
        "message": "Demo order ORD-DEMO-002 is being processed.",
    },
}


async def get_order_status(_db: object, order_id: str) -> OrderStatusResult:
    order_id = order_id.strip().upper()

    if order_id in _MOCK_ORDERS:
        mock = _MOCK_ORDERS[order_id]
        return OrderStatusResult(
            order_id=order_id,
            status=str(mock["status"]),
            total_cents=int(mock["total_cents"]),  # type: ignore[arg-type]
            message=str(mock["message"]),
        )

    return OrderStatusResult(
        order_id=order_id,
        status="unknown",
        found=False,
        message=f"No order found for {order_id}.",
    )
