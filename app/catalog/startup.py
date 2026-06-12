"""Catalog readiness checks before the transactional agent serves traffic."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.csv_schema import validate_parts_csv_text
from app.core.config import settings
from app.models.catalog import Part

logger = logging.getLogger(__name__)


class CatalogNotReadyError(RuntimeError):
    pass


async def validate_catalog_database(session: AsyncSession, *, min_parts: int = 100) -> int:
    count = await session.scalar(select(func.count()).select_from(Part)) or 0
    if count < min_parts:
        raise CatalogNotReadyError(
            f"Catalog database has {count} parts (need ≥{min_parts}). "
            "Run: uv run python -m ingestion import-catalog"
        )
    return count


def validate_catalog_csv_file(path: Path, *, min_rows: int = 1) -> None:
    if not path.is_file():
        raise CatalogNotReadyError(f"Catalog CSV not found: {path}")
    result = validate_parts_csv_text(path.read_text(encoding="utf-8"), min_rows=min_rows)
    if not result.ok:
        raise CatalogNotReadyError("; ".join(result.errors))


async def ensure_catalog_ready(session: AsyncSession) -> None:
    """Validate CSV file (if configured) and loaded Postgres catalog."""
    csv_path = settings.catalog_csv_path
    if csv_path:
        validate_catalog_csv_file(Path(csv_path))
    count = await validate_catalog_database(session)
    logger.info("Catalog ready: %s parts in database", count)
