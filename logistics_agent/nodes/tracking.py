"""통합 노드: 추적agent — 외부 상태변화 신호(캐리어 이벤트) 수신 + Order 파생값 재계산.

게이트들(delay_gates.py)과 같은 self-loop 뼈대를 재사용하지만, 이 노드는 "해소를 기다리는" 게
아니라 "정해진 이벤트 시퀀스를 진행시키는" 것이라 retry_count/escalated/MAX_GATE_RETRIES를 쓰지
않는다 — item_status 자체가 진행 카운터 역할을 한다. 이벤트는 패키지 단위로 발생(원칙1: 캐리어
신호는 Package 사건)하고, 같은 패키지의 모든 item에 동일하게 반영한다. escalated된 패키지도
계속 전진시킨다 (PackageState.escalated의 "비차단" 원칙).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from logistics_agent.enums import InternalOrderStatus
from logistics_agent.state import GraphState, GpsPoint, Item, OrderState, PackageState

# 포장완료 이후 캐리어 이벤트 고정 시퀀스. item_status 값 자체가 "지금 몇 번째 이벤트까지
# 반영됐는지"를 나타내는 진행 카운터라 별도 tick 필드가 필요 없다.
_SHIP_SEQUENCE = ["포장완료", "출고됨", "배송중", "배송완료"]

_CUSTOMER_FACING_MAP = {
    "포장완료": "준비중",
    "출고됨": "배송중",
    "배송중": "배송중",
    "배송완료": "배송완료",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_internal_order_status(item_list: list[Item], packages: list[PackageState]) -> InternalOrderStatus:
    """Order.internal_order_status 파생 규칙. 소유자는 추적agent — 다른 노드는 이 함수를 import해 쓴다."""
    if not packages or any(pkg["tracking_number"] is None for pkg in packages):
        return "조립중"

    ship_statuses = {item["item_status"] for item in item_list if item["package_ref"] is not None}
    if ship_statuses and ship_statuses <= {"배송완료"}:
        return "완료"
    if ship_statuses & {"출고됨", "배송중", "배송완료"}:
        return "배송중"
    return "출고준비"


def tracking_agent(state: GraphState) -> GraphState:
    """봉인된 Package를 패키지 단위로 한 단계씩 전진시키고, 그 자리에서 Order 파생값을 재계산."""
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    advanced = 0
    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is None:
            continue

        member_idxs = [i for i, it in enumerate(item_list) if it["package_ref"] == pkg["package_id"]]
        if not member_idxs:
            continue

        current = item_list[member_idxs[0]]["item_status"]
        if current not in _SHIP_SEQUENCE or current == _SHIP_SEQUENCE[-1]:
            continue

        next_status = _SHIP_SEQUENCE[_SHIP_SEQUENCE.index(current) + 1]
        delayed = bool(pkg["delay_categories"])
        facing_status = "지연" if delayed and next_status != "배송완료" else _CUSTOMER_FACING_MAP[next_status]

        for i in member_idxs:
            item_list[i] = cast(
                Item, {**item_list[i], "item_status": next_status, "customer_facing_status": facing_status}
            )

        gps: GpsPoint | None = pkg["current_gps"]
        if _SHIP_SEQUENCE.index(next_status) >= 1:
            # 데모용 GPS placeholder — 실제로는 캐리어 GPS 폴링으로 채워짐
            stage = _SHIP_SEQUENCE.index(next_status)
            gps = {"lat": 37.50 + 0.01 * stage, "lng": 127.00 + 0.01 * stage, "updated_at": now}

        packages[pos] = cast(PackageState, {**pkg, "current_gps": gps, "last_checked_at": now})
        advanced += 1
        print(
            f"  [이벤트] {pkg['package_id']} → {next_status} (items={len(member_idxs)}, "
            f"delay_categories={pkg['delay_categories']})"
        )

    order = cast(
        OrderState,
        {**order, "item_list": item_list, "internal_order_status": derive_internal_order_status(item_list, packages)},
    )

    print(f"[추적agent] 완료 - {advanced}개 패키지 전진, internal_order_status={order['internal_order_status']}")
    return {"order": order, "packages": packages}


def route_after_tracking(state: GraphState) -> str:
    """조건분기: 봉인된 패키지 중 아직 배송완료에 도달하지 못한 것이 있으면 재시도."""
    packages = state.get("packages", [])
    sealed_ids = {pkg["package_id"] for pkg in packages if pkg["tracking_number"] is not None}
    item_list = state["order"]["item_list"]
    pending = any(
        item["package_ref"] in sealed_ids and item["item_status"] != "배송완료" for item in item_list
    )
    return "retry" if pending else "proceed"
