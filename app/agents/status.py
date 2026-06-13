"""User-facing activity labels streamed to the chat UI during agent turns."""

from __future__ import annotations

from langgraph.config import get_stream_writer

# Node-level defaults (shown when a graph step begins).
NODE_STATUS: dict[str, str] = {
    "supervisor": "Understanding your request…",
    "refusal": "Preparing response…",
    "clarification": "Preparing response…",
    "transactional_tools": "Looking up catalog data…",
    "product_search_worker": "Searching the parts catalog…",
    "compatibility_worker": "Checking compatibility with your model…",
    "installation_worker": "Finding installation instructions…",
    "troubleshooting_worker": "Diagnosing possible causes…",
    "transaction_worker": "Preparing your order details…",
    "order_status_worker": "Looking up order status…",
    "suggest_follow_ups": "Preparing follow-up suggestions…",
    "composer": "Writing your answer…",
    "output_guardrail": "Verifying response…",
}

# Tool-level labels (more specific than the node default).
TOOL_STATUS: dict[str, str] = {
    "get_part_details": "Fetching part details from catalog…",
    "search_parts": "Searching the parts catalog…",
    "get_order_status": "Looking up order status…",
    "purchase_handoff": "Preparing your PartSelect.com link…",
}

SUPPORT_STATUS: dict[str, str] = {
    "compatibility": "Checking compatibility with your model…",
    "installation": "Finding installation instructions…",
    "diagnosis": "Diagnosing possible causes…",
    "documents": "Searching support articles…",
}


def tool_status(name: str, **context: str) -> str:
    """Return a tool label, optionally interpolating context like part or order ids."""
    if name == "get_part_details":
        part_id = context.get("part_id")
        if part_id:
            return f"Fetching details for {part_id} from catalog…"
    if name == "get_order_status":
        order_id = context.get("order_id")
        if order_id:
            return f"Looking up order {order_id}…"
    if name == "search_parts":
        return TOOL_STATUS["search_parts"]
    return TOOL_STATUS.get(name, "Working on your request…")


def emit_status(message: str) -> None:
    """Push a status update to the chat SSE stream (no-op if streaming is unavailable)."""
    if not message:
        return
    try:
        writer = get_stream_writer()
        writer({"message": message})
    except Exception:  # noqa: BLE001
        return
