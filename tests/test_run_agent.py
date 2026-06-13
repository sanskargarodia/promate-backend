"""Tests for agent turn streaming and status events."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.run import run_agent_turn


@pytest.mark.asyncio
async def test_run_agent_turn_streams_status_events(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_astream(_input: dict[str, Any], *, config: dict[str, Any], stream_mode: list[str]):
        assert stream_mode == ["custom", "values"]
        yield "custom", {"message": "Searching the parts catalog…"}
        yield "values", {
            "final_response": "Found PS11752778.",
            "purchase_handoffs": [],
            "tool_payload": {},
        }

    graph = MagicMock()
    graph.astream = fake_astream
    monkeypatch.setattr("app.agents.run.get_compiled_graph", lambda: graph)

    events: list[dict[str, Any]] = []
    async for event in run_agent_turn(message="ice maker", session=MagicMock(), thread_id="t-1"):
        events.append(event)

    assert events[0] == {"type": "session", "thread_id": "t-1"}
    assert events[1] == {"type": "status", "message": "Starting…"}
    assert {"type": "status", "message": "Searching the parts catalog…"} in events
    assert events[-2] == {"type": "token", "content": "Found PS11752778."}
    assert events[-1] == {"type": "done"}
