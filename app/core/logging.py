"""Logging setup.

Kept intentionally small for now; AGENT.md/CLAUDE.md call for structured JSON logs
with correlation IDs, which we layer on when the API + agent land (Phase 2/3).
"""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-8s %(name)s :: %(message)s",
        stream=sys.stdout,
        force=True,
    )
    # uvicorn access logs are noisy at INFO in dev; leave them as-is for now.
