"""반복 노드: 창고처리agent — Sensor→Action 내장 루프 (placeholder)."""

from __future__ import annotations

from typing import cast

from logistics_agent.state import GraphState, Item, Location, OrderState


def warehouse_processing_agent(state: GraphState) -> GraphState:
    """item_list 순회, 위치 확인 후 집화 (현재는 print placeholder)."""
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    start_index = order.get("current_item_index", 0)

    print(f"[창고처리agent] 시작 index={start_index}, total={len(item_list)}")

    picked = 0
    for idx in range(start_index, len(item_list)):
        item = item_list[idx]
        location: Location = item.get("location") or {"zone": "A", "shelf": "01", "bin": "03"}

        # Item 고유 사정(재고부족/검수불량 등)이 있으면 피킹 불가 → item_status "대기" 유지
        if item.get("item_delay_reason"):
            print(f"  [Sensor] item_id={item['item_id']} {item['item_delay_reason']} → 피킹 스킵")
            continue

        # Sensor: 위치 확인
        print(f"  [Sensor] item_id={item['item_id']} location={location}")

        # Action: 집화
        print(f"  [Action] item_id={item['item_id']} 피킹 완료")
        item_list[idx] = cast(
            Item,
            {
                **item,
                "item_status": "피킹완료",
                "location": location,
                "customer_facing_status": "준비중",
            },
        )
        picked += 1

    order = cast(
        OrderState,
        {
            **order,
            "item_list": item_list,
            "current_item_index": len(item_list),
        },
    )

    print(f"[창고처리agent] 완료 - {picked}/{len(item_list)}개 품목 피킹완료")
    return {"order": order}
