"""Product card selection tests."""

from app.agents.product_cards import select_product_cards

_PART = {
    "found": True,
    "part_id": "PS11752778",
    "name": "Door Shelf Bin",
    "appliance_type": "refrigerator",
    "price_cents": 3608,
    "in_stock": True,
    "image_urls": [],
    "source_url": "https://www.partselect.com/PS11752778.htm",
}

_EXTRA = {
    "part_id": "PS99999999",
    "name": "Unrelated Part",
    "appliance_type": "refrigerator",
    "price_cents": 999,
    "in_stock": True,
    "image_urls": [],
}

_HINGE = {
    "part_id": "PS11739891",
    "name": "Center Door Hinge",
    "appliance_type": "refrigerator",
    "price_cents": 4423,
    "in_stock": True,
    "image_urls": [],
}


def test_part_lookup_shows_primary_only_not_search_extras() -> None:
    cards = select_product_cards(
        {
            "intent": "product_search",
            "final_response": "Here is PS11752778.",
            "tool_payload": {
                "part": _PART,
                "matching_parts": [_EXTRA, {**_EXTRA, "part_id": "PS88888888"}],
                "related_parts": [_EXTRA, _HINGE],
            },
        }
    )
    assert len(cards) == 1
    assert cards[0]["part"]["ps_number"] == "PS11752778"
    assert cards[0]["card_role"] == "primary"


def test_recommended_card_only_when_mentioned_in_answer() -> None:
    cards = select_product_cards(
        {
            "intent": "product_search",
            "final_response": (
                "PS11752778 is the door shelf bin. If the door sags, check PS11739891."
            ),
            "tool_payload": {
                "part": _PART,
                "related_parts": [_EXTRA, _HINGE],
            },
        }
    )
    assert len(cards) == 2
    assert cards[0]["card_role"] == "primary"
    assert cards[1]["part"]["ps_number"] == "PS11739891"
    assert cards[1]["card_role"] == "recommended"
    assert all(c["part"]["ps_number"] != "PS99999999" for c in cards)


def test_troubleshooting_prefers_diagnosis_candidates() -> None:
    cards = select_product_cards(
        {
            "intent": "troubleshooting",
            "final_response": "Try PS11111111 or PS22222222.",
            "tool_payload": {
                "diagnosis": {
                    "candidate_parts": [
                        {
                            "ps_number": "PS11111111",
                            "name": "Ice Maker",
                            "price_cents": 1000,
                            "in_stock": True,
                        },
                        {
                            "ps_number": "PS22222222",
                            "name": "Water Valve",
                            "price_cents": 2000,
                            "in_stock": True,
                        },
                    ]
                },
                "matching_parts": [_EXTRA],
            },
        }
    )
    assert len(cards) == 2
    assert all(c["card_role"] == "recommended" for c in cards)
    assert all(c["part"]["ps_number"] != "PS99999999" for c in cards)


def test_refusal_emits_no_cards() -> None:
    assert select_product_cards({"intent": "refusal", "refused": True}) == []
