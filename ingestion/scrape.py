"""Polite PartSelect crawler (Playwright + on-disk HTML cache)."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from pathlib import Path

import httpx

from ingestion.cache_store import read_cached, write_cached
from ingestion.parse import extract_model_urls, extract_part_urls
from ingestion.types import CrawlManifest

logger = logging.getLogger(__name__)

BASE_URL = "https://www.partselect.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

SEEDS_PATH = Path(__file__).resolve().parent / "seeds" / "required.json"


def load_seed_manifest() -> CrawlManifest:
    import json

    if not SEEDS_PATH.is_file():
        return CrawlManifest()
    data = json.loads(SEEDS_PATH.read_text(encoding="utf-8"))
    part_urls = [
        u if u.startswith("http") else f"{BASE_URL}/PS{u.lstrip('PS')}.htm"
        for u in data.get("parts", [])
    ]
    model_urls = [
        u if u.startswith("http") else f"{BASE_URL}/Models/{u}/"
        for u in data.get("models", [])
    ]
    category_urls = data.get("category_urls", [])
    return CrawlManifest(
        part_urls=part_urls,
        model_urls=model_urls,
        category_urls=category_urls,
    )


async def _fetch_httpx(url: str) -> str | None:
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=45.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and "Access Denied" not in resp.text[:500]:
                return resp.text
    except httpx.HTTPError as exc:
        logger.debug("httpx failed for %s: %s", url, exc)
    return None


async def _fetch_playwright(url: str) -> str | None:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=USER_AGENT, locale="en-US")
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            if resp and resp.status >= 400:
                return None
            html = await page.content()
            if "Access Denied" in html[:800]:
                return None
            return html
        finally:
            await browser.close()


async def fetch_page(
    url: str,
    *,
    kind: str,
    use_network: bool = True,
    cache_only: bool = False,
) -> str | None:
    """Return HTML from cache or network (with cache write-through)."""
    cached = read_cached(url, kind=kind)
    if cached:
        return cached
    if cache_only or not use_network:
        logger.warning("Cache miss (no network): %s", url)
        return None

    html = await _fetch_httpx(url)
    if not html:
        await asyncio.sleep(random.uniform(1.0, 2.5))
        html = await _fetch_playwright(url)

    if html:
        write_cached(url, html, kind=kind)
        return html

    logger.error("Failed to fetch %s (403/blocked?). Save HTML to %s", url, kind)
    return None


async def discover_urls(
    *,
    max_parts: int = 500,
    use_network: bool = True,
    cache_only: bool = False,
) -> CrawlManifest:
    """Crawl category pages and merge with required seeds."""
    seeds = load_seed_manifest()
    part_urls: set[str] = set(seeds.part_urls)
    model_urls: set[str] = set(seeds.model_urls)

    for category_url in seeds.category_urls:
        html = await fetch_page(
            category_url,
            kind="categories",
            use_network=use_network,
            cache_only=cache_only,
        )
        if not html:
            continue
        for link in extract_part_urls(html):
            part_urls.add(link)
            if len(part_urls) >= max_parts:
                break
        await asyncio.sleep(random.uniform(1.0, 2.0))
        if len(part_urls) >= max_parts:
            break

    # Discover parts listed on required model pages.
    for model_url in list(model_urls):
        html = await fetch_page(
            model_url,
            kind="models",
            use_network=use_network,
            cache_only=cache_only,
        )
        if not html:
            continue
        for link in extract_part_urls(html):
            part_urls.add(link)
        for link in extract_model_urls(html):
            model_urls.add(link)
        await asyncio.sleep(random.uniform(1.0, 2.0))

    # Canonical part URLs (PartSelect redirects slug paths).
    normalized_parts: list[str] = []
    for url in sorted(part_urls)[:max_parts]:
        ps = re.search(r"PS(\d+)", url, re.I)
        if ps:
            normalized_parts.append(f"{BASE_URL}/PS{ps.group(1)}.htm")

    return CrawlManifest(
        part_urls=normalized_parts,
        model_urls=sorted(model_urls),
        category_urls=seeds.category_urls,
    )


async def scrape_manifest(
    manifest: CrawlManifest,
    *,
    use_network: bool = True,
    cache_only: bool = False,
) -> CrawlManifest:
    """Ensure HTML cache exists for every URL in the manifest."""
    for url in manifest.part_urls:
        await fetch_page(url, kind="parts", use_network=use_network, cache_only=cache_only)
        await asyncio.sleep(random.uniform(1.0, 2.0))
    for url in manifest.model_urls:
        await fetch_page(url, kind="models", use_network=use_network, cache_only=cache_only)
        await asyncio.sleep(random.uniform(1.0, 2.0))
    return manifest
