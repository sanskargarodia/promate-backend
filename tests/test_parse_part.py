"""Parser tests against recorded PartSelect HTML (real page snapshot)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.parse import parse_part_page

FIXTURE = Path(__file__).parent / "fixtures" / "part_PS11752778.html"


@pytest.fixture
def part_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_ps11752778(part_html: str) -> None:
    part = parse_part_page(
        part_html,
        source_url=(
            "https://www.partselect.com/PS11752778-Whirlpool-WPW10321304-"
            "Refrigerator-Door-Shelf-Bin.htm"
        ),
    )
    assert part.ps_number == "PS11752778"
    assert part.manufacturer_part_number == "WPW10321304"
    assert "Door Shelf Bin" in part.name
    assert part.appliance_type == "refrigerator"
    assert part.price_cents == 3608
    assert part.in_stock is True
    assert part.install_difficulty == "Really Easy"
    assert part.install_time_minutes == 15
    assert part.video_url is not None
    assert part.description
