"""Grounded part-number extraction from tool payloads."""

from __future__ import annotations

import re
from typing import Any

PS_IN_TEXT = re.compile(r"\b(PS\d{5,})\b", re.I)


def ps_numbers_in_text(text: str) -> set[str]:
    return {match.upper() for match in PS_IN_TEXT.findall(text)}


def grounded_ps_numbers(
    *,
    tool_payload: dict[str, Any] | None,
    tool_results: dict[str, Any] | None,
    extra: set[str] | None = None,
) -> set[str]:
    """All PS numbers the composer may cite from the current turn's tool context."""
    allowed: set[str] = set(extra or ())

    payload = tool_payload or {}
    results = tool_results or {}

    primary = payload.get("part")
    if isinstance(primary, dict):
        ps = primary.get("part_id") or primary.get("ps_number")
        if ps:
            allowed.add(str(ps).upper())

    for key in ("matching_parts", "related_parts"):
        raw = payload.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    ps = item.get("part_id") or item.get("ps_number")
                    if ps:
                        allowed.add(str(ps).upper())

    diagnosis = payload.get("diagnosis")
    if isinstance(diagnosis, dict):
        for item in diagnosis.get("candidate_parts") or []:
            if isinstance(item, dict) and item.get("ps_number"):
                allowed.add(str(item["ps_number"]).upper())

    for item in payload.get("documents") or []:
        if not isinstance(item, dict):
            continue
        ps = item.get("part_ps_number")
        if ps:
            allowed.add(str(ps).upper())
        content = item.get("content")
        if isinstance(content, str):
            allowed.update(ps_numbers_in_text(content))

    search = results.get("search_parts")
    if isinstance(search, dict):
        for part in search.get("parts") or []:
            if isinstance(part, dict):
                ps = part.get("part_id") or part.get("ps_number")
                if ps:
                    allowed.add(str(ps).upper())

    details = results.get("get_part_details")
    if isinstance(details, dict):
        ps = details.get("part_id") or details.get("ps_number")
        if ps:
            allowed.add(str(ps).upper())

    return allowed
