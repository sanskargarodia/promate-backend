"""Tests for category/repair-help discovery parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.discover import enrich_models_from_cached_parts
from ingestion.parse import discover_from_page, parse_repair_help_page
from ingestion.seeds import manifest_for_ps_numbers, merge_manifests
from ingestion.types import CrawlManifest

CATEGORY_FIXTURE = Path(__file__).parent / "fixtures" / \
    "category_refrigerator_parts.html"
REPAIR_FIXTURE = Path(__file__).parent / "fixtures" / \
    "repair_help_refrigerator_not_cooling.html"
PART_FIXTURE = Path(__file__).parent / "fixtures" / "part_PS11752778.html"


@pytest.fixture
def category_html() -> str:
    return CATEGORY_FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def repair_html() -> str:
    return REPAIR_FIXTURE.read_text(encoding="utf-8")


def test_discover_from_category_page(category_html: str) -> None:
    discovery = discover_from_page(
        category_html,
        source_url="https://www.partselect.com/Refrigerator-Parts.htm",
    )
    assert "https://www.partselect.com/PS11752778" in discovery.part_urls[0]
    assert any("WDT780SAEM1" in url for url in discovery.model_urls)
    assert any("Refrigerator-Shelves" in url for url in discovery.category_urls)
    assert not any("Dryer" in url for url in discovery.category_urls)
    assert any("Not-Cooling" in url for url in discovery.repair_help_urls)
    assert any("Offset=24" in url for url in discovery.pagination_urls)


def test_parse_repair_help_page(repair_html: str) -> None:
    docs = parse_repair_help_page(
        repair_html,
        source_url="https://www.partselect.com/Repair/Refrigerator/Not-Cooling/",
    )
    assert len(docs) == 1
    doc = docs[0]
    assert doc.doc_type == "troubleshooting"
    assert doc.part_ps_number is None
    assert "not cooling" in doc.title.lower()
    assert "condenser coils" in doc.content.lower()
    assert doc.metadata.get("appliance_type") == "refrigerator"
    assert "PS11752778" in doc.metadata.get("linked_ps_numbers", [])


def test_manifest_for_ps_numbers() -> None:
    manifest = manifest_for_ps_numbers(["11752778", "PS11752778"])
    assert manifest.part_urls == ["https://www.partselect.com/PS11752778.htm"]


def test_enrich_models_from_cached_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    part_html = PART_FIXTURE.read_text(encoding="utf-8")
    manifest = CrawlManifest(
        part_urls=["https://www.partselect.com/PS11752778.htm"],
        model_urls=["https://www.partselect.com/Models/WDT780SAEM1/"],
    )

    def fake_read(url: str, *, kind: str) -> str | None:
        if kind == "parts" and "PS11752778" in url:
            return part_html
        return None

    monkeypatch.setattr("ingestion.discover.read_cached", fake_read)
    enriched = enrich_models_from_cached_parts(manifest)
    assert "https://www.partselect.com/Models/WDT780SAEM1/" in enriched.model_urls
    assert len(enriched.model_urls) > 1


def test_merge_manifests_includes_repair_help() -> None:
    merged = merge_manifests(
        CrawlManifest(repair_help_urls=[
                      "https://www.partselect.com/Repair/Refrigerator/"]),
        CrawlManifest(repair_help_urls=[
                      "https://www.partselect.com/Repair/Dishwasher/"]),
    )
    assert len(merged.repair_help_urls) == 2
