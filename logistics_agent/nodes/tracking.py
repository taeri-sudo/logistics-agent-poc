"""mock_carrier_signal(액션, POC 전용) + 추적agent(판단+반복) — 상태변화 신호 시뮬레이션과
Order 파생값 재계산을 분리해서 담당한다.

추적agent의 원래 설계 의도는 "상태변화 신호를 받아 파생값을 재계산하고 배송완료 도달 여부를
판단"하는 것이지, 신호 자체를 만들어내는 게 아니다. 실제 서비스라면 택배사 웹훅/Kafka 이벤트가
그 신호를 채워줄 것이므로, 그 자리를 mock_carrier_signal이라는 이름의 별도 노드로 명시적으로
분리해뒀다 — 나중에 실제 이벤트 소스로 교체할 때 tracking_agent는 건드릴 필요가 없다.
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


def mock_carrier_signal(state: GraphState) -> GraphState:
    """POC 전용 신호 발생기 — **실제 서비스에서는 이 노드 자리에 택배사 웹훅/Kafka 이벤트가
    들어온다** (확장 지점: Kafka/Confluent 등 실제 스트리밍 인프라로 교체 예정).

    지금은 그 이벤트를 흉내 내어, 봉인된 Package를 패키지 단위로 `포장완료→출고됨→배송중→배송완료`
    고정 시퀀스에서 한 틱씩 전진시키고 GPS placeholder를 채운다. 같은 패키지의 모든 item에 동일하게
    반영한다(원칙1: 캐리어 신호는 Package 사건). escalated된 패키지도 계속 전진시킨다
    (PackageState.escalated의 "비차단" 원칙).
    """
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
        for i in member_idxs:
            item_list[i] = cast(Item, {**item_list[i], "item_status": next_status})

        gps: GpsPoint | None = pkg["current_gps"]
        stage = _SHIP_SEQUENCE.index(next_status)
        if stage >= 1:
            # 데모용 GPS placeholder — 실제로는 캐리어 GPS 폴링으로 채워짐
            gps = {"lat": 37.50 + 0.01 * stage, "lng": 127.00 + 0.01 * stage, "updated_at": now}

        packages[pos] = cast(PackageState, {**pkg, "current_gps": gps, "last_checked_at": now})
        advanced += 1
        print(f"  [모의신호] {pkg['package_id']} → {next_status} (items={len(member_idxs)})")

    order = cast(OrderState, {**order, "item_list": item_list})
    print(f"[mock_carrier_signal] 완료 - {advanced}개 패키지 전진 (POC 전용 시뮬레이션, 실제 신호 아님)")
    return {"order": order, "packages": packages}


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
    """판단+반복: 현재 item_status/delay_categories를 보고 customer_facing_status/
    internal_order_status를 재계산하고, 배송완료 도달 여부만 판단한다. 신호를 직접 만들지
    않는다 — 그건 mock_carrier_signal의 몫(또는 실제 서비스에서는 외부 이벤트 소스).
    """
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    packages: list[PackageState] = list(state.get("packages", []))

    for i, item in enumerate(item_list):
        pkg = next((p for p in packages if p["package_id"] == item["package_ref"]), None)
        if pkg is None or pkg["tracking_number"] is None or item["item_status"] not in _SHIP_SEQUENCE:
            continue

        delayed = bool(pkg["delay_categories"])
        facing_status = (
            "지연" if delayed and item["item_status"] != "배송완료" else _CUSTOMER_FACING_MAP[item["item_status"]]
        )
        item_list[i] = cast(Item, {**item, "customer_facing_status": facing_status})

    order = cast(
        OrderState,
        {**order, "item_list": item_list, "internal_order_status": derive_internal_order_status(item_list, packages)},
    )

    print(f"[추적agent] 완료 - internal_order_status={order['internal_order_status']}")
    return {"order": order}


def route_after_tracking(state: GraphState) -> str:
    """조건분기: 봉인된 패키지 중 아직 배송완료에 도달하지 못한 것이 있으면 mock_carrier_signal로
    되돌아가 다음 이벤트를 기다린다."""
    packages = state.get("packages", [])
    sealed_ids = {pkg["package_id"] for pkg in packages if pkg["tracking_number"] is not None}
    item_list = state["order"]["item_list"]
    pending = any(
        item["package_ref"] in sealed_ids and item["item_status"] != "배송완료" for item in item_list
    )
    return "retry" if pending else "proceed"
