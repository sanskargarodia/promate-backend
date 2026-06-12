"""FastAPI application entrypoint for local/dev (docker-compose, uvicorn).

The same compiled agent graph is also exposed via app/agent_core_entrypoint.py
for Bedrock AgentCore Runtime — one graph, two hosts (Phase 2).
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.checkpointer import close_checkpointer, init_checkpointer
from app.agents.graph import build_graph, set_compiled_graph
from app.api.v1.router import api_router
from app.catalog.startup import ensure_catalog_ready
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    try:
        async with SessionLocal() as db_session:
            await ensure_catalog_ready(db_session)
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning("Catalog validation skipped: %s", exc)
    try:
        checkpointer = await init_checkpointer()
        set_compiled_graph(build_graph(checkpointer=checkpointer))
    except Exception as exc:  # noqa: BLE001
        configure_logging(settings.log_level)
        import logging

        logging.getLogger(__name__).warning(
            "Postgres checkpointer unavailable (%s); multi-turn chat disabled.", exc
        )
        set_compiled_graph(build_graph(checkpointer=None))
    yield
    await close_checkpointer()


app = FastAPI(
    title="ProMate API",
    version="0.1.0",
    description="PartSelect (refrigerator + dishwasher) chat-agent backend.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def liveness() -> dict[str, str]:
    """Liveness probe (no dependencies) for container/orchestrator checks."""
    return {"status": "ok"}
