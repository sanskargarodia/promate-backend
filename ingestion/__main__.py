"""CLI: `uv run python -m ingestion <command>`."""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import func, select

from app.core.logging import configure_logging
from app.db.init_schema import init_schema_sync
from app.models.catalog import Part
from ingestion.load import ensure_required_parts_loaded, load_manifest
from ingestion.persist import SyncSession
from ingestion.public_catalog import load_public_catalog
from ingestion.scrape import ScrapeSettings, discover_urls, scrape_manifest
from ingestion.seeds import regression_part_ps_numbers


async def _cmd_init_db(_: argparse.Namespace) -> None:
    init_schema_sync()
    print("Database schema ready (pgvector + catalog tables).")


async def _cmd_import_catalog(args: argparse.Namespace) -> None:
    kwargs: dict[str, object] = {
        "embed_documents": not args.skip_embeddings,
        "link_models": not args.skip_model_links,
    }
    if args.csv_url:
        kwargs["csv_url"] = args.csv_url
    counts = load_public_catalog(**kwargs)  # type: ignore[arg-type]
    print(f"Imported public catalog: {counts}")


async def _cmd_scrape(args: argparse.Namespace) -> None:
    settings = ScrapeSettings(
        max_parts=args.max_parts,
        headed=args.headed,
        use_public_catalog_urls=not args.no_public_urls,
    )
    manifest = await discover_urls(
        max_parts=args.max_parts,
        settings=settings,
    )
    await scrape_manifest(
        manifest,
        use_network=not args.cache_only,
        cache_only=args.cache_only,
        settings=settings,
    )
    print(
        f"Scrape complete: {len(manifest.part_urls)} parts, "
        f"{len(manifest.model_urls)} models in manifest."
    )


async def _cmd_load(args: argparse.Namespace) -> None:
    settings = ScrapeSettings(max_parts=args.max_parts, use_public_catalog_urls=True)
    manifest = await discover_urls(
        max_parts=args.max_parts,
        settings=settings,
    )
    counts = load_manifest(manifest)
    print(f"Cache enrichment complete: {counts}")


async def _cmd_run(args: argparse.Namespace) -> None:
    """Full pipeline: public catalog → optional live scrape → cache enrichment."""
    init_schema_sync()

    import_counts = load_public_catalog(
        embed_documents=not args.skip_embeddings,
        link_models=not getattr(args, "skip_model_links", False),
    )
    print(f"Step 1/3 — public catalog: {import_counts}")

    if not args.skip_scrape:
        await _cmd_scrape(args)

    if not args.skip_cache_load:
        await _cmd_load(args)

    missing = ensure_required_parts_loaded(regression_part_ps_numbers())
    if missing:
        print(
            "WARNING: regression anchor parts missing:",
            ", ".join(missing),
            file=sys.stderr,
        )

    with SyncSession() as session:
        total = session.scalar(select(func.count()).select_from(Part))
        by_type = session.execute(
            select(Part.appliance_type, func.count())
            .group_by(Part.appliance_type)
            .order_by(Part.appliance_type)
        ).all()
    print(f"Step 3/3 — database totals: {total} parts ({dict(by_type)})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ProMate PartSelect ingestion — full refrigerator + dishwasher catalog"
    )
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create pgvector extension and tables")

    import_p = sub.add_parser(
        "import-catalog",
        help="Load ~7k fridge/dishwasher parts from public scraped CSV (primary catalog source)",
    )
    import_p.add_argument("--csv-url", default=None, help="Override public CSV URL")
    import_p.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip document embedding (faster smoke load)",
    )
    import_p.add_argument(
        "--skip-model-links",
        action="store_true",
        help="Skip part↔model compatibility links (faster; use for smoke tests only)",
    )

    scrape_p = sub.add_parser("scrape", help="Discover + cache PartSelect HTML")
    scrape_p.add_argument("--max-parts", type=int, default=10_000)
    scrape_p.add_argument("--cache-only", action="store_true")
    scrape_p.add_argument("--headed", action="store_true", help="Visible browser (bot bypass)")
    scrape_p.add_argument(
        "--no-public-urls",
        action="store_true",
        help="Do not seed manifest from public catalog export",
    )

    load_p = sub.add_parser("load", help="Enrich DB rows from cached HTML")
    load_p.add_argument("--max-parts", type=int, default=10_000)

    run_p = sub.add_parser(
        "run",
        help="import-catalog + scrape + load (recommended full pipeline)",
    )
    run_p.add_argument("--max-parts", type=int, default=10_000)
    run_p.add_argument("--cache-only", action="store_true")
    run_p.add_argument("--headed", action="store_true")
    run_p.add_argument("--skip-embeddings", action="store_true")
    run_p.add_argument(
        "--skip-model-links",
        action="store_true",
        help="Skip part↔model compatibility during catalog import",
    )
    run_p.add_argument("--skip-scrape", action="store_true", help="Skip live HTML scrape")
    run_p.add_argument("--skip-cache-load", action="store_true", help="Skip HTML enrichment")
    run_p.add_argument("--no-public-urls", action="store_true")

    args = parser.parse_args()
    configure_logging(args.log_level)

    if getattr(args, "csv_url", None) is None:
        args.csv_url = None  # type: ignore[attr-defined]

    commands = {
        "init-db": _cmd_init_db,
        "import-catalog": _cmd_import_catalog,
        "scrape": _cmd_scrape,
        "load": _cmd_load,
        "run": _cmd_run,
    }
    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
