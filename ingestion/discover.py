"""Site discovery: category BFS, repair-help crawl, and offline model extraction."""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING

from ingestion.cache_store import read_cached
from ingestion.parse import discover_from_page, extract_model_urls
from ingestion.seeds import category_root_urls, merge_manifests, repair_help_root_urls
from ingestion.types import CrawlManifest

if TYPE_CHECKING:
    from ingestion.scrape import BrowserSession, ScrapeSettings

logger = logging.getLogger(__name__)


async def _bfs_fetch_pages(
    seed_urls: list[str],
    *,
    kind: str,
    max_pages: int,
    browser: BrowserSession | None,
    settings: ScrapeSettings,
    use_network: bool,
    cache_only: bool,
) -> tuple[list[str], CrawlManifest]:
    """Breadth-first crawl of listing pages; returns visited URLs and discovered manifest."""
    from ingestion.scrape import fetch_page

    visited: set[str] = set()
    queue: deque[str] = deque(seed_urls)
    discovered = CrawlManifest()

    while queue and len(visited) < max_pages:
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        html = await fetch_page(
            url,
            kind=kind,
            use_network=use_network,
            cache_only=cache_only,
            browser=browser,
            settings=settings,
        )
        if not html:
            logger.debug("Skip discovery for %s (no HTML)", url)
            continue

        page = discover_from_page(html, source_url=url)
        discovered.part_urls = sorted(
            set(discovered.part_urls) | set(page.part_urls))
        discovered.model_urls = sorted(
            set(discovered.model_urls) | set(page.model_urls))
        discovered.category_urls = sorted(
            set(discovered.category_urls) | set(page.category_urls))
        discovered.repair_help_urls = sorted(
            set(discovered.repair_help_urls) | set(page.repair_help_urls)
        )

        for next_url in page.pagination_urls + page.category_urls + page.repair_help_urls:
            if next_url not in visited and len(visited) + len(queue) < max_pages:
                queue.append(next_url)

    return sorted(visited), discovered


async def crawl_category_tree(
    *,
    max_category_pages: int = 200,
    max_repair_help_pages: int = 100,
    settings: ScrapeSettings | None = None,
    use_network: bool = True,
    cache_only: bool = False,
    browser: BrowserSession | None = None,
) -> CrawlManifest:
    """Walk category and repair-help listings to discover parts, models, and articles."""
    from ingestion.scrape import BrowserSession, ScrapeSettings

    cfg = settings or ScrapeSettings()
    category_seeds = category_root_urls()
    repair_seeds = repair_help_root_urls()

    async def run(browser_session: BrowserSession | None) -> CrawlManifest:
        cat_visited, cat_discovered = await _bfs_fetch_pages(
            category_seeds,
            kind="categories",
            max_pages=max_category_pages,
            browser=browser_session,
            settings=cfg,
            use_network=use_network,
            cache_only=cache_only,
        )
        logger.info(
            "Category crawl: visited %s pages, found %s parts, %s subcategories",
            len(cat_visited),
            len(cat_discovered.part_urls),
            len(cat_discovered.category_urls),
        )

        repair_visited, repair_discovered = await _bfs_fetch_pages(
            repair_seeds,
            kind="repair_help",
            max_pages=max_repair_help_pages,
            browser=browser_session,
            settings=cfg,
            use_network=use_network,
            cache_only=cache_only,
        )
        repair_discovered.repair_help_urls = sorted(
            set(repair_discovered.repair_help_urls) | set(repair_visited)
        )
        logger.info(
            "Repair-help crawl: visited %s pages, found %s article URLs",
            len(repair_visited),
            len(repair_discovered.repair_help_urls),
        )

        merged = merge_manifests(cat_discovered, repair_discovered)
        merged.category_urls = sorted(
            set(merged.category_urls) | set(category_seeds))
        logger.info(
            "Site crawl complete: %s parts, %s models, %s repair-help URLs",
            len(merged.part_urls),
            len(merged.model_urls),
            len(merged.repair_help_urls),
        )
        return merged

    if browser is not None:
        return await run(browser)
    if cache_only or not use_network:
        return await run(None)
    async with BrowserSession(headed=cfg.headed) as session:
        return await run(session)


def enrich_models_from_cached_parts(manifest: CrawlManifest) -> CrawlManifest:
    """Offline pass: extract compatible model URLs from cached part detail pages."""
    models = set(manifest.model_urls)
    for url in manifest.part_urls:
        html = read_cached(url, kind="parts")
        if html:
            models.update(extract_model_urls(html))
    manifest.model_urls = sorted(models)
    return manifest
