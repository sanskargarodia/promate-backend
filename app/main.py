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

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings.log_level)
    yield


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
