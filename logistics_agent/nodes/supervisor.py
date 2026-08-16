"""판단 노드: Supervisor — LLM 대신 더미 판단 함수."""

from __future__ import annotations

from typing import cast

from logistics_agent.state import GraphState, OrderState


def supervisor(state: GraphState) -> GraphState:
    """온톨로지/규칙으로 못 정하는 예외만 처리 (현재는 더미)."""
    order = state["order"]
    item_count = len(order["item_list"])

    # 실제 LLM 호출 자리 — 지금은 고정 판단
    decision = "proceed_to_warehouse"
    notes = f"예외 없음. {item_count}개 품목 창고 처리 진행."

    print(f"[Supervisor] decision={decision}, notes={notes}")

    order = cast(OrderState, {**order, "internal_order_status": "창고처리중"})
    return {
        "supervisor_decision": decision,
        "supervisor_notes": notes,
        "order": order,
    }
