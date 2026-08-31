"""mock_carrier_signal(액션, POC 전용) + 추적agent(판단+반복) — 상태변화 신호 시뮬레이션과
Order 파생값 재계산을 분리해서 담당한다.

추적agent의 원래 설계 의도는 "상태변화 신호를 받아 파생값을 재계산하고 배송완료 도달 여부를
판단"하는 것이지, 신호 자체를 만들어내는 게 아니다. 실제 서비스라면 택배사 웹훅/Kafka 이벤트가
그 신호를 채워줄 것이므로, 그 자리를 mock_carrier_signal이라는 이름의 별도 노드로 명시적으로
분리해뒀다 — 나중에 실제 이벤트 소스로 교체할 때 tracking_agent는 건드릴 필요가 없다.
"""

from __future__ import annotations

from typing import cast

from logistics_agent.enums import InternalOrderStatus
from logistics_agent.nodes._common import _now
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


def mock_carrier_signal(state: GraphState) -> GraphState:
    """POC 전용 신호 발생기 — **실제 서비스에서는 이 노드 자리에 택배사 웹훅/Kafka 이벤트가
    들어온다** (확장 지점: Kafka/Confluent 등 실제 스트리밍 인프라로 교체 예정).

    지금은 그 이벤트를 모의 신호로 대체해, 봉인된 Package를 패키지 단위로 `포장완료→출고됨→배송중→배송완료`
    고정 시퀀스에서 한 틱씩 전진시키고 GPS placeholder를 채운다. 같은 패키지의 모든 item에 동일하게
    반영한다(원칙1: 캐리어 신호는 Package 사건). 보상조치(환불)된 패키지도 계속 전진시킨다
    ("비차단" 원칙 — 백그라운드 자동처리는 사람/판단 결과와 무관하게 계속됨). 단, 아직 보상조치로
    귀결되지 않은 미해소 지연(`delay_categories`)이 있는 패키지는 건너뛴다 — `in_transit_delay_gate`가
    매 틱 먼저 그 지연을 처리하므로, 같은 주문의 다른(무지연) 패키지가 그걸로 인해 함께 멈출 이유는
    없다(원칙6, DESIGN.md "배송중게이트 order-wide 블로킹" 참고).
    """
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    advanced = 0
    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is None:
            continue
        if pkg["delay_categories"] and pkg["compensation"] is None:
            print(f"  [대기] {pkg['package_id']} 미해소 지연으로 전진 보류")
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


_PERMANENTLY_EXCLUDED_OUTCOMES = {"회복가능_부분수령적용"}


def _permanently_excluded(item: Item, packages: list[PackageState]) -> bool:
    """이 item은 앞으로도 배송완료에 도달하지 못한다 — 취소됐거나(품목취소), 그래프
    재진입성이 없는 이 POC에서 영구 제외된(부분수령적용) 경우, 또는 소속 패키지가 끝내
    미봉인 상태로 보상조치(환불)돼 앞으로도 절대 봉인되지 않을 경우(v16 후속). assembly.py의
    `_is_assembly_eligible`과 같은 기준(순환 import를 피하려 여기서 다시 정의)."""
    if item["item_status"] == "취소됨":
        return True
    if item["decision_log"] and item["decision_log"][-1]["outcome"] in _PERMANENTLY_EXCLUDED_OUTCOMES:
        return True
    pkg = next((p for p in packages if p["package_id"] == item["package_ref"]), None)
    return pkg is not None and pkg["tracking_number"] is None and pkg["compensation"] is not None


def derive_internal_order_status(item_list: list[Item], packages: list[PackageState]) -> InternalOrderStatus:
    """Order.internal_order_status 파생 규칙. 소유자는 추적agent — 다른 노드는 이 함수를 import해 쓴다.

    v16: 품목 단위 취소, 그리고 그래프 재진입성이 없어 영구 제외되는 부분수령 item 때문에
    "일부만 배송"이 실제로 가능해졌다. 진행 중(조립중/출고준비/배송중)에는 이 사실을 별도로
    반영하지 않는다 — item.customer_facing_status가 이미 그 사실을 드러내고, 진행 단계
    자체는 원칙2(순차단계는 enum)상 이 축과 무관하기 때문이다. 영구 제외된 item이 있는 채로
    종결(잔여 item이 전부 배송완료)될 때만 "완료" 대신 "부분완료"로 구분한다.

    v16 후속: shippable item이 아예 0개인 vacuous case(전부 취소/제외/미봉인채 보상조치)는
    "부분완료"와 분리해 "전체무산"으로 반환한다 — "부분"은 대비되는 "온 것"이 있다는 전제인데
    이 케이스는 그 전제 자체가 성립하지 않는다(하나도 배송되지 않음). 코드 리뷰로 발견(main.py
    시나리오 6/10이 실제로 이 케이스를 실행하면서도 "부분완료"라 찍혀 혼동을 유발했음).
    """
    shippable = [item for item in item_list if not _permanently_excluded(item, packages)]
    excluded = len(shippable) < len(item_list)

    if not shippable:
        return "전체무산"  # 전부 취소/제외/미봉인채 보상조치 — 배송된 item이 하나도 없음 (vacuous case)

    # 미봉인+미보상조치 패키지가 남아있을 때만 "조립중" — 보상조치된 미봉인 패키지는 이미
    # shippable 필터에서 걸러졌으므로(위) 더 이상 이 판정을 막지 않는다 (v16 후속 수정).
    if not packages or any(
        pkg["tracking_number"] is None and pkg["compensation"] is None for pkg in packages
    ):
        return "조립중"

    ship_statuses = {item["item_status"] for item in shippable if item["package_ref"] is not None}
    if ship_statuses and ship_statuses <= {"배송완료"}:
        return "부분완료" if excluded else "완료"
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


def route_after_in_transit_cycle(state: GraphState) -> str:
    """조건분기: 배송중게이트→mock_carrier_signal→추적agent를 하나로 묶은 통합 루프의 종료 조건.

    두 가지를 모두 확인한다 — 봉인된 패키지 중 아직 배송완료에 도달하지 못한 item이 있는가
    (舊 route_after_tracking), 그리고 아직 보상조치로 귀결되지 않은 미해소 지연 패키지가 있는가
    (舊 route_after_in_transit_gate, delay_gates.py에서 흡수). 흡수한 이유: 두 조건 중 하나라도
    참이면 in_transit_delay_gate로 돌아가 다음 틱을 처리해야 하므로 사실상 하나의 종료 판단이다
    (DESIGN.md "배송중게이트 order-wide 블로킹" 참고).
    """
    packages = state.get("packages", [])
    sealed_ids = {pkg["package_id"] for pkg in packages if pkg["tracking_number"] is not None}
    item_list = state["order"]["item_list"]
    shipment_pending = any(
        item["package_ref"] in sealed_ids and item["item_status"] != "배송완료" for item in item_list
    )
    delay_pending = any(
        pkg["tracking_number"] is not None and pkg["delay_categories"] and pkg["compensation"] is None
        for pkg in packages
    )
    return "retry" if (shipment_pending or delay_pending) else "proceed"
