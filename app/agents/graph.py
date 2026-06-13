"""Compile the Promate LangGraph agent."""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.agents import nodes, workers
from app.agents.state import AgentState
from app.agents.tool_router import plan_transactional_tools

_compiled_graph = None

SupervisorRoute = Literal[
    "refusal",
    "clarification",
    "product_search_worker",
    "compatibility_worker",
    "installation_worker",
    "troubleshooting_worker",
    "transaction_worker",
    "order_status_worker",
]


def _route_after_supervisor(state: AgentState) -> SupervisorRoute:
    if state.get("intent") == "refusal" or state.get("refused"):
        return "refusal"

    if nodes.needs_clarification(state):
        return "clarification"

    planned = plan_transactional_tools(state)
    if planned and all(call.name == "get_order_status" for call in planned):
        return "order_status_worker"

    intent = state.get("intent") or "product_search"
    by_intent: dict[str, SupervisorRoute] = {
        "product_search": "product_search_worker",
        "compatibility": "compatibility_worker",
        "installation": "installation_worker",
        "troubleshooting": "troubleshooting_worker",
        "transaction": "transaction_worker",
    }
    return by_intent.get(intent, "product_search_worker")


def build_graph(*, checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(AgentState)

    graph.add_node("refusal", nodes.refusal_node)
    graph.add_node("supervisor", nodes.supervisor_node)
    graph.add_node("clarification", nodes.clarification_node)
    graph.add_node("product_search_worker", workers.product_search_worker_node)
    graph.add_node("compatibility_worker", workers.compatibility_worker_node)
    graph.add_node("installation_worker", workers.installation_worker_node)
    graph.add_node("troubleshooting_worker",
                   workers.troubleshooting_worker_node)
    graph.add_node("transaction_worker", workers.transaction_worker_node)
    graph.add_node("order_status_worker", workers.order_status_worker_node)
    graph.add_node("composer", nodes.composer_node)
    graph.add_node("output_guardrail", nodes.output_guardrail_node)
    graph.add_node("suggest_follow_ups", nodes.suggest_follow_ups_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", _route_after_supervisor)
    graph.add_edge("refusal", "suggest_follow_ups")
    graph.add_edge("clarification", "suggest_follow_ups")
    graph.add_edge("product_search_worker", "composer")
    graph.add_edge("compatibility_worker", "composer")
    graph.add_edge("installation_worker", "composer")
    graph.add_edge("troubleshooting_worker", "composer")
    graph.add_edge("transaction_worker", "composer")
    graph.add_edge("order_status_worker", "composer")
    graph.add_edge("composer", "output_guardrail")
    graph.add_edge("output_guardrail", "suggest_follow_ups")
    graph.add_edge("suggest_follow_ups", END)

    return graph.compile(checkpointer=checkpointer)


def set_compiled_graph(graph) -> None:
    global _compiled_graph
    _compiled_graph = graph


def get_compiled_graph():
    if _compiled_graph is not None:
        return _compiled_graph
    return build_graph(checkpointer=None)
