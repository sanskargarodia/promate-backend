"""Select which catalog parts become UI product cards — intentional, not tool dumps."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.schemas.catalog import PartResult

PS_IN_TEXT = re.compile(r"\b(PS\d{5,})\b", re.I)

MAX_TROUBLESHOOTING_CARDS = 3
CardRole = Literal["primary", "recommended"]


def part_dict_to_card(item: dict[str, object]) -> dict[str, object]:
    return PartResult.model_validate(
        {
            "ps_number": item.get("part_id") or item.get("ps_number"),
            "name": item.get("name", ""),
            "brand": item.get("brand"),
            "appliance_type": item.get("appliance_type", "refrigerator"),
            "price_cents": item.get("price_cents"),
            "in_stock": item.get("in_stock", False),
            "image_urls": item.get("image_urls") or [],
            "source_url": item.get("source_url"),
            "recommendation_reason": item.get("recommendation_reason"),
        }
    ).model_dump()


def _ps_in_text(text: str) -> set[str]:
    return {match.upper() for match in PS_IN_TEXT.findall(text)}


def _add_card(
    cards: list[dict[str, object]],
    emitted: set[str],
    item: dict[str, object],
    *,
    role: CardRole,
) -> None:
    if not item:
        return
    card = part_dict_to_card(item)
    ps = str(card["ps_number"])
    if ps in emitted:
        return
    emitted.add(ps)
    cards.append({"part": card, "card_role": role})


def _lookup_part(
    ps_number: str,
    tool_payload: dict[str, object],
) -> dict[str, object] | None:
    """Resolve a mentioned PS number from tool payload for card rendering."""
    primary = tool_payload.get("part")
    if isinstance(primary, dict):
        primary_ps = str(primary.get("part_id")
                         or primary.get("ps_number") or "").upper()
        if primary_ps == ps_number:
            return primary

    for key in ("related_parts", "matching_parts"):
        raw = tool_payload.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            ps = str(item.get("part_id") or item.get(
                "ps_number") or "").upper()
            if ps == ps_number:
                return item

    diagnosis = tool_payload.get("diagnosis")
    if isinstance(diagnosis, dict):
        for item in diagnosis.get("candidate_parts") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("ps_number", "")).upper() == ps_number:
                return item

    return None


def select_product_cards(result: dict[str, Any]) -> list[dict[str, object]]:
    """Return product cards that match user intent — never every search hit."""
    if result.get("refused") or result.get("intent") in {"refusal", "clarification"}:
        return []

    intent = result.get("intent")
    tool_payload = result.get("tool_payload") or {}
    final_response = str(result.get("final_response") or "")
    mentioned_ps = _ps_in_text(final_response)

    cards: list[dict[str, object]] = []
    emitted: set[str] = set()

    primary = tool_payload.get("part")
    primary_ps: str | None = None
    if isinstance(primary, dict) and primary.get("found", True):
        primary_ps = str(primary.get("part_id")
                         or primary.get("ps_number") or "")
        if primary_ps:
            _add_card(cards, emitted, primary, role="primary")

    if primary_ps:
        for ps in sorted(mentioned_ps):
            if ps == primary_ps.upper():
                continue
            item = _lookup_part(ps, tool_payload)
            if item:
                _add_card(cards, emitted, item, role="recommended")

    if intent == "troubleshooting" and not primary_ps:
        diagnosis = tool_payload.get("diagnosis")
        if isinstance(diagnosis, dict):
            candidates = diagnosis.get("candidate_parts") or []
            if mentioned_ps:
                candidates = [
                    c
                    for c in candidates
                    if isinstance(c, dict) and str(c.get("ps_number", "")).upper() in mentioned_ps
                ]
            for item in candidates[:MAX_TROUBLESHOOTING_CARDS]:
                if isinstance(item, dict):
                    _add_card(cards, emitted, item, role="recommended")
        elif mentioned_ps:
            matching = tool_payload.get("matching_parts") or []
            if isinstance(matching, list):
                for ps in sorted(mentioned_ps):
                    item = _lookup_part(ps, tool_payload)
                    if item:
                        _add_card(cards, emitted, item, role="recommended")

    if intent == "product_search" and not primary_ps and not cards:
        matching = tool_payload.get("matching_parts") or []
        if isinstance(matching, list) and len(matching) == 1 and isinstance(matching[0], dict):
            _add_card(cards, emitted, matching[0], role="primary")
        elif mentioned_ps:
            for ps in sorted(mentioned_ps):
                item = _lookup_part(ps, tool_payload)
                if item:
                    role: CardRole = "primary" if not cards else "recommended"
                    _add_card(cards, emitted, item, role=role)

    return cards
