"""Tests for user-facing activity status labels."""

from __future__ import annotations

from app.agents.status import tool_status


def test_tool_status_part_details_includes_part_id() -> None:
    assert tool_status("get_part_details", part_id="PS11752778") == (
        "Fetching details for PS11752778 from catalog…"
    )


def test_tool_status_order_status_includes_order_id() -> None:
    assert tool_status("get_order_status", order_id="ORD-DEMO-001") == (
        "Looking up order ORD-DEMO-001…"
    )
