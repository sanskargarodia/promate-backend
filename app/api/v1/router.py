"""Aggregates all /api/v1 routers. New feature routers register here."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import cart, chat, health, parts

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(parts.router)
api_router.include_router(cart.router)
