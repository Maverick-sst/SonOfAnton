"""
LangGraph State Machine — Anton Orchestrator

Flow: memory → router → (knowledge | scheduling | both) → response → END

The graph is the core orchestration layer. It coordinates — it does not
replace the Knowledge, Conversation, or Action layers.
"""

from langgraph.graph import StateGraph, END
from backend.orchestrator.state import AntonState
from backend.orchestrator.nodes import (
    router_node,
    memory_node,
    knowledge_node,
    scheduling_node,
    response_node
)


def build_graph() -> StateGraph:
    graph = StateGraph(AntonState)

    # Add nodes
    graph.add_node("memory", memory_node.run)
    graph.add_node("router", router_node.run)
    graph.add_node("knowledge", knowledge_node.run)
    graph.add_node("scheduling", scheduling_node.run)
    graph.add_node("response", response_node.run)

    # Entry point: always load memory first
    graph.set_entry_point("memory")

    # Memory → Router
    graph.add_edge("memory", "router")

    # Router dispatches based on intents
    graph.add_conditional_edges(
        "router",
        _route_based_on_intents,
        {
            "knowledge": "knowledge",
            "scheduling": "scheduling",
            "both": "knowledge",       # knowledge first, then scheduling
            "response": "response",    # chitchat → straight to response
        }
    )

    # After knowledge, check if scheduling also needed
    graph.add_conditional_edges(
        "knowledge",
        _check_scheduling_needed,
        {
            "scheduling": "scheduling",
            "response": "response"
        }
    )

    # Scheduling always leads to response
    graph.add_edge("scheduling", "response")

    # Response leads to END
    graph.add_edge("response", END)

    return graph.compile()


def _route_based_on_intents(state: AntonState) -> str:
    intents = state.get("intents", [])
    if "knowledge" in intents and "scheduling" in intents:
        return "both"
    if "knowledge" in intents:
        return "knowledge"
    if "scheduling" in intents:
        return "scheduling"
    return "response"  # chitchat / greeting


def _check_scheduling_needed(state: AntonState) -> str:
    if "scheduling" in state.get("intents", []):
        return "scheduling"
    return "response"


# Singleton compiled graph
_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph
