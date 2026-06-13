"""Regression anchors and manifest helpers for ingestion (no live site crawl)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ingestion.types import CrawlManifest

BASE_URL = "https://www.partselect.com"
SEEDS_PATH = Path(__file__).resolve().parent / "seeds" / "catalog.json"


def load_catalog_seeds() -> dict[str, object]:
    if not SEEDS_PATH.is_file():
        return {}
    return json.loads(SEEDS_PATH.read_text(encoding="utf-8"))


def regression_part_ps_numbers() -> list[str]:
    seeds = load_catalog_seeds()
    anchors = seeds.get("regression_anchors", {})
    if isinstance(anchors, dict):
        parts = anchors.get("parts", [])
        if isinstance(parts, list):
            return [str(p).upper() for p in parts]
    return []


def category_root_urls() -> list[str]:
    seeds = load_catalog_seeds()
    roots = seeds.get("category_roots", [])
    if isinstance(roots, list) and roots:
        return [str(u) for u in roots]
    return [
        f"{BASE_URL}/Refrigerator-Parts.htm",
        f"{BASE_URL}/Dishwasher-Parts.htm",
    ]


def repair_help_root_urls() -> list[str]:
    seeds = load_catalog_seeds()
    roots = seeds.get("repair_help_roots", [])
    if isinstance(roots, list) and roots:
        return [str(u) for u in roots]
    return [
        f"{BASE_URL}/Repair/Refrigerator/",
        f"{BASE_URL}/Repair/Dishwasher/",
    ]


def normalize_part_url(url: str) -> str | None:
    match = re.search(r"PS(\d+)", url, re.I)
    if not match:
        return None
    return f"{BASE_URL}/PS{match.group(1)}.htm"


def merge_manifests(*manifests: CrawlManifest) -> CrawlManifest:
    parts: set[str] = set()
    models: set[str] = set()
    categories: set[str] = set()
    repair_help: set[str] = set()
    for manifest in manifests:
        parts.update(manifest.part_urls)
        models.update(manifest.model_urls)
        categories.update(manifest.category_urls)
        repair_help.update(manifest.repair_help_urls)
    return CrawlManifest(
        part_urls=sorted(parts),
        model_urls=sorted(models),
        category_urls=sorted(categories),
        repair_help_urls=sorted(repair_help),
    )


def manifest_for_ps_numbers(ps_numbers: list[str]) -> CrawlManifest:
    part_urls = []
    for raw in ps_numbers:
        normalized = normalize_part_url(raw.strip())
        if normalized:
            part_urls.append(normalized)
    return CrawlManifest(part_urls=sorted(set(part_urls)))
