"""LangGraph 최소 골격 — UserProfile → 주문요청 → 검증 → Supervisor → 창고처리
→ 출고전게이트 → 패키지조립 → 포장 → 조립대기게이트 → 배송중게이트 → 추적."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from logistics_agent.nodes.assembly import package_assembly_agent
from logistics_agent.nodes.delay_gates import (
    assembly_wait_gate,
    in_transit_delay_gate,
    outbound_delay_gate,
    route_after_assembly_wait_gate,
    route_after_in_transit_gate,
    route_after_outbound_gate,
)
from logistics_agent.nodes.entry import order_request_agent, user_profile_lookup
from logistics_agent.nodes.packaging import packaging_agent
from logistics_agent.nodes.supervisor import supervisor
from logistics_agent.nodes.tracking import route_after_tracking, tracking_agent
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
    graph.add_node("outbound_delay_gate", outbound_delay_gate)
    graph.add_node("package_assembly_agent", package_assembly_agent)
    graph.add_node("packaging_agent", packaging_agent)
    graph.add_node("assembly_wait_gate", assembly_wait_gate)
    graph.add_node("in_transit_delay_gate", in_transit_delay_gate)
    graph.add_node("tracking_agent", tracking_agent)

    graph.add_edge(START, "user_profile_lookup")
    graph.add_edge("user_profile_lookup", "order_request_agent")
    graph.add_edge("order_request_agent", "order_validation_agent")
    graph.add_conditional_edges(
        "order_validation_agent",
        route_after_validation,
        {"supervisor": "supervisor", "end": END},
    )
    graph.add_edge("supervisor", "warehouse_processing_agent")
    graph.add_edge("warehouse_processing_agent", "outbound_delay_gate")
    graph.add_conditional_edges(
        "outbound_delay_gate",
        route_after_outbound_gate,
        {"retry": "outbound_delay_gate", "proceed": "package_assembly_agent"},
    )
    graph.add_edge("package_assembly_agent", "packaging_agent")
    graph.add_edge("packaging_agent", "assembly_wait_gate")
    graph.add_conditional_edges(
        "assembly_wait_gate",
        route_after_assembly_wait_gate,
        {"retry": "assembly_wait_gate", "proceed": "in_transit_delay_gate"},
    )
    graph.add_conditional_edges(
        "in_transit_delay_gate",
        route_after_in_transit_gate,
        {"retry": "in_transit_delay_gate", "proceed": "tracking_agent"},
    )
    graph.add_conditional_edges(
        "tracking_agent",
        route_after_tracking,
        {"retry": "tracking_agent", "proceed": END},
    )

    return graph.compile()


app = build_graph()
