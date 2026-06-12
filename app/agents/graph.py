"""Compile the Promate LangGraph agent."""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents import nodes
from app.agents.state import AgentState

_compiled_graph = None


def _route_after_input(state: AgentState) -> Literal["refusal", "supervisor"]:
    if state.get("refused"):
        return "refusal"
    return "supervisor"


def _route_after_supervisor(state: AgentState) -> Literal["clarification", "worker"]:
    if nodes.needs_clarification(state):
        return "clarification"
    return "worker"


def build_graph(*, checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(AgentState)

    graph.add_node("input_guardrail", nodes.input_guardrail_node)
    graph.add_node("refusal", nodes.refusal_node)
    graph.add_node("supervisor", nodes.supervisor_node)
    graph.add_node("clarification", nodes.clarification_node)
    graph.add_node("worker", nodes.worker_node)
    graph.add_node("composer", nodes.composer_node)
    graph.add_node("output_guardrail", nodes.output_guardrail_node)

    graph.add_edge(START, "input_guardrail")
    graph.add_conditional_edges("input_guardrail", _route_after_input)
    graph.add_conditional_edges("supervisor", _route_after_supervisor)
    graph.add_edge("refusal", END)
    graph.add_edge("clarification", END)
    graph.add_edge("worker", "composer")
    graph.add_edge("composer", "output_guardrail")
    graph.add_edge("output_guardrail", END)

    return graph.compile(checkpointer=checkpointer)


def set_compiled_graph(graph) -> None:
    global _compiled_graph
    _compiled_graph = graph


def get_compiled_graph():
    if _compiled_graph is not None:
        return _compiled_graph
    return build_graph(checkpointer=None)
