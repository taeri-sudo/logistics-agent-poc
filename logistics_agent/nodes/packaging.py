"""액션 노드: 포장agent — 봉인된 Package의 item을 일괄 포장 처리."""

from __future__ import annotations

from typing import cast

from logistics_agent.state import GraphState, Item, OrderState, PackageState


def packaging_agent(state: GraphState) -> GraphState:
    """tracking_number가 발급된(봉인된) Package 소속 item 중 피킹완료인 것을 포장완료로 전이."""
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    packages: list[PackageState] = list(state.get("packages", []))
    sealed_ids = {pkg["package_id"] for pkg in packages if pkg["tracking_number"] is not None}

    packed = 0
    for idx, item in enumerate(item_list):
        if item["package_ref"] not in sealed_ids or item["item_status"] != "피킹완료":
            continue
        print(f"  [포장] item_id={item['item_id']} package_ref={item['package_ref']} → 포장완료")
        item_list[idx] = cast(Item, {**item, "item_status": "포장완료"})
        packed += 1

    order = cast(OrderState, {**order, "item_list": item_list})
    print(f"[포장agent] 완료 - {packed}개 품목 포장완료")
    return {"order": order}
