"""CLI: `uv run python -m ingestion <command>`."""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.logging import configure_logging
from app.db.init_schema import init_schema
from ingestion.load import ensure_required_parts_loaded, load_manifest
from ingestion.scrape import discover_urls, load_seed_manifest, scrape_manifest


async def _cmd_init_db(_: argparse.Namespace) -> None:
    await init_schema()
    print("Database schema ready (pgvector + catalog tables).")


async def _cmd_scrape(args: argparse.Namespace) -> None:
    manifest = await discover_urls(
        max_parts=args.max_parts,
        use_network=not args.cache_only,
        cache_only=args.cache_only,
    )
    await scrape_manifest(
        manifest,
        use_network=not args.cache_only,
        cache_only=args.cache_only,
    )
    print(
        f"Scrape complete: {len(manifest.part_urls)} parts, "
        f"{len(manifest.model_urls)} models queued in cache."
    )


async def _cmd_load(_: argparse.Namespace) -> None:
    manifest = load_seed_manifest()
    discovered = await discover_urls(max_parts=500, use_network=False, cache_only=True)
    manifest.part_urls = sorted(set(manifest.part_urls) | set(discovered.part_urls))
    manifest.model_urls = sorted(set(manifest.model_urls) | set(discovered.model_urls))
    counts = await load_manifest(manifest)
    missing = ensure_required_parts_loaded(["PS11752778"])
    if missing:
        print(
            "WARNING: required parts missing from DB (cache/network):",
            ", ".join(missing),
            file=sys.stderr,
        )
    print(f"Load complete: {counts}")


async def _cmd_run(args: argparse.Namespace) -> None:
    await _cmd_scrape(args)
    await _cmd_load(args)


def main() -> None:
    parser = argparse.ArgumentParser(description="ProMate PartSelect ingestion")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create pgvector extension and tables")

    scrape_p = sub.add_parser("scrape", help="Crawl PartSelect and cache HTML")
    scrape_p.add_argument("--max-parts", type=int, default=500)
    scrape_p.add_argument(
        "--cache-only",
        action="store_true",
        help="Only read/write ingestion/cache (no network)",
    )

    sub.add_parser("load", help="Parse cached HTML and upsert into Postgres")

    run_p = sub.add_parser("run", help="scrape then load")
    run_p.add_argument("--max-parts", type=int, default=500)
    run_p.add_argument("--cache-only", action="store_true")

    args = parser.parse_args()
    configure_logging(args.log_level)

    commands = {
        "init-db": _cmd_init_db,
        "scrape": _cmd_scrape,
        "load": _cmd_load,
        "run": _cmd_run,
    }
    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
