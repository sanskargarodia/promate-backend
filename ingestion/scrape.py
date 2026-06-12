"""Polite PartSelect crawler (Playwright + on-disk HTML cache)."""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field

import httpx

from ingestion.cache_store import read_cached, write_cached
from ingestion.public_catalog import catalog_part_urls
from ingestion.seeds import (
    category_root_urls,
    load_catalog_seeds,
    merge_manifests,
    normalize_part_url,
)
from ingestion.types import CrawlManifest

logger = logging.getLogger(__name__)

BASE_URL = "https://www.partselect.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class ScrapeSettings:
    max_parts: int = 10_000
    delay_min: float = 1.0
    delay_max: float = 2.5
    headed: bool = False
    use_public_catalog_urls: bool = True


@dataclass
class BrowserSession:
    """Reused Playwright session — visit homepage once for cookies."""

    headed: bool = False
    _playwright: object | None = field(default=None, repr=False)
    _browser: object | None = field(default=None, repr=False)
    _context: object | None = field(default=None, repr=False)
    _warmed_up: bool = False

    async def __aenter__(self) -> BrowserSession:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, object] = {
            "headless": not self.headed,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)  # type: ignore[union-attr]
        self._context = await self._browser.new_context(  # type: ignore[union-attr]
            user_agent=USER_AGENT,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        await self._context.add_init_script(  # type: ignore[union-attr]
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await self._context.new_page()  # type: ignore[union-attr]
        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=60_000)
            self._warmed_up = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Homepage warmup failed: %s", exc)
        finally:
            await page.close()
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._context is not None:
            await self._context.close()  # type: ignore[union-attr]
        if self._browser is not None:
            await self._browser.close()  # type: ignore[union-attr]
        if self._playwright is not None:
            await self._playwright.stop()  # type: ignore[union-attr]

    async def fetch(self, url: str) -> str | None:
        if self._context is None:
            return None
        page = await self._context.new_page()  # type: ignore[union-attr]
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            if resp and resp.status >= 400:
                return None
            html = await page.content()
            if "Access Denied" in html[:800]:
                return None
            return html
        finally:
            await page.close()


async def _fetch_httpx(url: str) -> str | None:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BASE_URL + "/",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=45.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and "Access Denied" not in resp.text[:500]:
                return resp.text
    except httpx.HTTPError as exc:
        logger.debug("httpx failed for %s: %s", url, exc)
    return None


async def fetch_page(
    url: str,
    *,
    kind: str,
    use_network: bool = True,
    cache_only: bool = False,
    browser: BrowserSession | None = None,
    settings: ScrapeSettings | None = None,
) -> str | None:
    """Return HTML from cache or network (with cache write-through)."""
    cfg = settings or ScrapeSettings()
    cached = read_cached(url, kind=kind)
    if cached:
        return cached
    if cache_only or not use_network:
        logger.debug("Cache miss (no network): %s", url)
        return None

    html = await _fetch_httpx(url)
    if not html and browser is not None:
        await asyncio.sleep(random.uniform(cfg.delay_min, cfg.delay_max))
        html = await browser.fetch(url)
    elif not html:
        await asyncio.sleep(random.uniform(cfg.delay_min, cfg.delay_max))
        async with BrowserSession(headed=cfg.headed) as session:
            html = await session.fetch(url)

    if html:
        write_cached(url, html, kind=kind)
        return html

    logger.warning("Blocked or failed fetch for %s — use cache or import-catalog", url)
    return None


def _manifest_from_public_catalog(max_parts: int) -> CrawlManifest:
    logger.info("Building part manifest from public catalog export")
    urls = catalog_part_urls()[:max_parts]
    return CrawlManifest(part_urls=urls, model_urls=[], category_urls=category_root_urls())


def _manifest_from_seeds() -> CrawlManifest:
    seeds = load_catalog_seeds()
    anchors = seeds.get("regression_anchors", {})
    model_urls: list[str] = []
    part_urls: list[str] = []
    if isinstance(anchors, dict):
        for model in anchors.get("models", []):
            model_urls.append(f"{BASE_URL}/Models/{model}/")
        for ps in anchors.get("parts", []):
            normalized = normalize_part_url(str(ps))
            if normalized:
                part_urls.append(normalized)
    return CrawlManifest(
        part_urls=part_urls,
        model_urls=model_urls,
        category_urls=category_root_urls(),
    )


async def discover_urls(
    *,
    max_parts: int = 10_000,
    settings: ScrapeSettings | None = None,
) -> CrawlManifest:
    """Part URLs from public CSV export + regression anchors (no listing crawl)."""
    cfg = settings or ScrapeSettings(max_parts=max_parts)
    cfg.max_parts = max_parts

    manifests: list[CrawlManifest] = [_manifest_from_seeds()]

    if cfg.use_public_catalog_urls:
        try:
            manifests.append(_manifest_from_public_catalog(max_parts))
        except Exception as exc:  # noqa: BLE001
            logger.error("Public catalog URL export failed: %s", exc)

    merged = merge_manifests(*manifests)
    merged.part_urls = sorted(set(merged.part_urls))[:max_parts]
    logger.info(
        "Discovery complete: %s part URLs, %s model URLs",
        len(merged.part_urls),
        len(merged.model_urls),
    )
    return merged


async def scrape_manifest(
    manifest: CrawlManifest,
    *,
    use_network: bool = True,
    cache_only: bool = False,
    settings: ScrapeSettings | None = None,
    concurrency: int = 2,
) -> CrawlManifest:
    """Ensure HTML cache exists for every URL in the manifest."""
    cfg = settings or ScrapeSettings()
    sem = asyncio.Semaphore(max(1, min(concurrency, 2)))

    if cache_only or not use_network:
        for url in manifest.part_urls:
            await fetch_page(url, kind="parts", cache_only=True)
        for url in manifest.model_urls:
            await fetch_page(url, kind="models", cache_only=True)
        return manifest

    async with BrowserSession(headed=cfg.headed) as browser:

        async def scrape_one(url: str, kind: str) -> None:
            async with sem:
                await fetch_page(
                    url,
                    kind=kind,
                    browser=browser,
                    settings=cfg,
                )
                await asyncio.sleep(random.uniform(cfg.delay_min, cfg.delay_max))

        for url in manifest.part_urls:
            await scrape_one(url, "parts")
        for url in manifest.model_urls:
            await scrape_one(url, "models")

    return manifest
