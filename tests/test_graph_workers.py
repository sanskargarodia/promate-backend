"""Tests for per-intent worker graph routing."""

from __future__ import annotations

from app.agents.graph import _route_after_supervisor
from app.agents.state import AgentState


def test_route_order_status_worker() -> None:
    state: AgentState = {
        "messages": [{"role": "user", "content": "Status of order ORD-DEMO-001"}],
        "intent": "product_search",
    }
    assert _route_after_supervisor(state) == "order_status_worker"


def test_route_compatibility_worker() -> None:
    state: AgentState = {
        "messages": [
            {"role": "user", "content": "Is PS11752778 compatible with WDT780SAEM1?"},
        ],
        "intent": "compatibility",
        "ps_number": "PS11752778",
        "model_number": "WDT780SAEM1",
    }
    assert _route_after_supervisor(state) == "compatibility_worker"


def test_route_troubleshooting_worker() -> None:
    state: AgentState = {
        "messages": [
            {"role": "user", "content": "Whirlpool ice maker not working"},
        ],
        "intent": "troubleshooting",
        "brand": "Whirlpool",
        "appliance_type": "refrigerator",
    }
    assert _route_after_supervisor(state) == "troubleshooting_worker"


def test_route_transaction_worker() -> None:
    state: AgentState = {
        "messages": [{"role": "user", "content": "I'm ready to buy PS11752778"}],
        "intent": "transaction",
        "ps_number": "PS11752778",
    }
    assert _route_after_supervisor(state) == "transaction_worker"
