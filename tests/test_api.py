"""API integration tests (require Postgres on localhost:5433 with catalog loaded)."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import ping
from app.main import app

pytestmark = pytest.mark.asyncio


def _db_available_sync() -> bool:
    async def _check() -> bool:
        try:
            return await ping()
        except Exception:
            return False

    return asyncio.run(_check())


requires_db = pytest.mark.skipif(not _db_available_sync(), reason="Postgres not available")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@requires_db
async def test_list_parts_search(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/v1/parts",
        params={"q": "ice maker", "appliance_type": "refrigerator"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "ps_number" in data[0]


@requires_db
async def test_list_featured_parts(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/parts", params={"limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()) <= 5


@requires_db
async def test_get_part(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/parts/PS11752778")
    assert resp.status_code == 200
    assert resp.json()["ps_number"] == "PS11752778"


@requires_db
async def test_part_compatibility(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/parts/PS11752778/compatibility/WDT780SAEM1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ps_number"] == "PS11752778"
    assert body["model_number"] == "WDT780SAEM1"
    assert isinstance(body["compatible"], bool)


@requires_db
async def test_chat_install_question(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/chat",
        json={"message": "How can I install part PS11752778?"},
    )
    assert resp.status_code == 200
    text = resp.text
    assert "token" in text or "done" in text



async def test_health(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
