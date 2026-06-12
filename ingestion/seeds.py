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


def normalize_part_url(url: str) -> str | None:
    match = re.search(r"PS(\d+)", url, re.I)
    if not match:
        return None
    return f"{BASE_URL}/PS{match.group(1)}.htm"


def merge_manifests(*manifests: CrawlManifest) -> CrawlManifest:
    parts: set[str] = set()
    models: set[str] = set()
    categories: set[str] = set()
    for manifest in manifests:
        parts.update(manifest.part_urls)
        models.update(manifest.model_urls)
        categories.update(manifest.category_urls)
    return CrawlManifest(
        part_urls=sorted(parts),
        model_urls=sorted(models),
        category_urls=sorted(categories),
    )
