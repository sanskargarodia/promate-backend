"""Agent routing heuristics (no LLM required)."""

from app.agents.nodes import _heuristic_route


def test_heuristic_install_intent() -> None:
    routed = _heuristic_route("How can I install part number PS11752778?")
    assert routed["intent"] == "installation"
    assert routed["ps_number"] == "PS11752778"


def test_heuristic_compatibility_intent() -> None:
    routed = _heuristic_route("Is PS11752778 compatible with my WDT780SAEM1 model?")
    assert routed["intent"] == "compatibility"
    assert routed["model_number"] == "WDT780SAEM1"


def test_heuristic_troubleshooting_intent() -> None:
    routed = _heuristic_route("My Whirlpool fridge ice maker is not working")
    assert routed["intent"] == "troubleshooting"
    assert routed["brand"] == "Whirlpool"
