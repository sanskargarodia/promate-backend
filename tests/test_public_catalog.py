"""Tests for public catalog CSV import."""

from ingestion.persist import _pick_source_url
from ingestion.public_catalog import row_to_scraped_part

CANONICAL = (
    "https://www.partselect.com/PS11752778-Whirlpool-WPW10321304-Refrigerator-Door-Shelf-Bin.htm"
)
SHORT = "https://www.partselect.com/PS11752778.htm"


def test_pick_source_url_prefers_canonical_over_short() -> None:
    assert _pick_source_url(CANONICAL, SHORT) == CANONICAL
    assert _pick_source_url(SHORT, CANONICAL) == CANONICAL


def test_row_to_scraped_part_refrigerator() -> None:
    row = {
        "part_name": "Refrigerator Door Shelf Bin",
        "part_id": "PS11752778",
        "mpn_id": "WPW10321304",
        "part_price": "47.40",
        "install_difficulty": "Really Easy",
        "install_time": "Less than 15 mins",
        "symptoms": "Door won't open or close | Ice maker not making ice",
        "appliance_type": "refrigerator",
        "replace_parts": "W10321304, WPW10321304",
        "brand": "Whirlpool",
        "in_stock": "1",
        "install_video_url": "https://www.youtube.com/watch?v=abc",
        "product_url": "https://www.partselect.com/PS11752778.htm",
        "description": "Door bin OEM replacement.",
        "compatible_models": "WDT780SAEM1 | ABC123",
        "image_url": "https://example.com/img.jpg",
        "rating": "4.9",
        "review_count": "351",
    }
    part = row_to_scraped_part(row)
    assert part is not None
    assert part.ps_number == "PS11752778"
    assert part.appliance_type == "refrigerator"
    assert part.price_cents == 4740
    assert "WDT780SAEM1" in part.compatible_models


def test_row_to_scraped_part_skips_other_appliances() -> None:
    row = {"part_id": "PS1", "appliance_type": "range"}
    assert row_to_scraped_part(row) is None
