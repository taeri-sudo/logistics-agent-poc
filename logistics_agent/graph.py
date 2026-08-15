"""LangGraph 최소 골격 — UserProfile → 주문요청 → 검증 → Supervisor → 창고처리."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from logistics_agent.nodes.entry import order_request_agent, user_profile_lookup
from logistics_agent.nodes.supervisor import supervisor
from logistics_agent.nodes.validation import order_validation_agent, route_after_validation
from logistics_agent.nodes.warehouse import warehouse_processing_agent
from logistics_agent.state import GraphState


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("user_profile_lookup", user_profile_lookup)
    graph.add_node("order_request_agent", order_request_agent)
    graph.add_node("order_validation_agent", order_validation_agent)
    graph.add_node("supervisor", supervisor)
    graph.add_node("warehouse_processing_agent", warehouse_processing_agent)

    graph.add_edge(START, "user_profile_lookup")
    graph.add_edge("user_profile_lookup", "order_request_agent")
    graph.add_edge("order_request_agent", "order_validation_agent")
    graph.add_conditional_edges(
        "order_validation_agent",
        route_after_validation,
        {"supervisor": "supervisor", "end": END},
    )
    graph.add_edge("supervisor", "warehouse_processing_agent")
    graph.add_edge("warehouse_processing_agent", END)

    return graph.compile()


app = build_graph()
