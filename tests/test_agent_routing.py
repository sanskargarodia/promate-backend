"""Agent routing heuristics (no LLM required)."""

from app.agents.nodes import _heuristic_route, _merge_route_results


def test_heuristic_install_intent() -> None:
    routed = _heuristic_route("How can I install part number PS11752778?")
    assert routed["intent"] == "installation"
    assert routed["ps_number"] == "PS11752778"


def test_heuristic_install_pronoun_uses_session_ps() -> None:
    state = {
        "session_context": {"ps_number": "PS11752778", "active_intent": "product_search"},
        "identified_part_id": "PS11752778",
    }
    routed = _heuristic_route("can you tell about its installation", state)
    assert routed["intent"] == "installation"
    assert routed["ps_number"] == "PS11752778"


def test_heuristic_compatibility_intent() -> None:
    routed = _heuristic_route(
        "Is PS11752778 compatible with my WDT780SAEM1 model?")
    assert routed["intent"] == "compatibility"
    assert routed["model_number"] == "WDT780SAEM1"


def test_heuristic_troubleshooting_intent() -> None:
    routed = _heuristic_route("My Whirlpool fridge ice maker is not working")
    assert routed["intent"] == "troubleshooting"
    assert routed["brand"] == "Whirlpool"


def test_heuristic_diagnose_phrase() -> None:
    routed = _heuristic_route("help me diagnose")
    assert routed["intent"] == "troubleshooting"


def test_heuristic_typo_diagnose() -> None:
    routed = _heuristic_route("help me diafnose the problem")
    assert routed["intent"] == "troubleshooting"


def test_heuristic_transaction_intent() -> None:
    routed = _heuristic_route("I'm ready to buy PS11752778")
    assert routed["intent"] == "transaction"
    assert routed["ps_number"] == "PS11752778"


def test_heuristic_keeps_troubleshooting_from_session() -> None:
    state = {
        "session_context": {"active_intent": "troubleshooting", "appliance_type": "refrigerator"},
    }
    routed = _heuristic_route("weird noise", state)
    assert routed["intent"] == "troubleshooting"


def test_merge_route_fills_appliance_when_llm_omits_it() -> None:
    state = {"session_context": {"active_intent": "troubleshooting"}}
    heuristic = _heuristic_route(
        "My refrigerator is making weird noises", state)
    llm = {"intent": "troubleshooting", "appliance_type": None,
           "ps_number": None, "model_number": None, "brand": None}
    merged = _merge_route_results(llm, heuristic, state=state)
    assert merged["intent"] == "troubleshooting"
    assert merged["appliance_type"] == "refrigerator"


def test_merge_route_prefers_heuristic_troubleshooting_over_product_search() -> None:
    state = {}
    heuristic = _heuristic_route("help me diafnose the problem", state)
    llm = {"intent": "product_search", "appliance_type": None}
    merged = _merge_route_results(llm, heuristic, state=state)
    assert merged["intent"] == "troubleshooting"
