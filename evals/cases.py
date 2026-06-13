"""Canonical demo and regression cases (AGENT.md §5)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SmokeCase:
    id: str
    message: str
    state: dict = field(default_factory=dict)
    expected_tools: tuple[str, ...] = ()
    in_scope: bool = True


# Deterministic tool-routing regression suite (no LLM required).
SMOKE_CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        id="install_guide",
        message="How can I install part number PS11752778?",
        state={"intent": "installation", "ps_number": "PS11752778"},
        expected_tools=("get_part_details",),
    ),
    SmokeCase(
        id="compatibility",
        message="Is PS11752778 compatible with WDT780SAEM1?",
        state={"intent": "compatibility", "ps_number": "PS11752778",
               "model_number": "WDT780SAEM1"},
        expected_tools=("get_part_details",),
    ),
    SmokeCase(
        id="troubleshooting",
        message="The ice maker on my Whirlpool fridge is not working. How can I fix it?",
        state={"intent": "troubleshooting",
               "appliance_type": "refrigerator", "brand": "Whirlpool"},
        expected_tools=("search_parts",),
    ),
    SmokeCase(
        id="symptom_search",
        message="My dishwasher won't drain — what part might I need?",
        state={"intent": "troubleshooting", "appliance_type": "dishwasher"},
        expected_tools=("search_parts",),
    ),
    SmokeCase(
        id="purchase_handoff",
        message="I'm ready to buy PS11752778",
        state={"ps_number": "PS11752778"},
        expected_tools=("get_part_details", "purchase_handoff"),
    ),
    SmokeCase(
        id="order_status",
        message="What is the status of order ORD-DEMO-001?",
        expected_tools=("get_order_status",),
    ),
    SmokeCase(
        id="part_lookup",
        message="Tell me about PS11752778",
        state={"intent": "product_search", "ps_number": "PS11752778"},
        expected_tools=("get_part_details",),
    ),
)

GUARDRAIL_CASES: tuple[SmokeCase, ...] = (
    SmokeCase(
        id="refuse_washing_machine",
        message="My washing machine is leaking",
        in_scope=False,
    ),
    SmokeCase(
        id="refuse_coding",
        message="Write me a Python script to scrape Amazon",
        in_scope=False,
    ),
)
