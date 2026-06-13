"""Integration tests for LangGraph Postgres checkpoint memory."""

from __future__ import annotations

import sys
from uuid import uuid4

import pytest
from langchain_core.messages import HumanMessage

from app.agents.checkpointer import close_checkpointer, init_checkpointer
from app.agents.conversation import format_recent_transcript, reset_turn_ephemeral_state
from app.agents.graph import build_graph
from app.core.db import SessionLocal, ping


@pytest.fixture
async def memory_graph():
    if sys.platform == "win32":
        import asyncio

        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        if not await ping():
            pytest.skip("Postgres unavailable")
        checkpointer = await init_checkpointer()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Checkpointer unavailable: {exc}")

    graph = build_graph(checkpointer=checkpointer)
    yield graph
    await close_checkpointer()


@pytest.mark.asyncio
async def test_checkpoint_restores_prior_turns(memory_graph) -> None:
    thread_id = f"test-{uuid4()}"
    config: dict = {"configurable": {"thread_id": thread_id}}

    async with SessionLocal() as session:
        config["configurable"]["session"] = session

        turn1 = await memory_graph.ainvoke(
            {"messages": [HumanMessage(content="help me diagnose")]},
            config=config,
        )
        assert turn1.get("session_context", {}).get(
            "active_intent") == "troubleshooting"

        turn2 = await memory_graph.ainvoke(
            {"messages": [HumanMessage(
                content="My refrigerator is making weird noise")]},
            config=config,
        )

    transcript = format_recent_transcript(turn2)
    assert "help me diagnose" in transcript
    assert "weird noise" in transcript
    assert len(turn2.get("messages") or []) >= 4
    assert turn2.get("session_context", {}).get(
        "appliance_type") == "refrigerator"


@pytest.mark.asyncio
async def test_without_checkpoint_drops_prior_turns() -> None:
    graph = build_graph(checkpointer=None)
    thread_id = f"test-{uuid4()}"
    config: dict = {"configurable": {"thread_id": thread_id}}

    async with SessionLocal() as session:
        config["configurable"]["session"] = session
        await graph.ainvoke(
            {"messages": [HumanMessage(content="help me diagnose")]},
            config=config,
        )
        turn2 = await graph.ainvoke(
            {"messages": [HumanMessage(
                content="My refrigerator is making weird noise")]},
            config=config,
        )

    transcript = format_recent_transcript(turn2)
    assert "help me diagnose" not in transcript
    assert len(turn2.get("messages") or []) == 2


@pytest.mark.asyncio
async def test_part_lookup_then_pronoun_installation(memory_graph) -> None:
    """Regression: 'its installation' must not be refused after a PS lookup turn."""
    thread_id = f"test-{uuid4()}"
    config: dict = {"configurable": {"thread_id": thread_id}}

    async with SessionLocal() as session:
        config["configurable"]["session"] = session

        await memory_graph.ainvoke(
            {"messages": [HumanMessage(
                content="Tell me about part PS11752778")]},
            config=config,
        )
        turn2 = await memory_graph.ainvoke(
            {"messages": [HumanMessage(
                content="can you tell about its installation")]},
            config=config,
        )

    assert turn2.get("refused") is not True
    assert turn2.get("intent") == "installation"
    assert turn2.get("ps_number") == "PS11752778"
    assert turn2.get("final_response")


def test_reset_turn_ephemeral_state_clears_tool_payload() -> None:
    reset = reset_turn_ephemeral_state()
    assert reset["tool_results"] == {}
    assert reset["tool_payload"] == {}
    assert reset["purchase_handoffs"] == []
