"""Parts catalog CSV schema validation (JeffreyLiang321 / PartSelect export)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

REQUIRED_COLUMNS = frozenset(
    {
        "part_id",
        "part_name",
        "part_price",
        "appliance_type",
        "in_stock",
    }
)

OPTIONAL_COLUMNS = frozenset(
    {
        "mpn_id",
        "brand",
        "description",
        "symptoms",
        "compatible_models",
        "image_url",
        "install_difficulty",
        "install_time",
        "install_video_url",
        "rating",
        "review_count",
        "replace_parts",
        "product_url",
        "appliance_types",
    }
)


@dataclass(frozen=True)
class CsvValidationResult:
    ok: bool
    row_count: int
    errors: tuple[str, ...]


def validate_parts_csv_text(csv_text: str, *, min_rows: int = 1) -> CsvValidationResult:
    """Validate CSV headers and parse at least min_rows without schema errors."""
    errors: list[str] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames is None:
        return CsvValidationResult(ok=False, row_count=0, errors=("CSV has no header row.",))

    headers = {h.strip() for h in reader.fieldnames if h}
    missing = REQUIRED_COLUMNS - headers
    if missing:
        errors.append(f"Missing required columns: {', '.join(sorted(missing))}")

    row_count = 0
    for idx, row in enumerate(reader, start=2):
        row_count += 1
        part_id = (row.get("part_id") or "").strip()
        if not part_id:
            errors.append(f"Row {idx}: missing part_id")
            continue
        if not part_id.upper().startswith("PS"):
            errors.append(f"Row {idx}: invalid part_id {part_id!r}")
        appliance = (row.get("appliance_type") or row.get("appliance_types") or "").lower()
        if appliance not in {"refrigerator", "dishwasher"}:
            errors.append(f"Row {idx}: invalid appliance_type {appliance!r}")

    if row_count < min_rows:
        errors.append(f"Expected at least {min_rows} data rows, found {row_count}")

    return CsvValidationResult(ok=not errors, row_count=row_count, errors=tuple(errors))
