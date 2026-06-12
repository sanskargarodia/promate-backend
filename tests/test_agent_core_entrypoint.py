"""Bedrock AgentCore entrypoint — streaming wrapper and payload helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest
from bedrock_agentcore import RequestContext
from httpx import ASGITransport, AsyncClient

from app.agent_core_entrypoint import (
    app as agentcore_app,
)
from app.agent_core_entrypoint import (
    collect_events,
    extract_message,
    invoke,
    parse_sse_events,
    resolve_thread_id,
)


def test_extract_message_prefers_message_key() -> None:
    assert extract_message({"message": "hello", "prompt": "other"}) == "hello"
    assert extract_message({"prompt": "from agentcore"}) == "from agentcore"
    assert extract_message({}) == ""


def test_resolve_thread_id() -> None:
    ctx = RequestContext(session_id="sess-abc")
    assert resolve_thread_id({"thread_id": "explicit"}, ctx) == "explicit"
    assert resolve_thread_id({}, ctx) == "sess-abc"
    assert resolve_thread_id({}, RequestContext(session_id=None)) is None


@pytest.mark.asyncio
async def test_invoke_empty_message_yields_error() -> None:
    events: list[dict[str, Any]] = []
    async for event in invoke({}, RequestContext(session_id=None)):
        events.append(event)
    assert events == [
        {"type": "error", "content": "message or prompt is required"},
        {"type": "done"},
    ]


@pytest.mark.asyncio
async def test_invoke_streams_mocked_agent_events(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_session_local():
        yield MagicMock()

    async def fake_run(**kwargs: Any):
        assert kwargs["message"] == "find ice maker"
        assert kwargs["thread_id"] == "sess-1"
        yield {"type": "session", "thread_id": "sess-1"}
        yield {"type": "token", "content": "Try PS11752778."}
        yield {"type": "done"}

    monkeypatch.setattr(
        "app.agent_core_entrypoint.SessionLocal", fake_session_local)
    monkeypatch.setattr("app.agent_core_entrypoint.run_agent_turn", fake_run)

    events: list[dict[str, Any]] = []
    async for event in invoke(
        {"prompt": "find ice maker"},
        RequestContext(session_id="sess-1"),
    ):
        events.append(event)

    assert events[0]["type"] == "session"
    assert events[1]["content"] == "Try PS11752778."
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_collect_events_aggregates_stream() -> None:
    result = await collect_events({"message": ""})
    assert result["thread_id"] is None
    assert result["events"][0]["type"] == "error"


@pytest.mark.asyncio
async def test_agentcore_ping() -> None:
    transport = ASGITransport(app=agentcore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/ping")
    assert resp.status_code == 200
    assert resp.json()["status"] in {"Healthy", "HealthyBusy"}


@pytest.mark.asyncio
async def test_agentcore_invocations_stream_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def fake_session_local():
        yield MagicMock()

    async def fake_run(**_kwargs: Any):
        yield {"type": "session", "thread_id": "t-1"}
        yield {"type": "token", "content": "hi"}
        yield {"type": "done"}

    monkeypatch.setattr(
        "app.agent_core_entrypoint.SessionLocal", fake_session_local)
    monkeypatch.setattr("app.agent_core_entrypoint.run_agent_turn", fake_run)

    transport = ASGITransport(app=agentcore_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/invocations", json={"prompt": "hello"})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    events = parse_sse_events(resp.text)
    assert events[0]["type"] == "session"
    assert events[1]["content"] == "hi"
    assert events[-1]["type"] == "done"
