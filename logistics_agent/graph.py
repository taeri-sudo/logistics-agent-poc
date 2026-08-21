"""LangGraph 최소 골격 — UserProfile → 주문요청 → 검증 → decide_warehouse_entry → 창고처리
→ 피킹지연게이트 → 패키지조립 → 포장 → 포장대기게이트 → 배송중게이트 → mock_carrier_signal → 추적."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from logistics_agent.nodes.assembly import package_assembly_agent
from logistics_agent.nodes.delay_gates import (
    in_transit_delay_gate,
    packaging_wait_gate,
    picking_delay_gate,
    route_after_in_transit_gate,
    route_after_packaging_wait_gate,
    route_after_picking_gate,
)
from logistics_agent.nodes.entry import order_request_agent, user_profile_lookup
from logistics_agent.nodes.packaging import packaging_agent
from logistics_agent.nodes.supervisor import decide_warehouse_entry
from logistics_agent.nodes.tracking import mock_carrier_signal, route_after_tracking, tracking_agent
from logistics_agent.nodes.validation import order_validation_agent, route_after_validation
from logistics_agent.nodes.warehouse import warehouse_processing_agent
from logistics_agent.state import GraphState


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("user_profile_lookup", user_profile_lookup)
    graph.add_node("order_request_agent", order_request_agent)
    graph.add_node("order_validation_agent", order_validation_agent)
    graph.add_node("decide_warehouse_entry", decide_warehouse_entry)
    graph.add_node("warehouse_processing_agent", warehouse_processing_agent)
    graph.add_node("picking_delay_gate", picking_delay_gate)
    graph.add_node("package_assembly_agent", package_assembly_agent)
    graph.add_node("packaging_agent", packaging_agent)
    graph.add_node("packaging_wait_gate", packaging_wait_gate)
    graph.add_node("in_transit_delay_gate", in_transit_delay_gate)
    graph.add_node("mock_carrier_signal", mock_carrier_signal)
    graph.add_node("tracking_agent", tracking_agent)

    graph.add_edge(START, "user_profile_lookup")
    graph.add_edge("user_profile_lookup", "order_request_agent")
    graph.add_edge("order_request_agent", "order_validation_agent")
    graph.add_conditional_edges(
        "order_validation_agent",
        route_after_validation,
        {"supervisor": "decide_warehouse_entry", "end": END},
    )
    graph.add_edge("decide_warehouse_entry", "warehouse_processing_agent")
    graph.add_edge("warehouse_processing_agent", "picking_delay_gate")
    graph.add_conditional_edges(
        "picking_delay_gate",
        route_after_picking_gate,
        {"retry": "picking_delay_gate", "proceed": "package_assembly_agent"},
    )
    graph.add_edge("package_assembly_agent", "packaging_agent")
    graph.add_edge("packaging_agent", "packaging_wait_gate")
    graph.add_conditional_edges(
        "packaging_wait_gate",
        route_after_packaging_wait_gate,
        {"retry": "packaging_wait_gate", "proceed": "in_transit_delay_gate"},
    )
    graph.add_conditional_edges(
        "in_transit_delay_gate",
        route_after_in_transit_gate,
        {"retry": "in_transit_delay_gate", "proceed": "mock_carrier_signal"},
    )
    graph.add_edge("mock_carrier_signal", "tracking_agent")
    graph.add_conditional_edges(
        "tracking_agent",
        route_after_tracking,
        {"retry": "mock_carrier_signal", "proceed": END},
    )

    return graph.compile()


app = build_graph()
