"""Filesystem cache for raw HTML (idempotent re-runs)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_CACHE_ROOT = Path(__file__).resolve().parent / "cache"


def cache_root() -> Path:
    return _CACHE_ROOT


def _slug_from_url(url: str) -> str:
    ps = re.search(r"(PS\d+)", url, re.I)
    if ps:
        return ps.group(1).upper()
    model = re.search(r"/Models/([^/]+)/?", url, re.I)
    if model:
        return model.group(1).upper()
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    return f"page_{digest}"


def cache_path(url: str, *, kind: str) -> Path:
    """Return the on-disk path for a cached page (`parts`, `models`, `categories`)."""
    return cache_root() / kind / f"{_slug_from_url(url)}.html"


def read_cached(url: str, *, kind: str) -> str | None:
    path = cache_path(url, kind=kind)
    if path.is_file():
        return path.read_text(encoding="utf-8", errors="replace")
    return None


def write_cached(url: str, html: str, *, kind: str) -> Path:
    path = cache_path(url, kind=kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path
