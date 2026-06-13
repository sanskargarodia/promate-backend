"""Transactional tool routing tests."""

from app.agents.tool_router import detect_purchase_intent, plan_transactional_tools


def test_plan_purchase_handoff() -> None:
    calls = plan_transactional_tools(
        {
            "messages": [{"role": "user", "content": "I'm ready to buy PS11752778"}],
            "ps_number": "PS11752778",
        }
    )
    assert calls[0].name == "get_part_details"
    assert calls[1].name == "purchase_handoff"
    assert calls[1].arguments["part_id"] == "PS11752778"


def test_detect_purchase_intent() -> None:
    assert detect_purchase_intent("I'm ready to order this part")
    assert not detect_purchase_intent("What is the price of PS11752778?")


def test_plan_order_status() -> None:
    calls = plan_transactional_tools(
        {"messages": [
            {"role": "user", "content": "What is my order status ORD-DEMO-001?"}]}
    )
    assert calls[0].name == "get_order_status"


def test_plan_troubleshooting_search() -> None:
    calls = plan_transactional_tools(
        {
            "messages": [{"role": "user", "content": "My fridge ice maker is not working"}],
            "intent": "troubleshooting",
            "appliance_type": "refrigerator",
        }
    )
    assert calls[0].name == "search_parts"
    assert calls[0].arguments["appliance_type"] == "refrigerator"
