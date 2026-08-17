"""집계 노드: 패키지조립agent — item을 배송지 기준으로 묶고 조건카운트로 봉인."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import cast

from logistics_agent.nodes.tracking import derive_internal_order_status
from logistics_agent.state import GraphState, Item, OrderState, PackageState, SourceItemRef

# 창고에 집화된(=패키지에 도착한) 것으로 보는 item_status. "대기"/"피킹중"은 미도착.
ARRIVED_ITEM_STATUSES = frozenset(
    {"피킹완료", "포장완료", "출고됨", "배송중", "배송지연", "배송완료"}
)


def _new_package(address_id: str, now: str) -> PackageState:
    return {
        "package_id": f"PKG-{uuid.uuid4().hex[:8].upper()}",
        "source_items": [],
        "delivery_address_id": address_id,
        "required_item_count": 0,
        "arrived_item_count": 0,
        "current_gps": None,
        "tracking_number": None,
        "delay_categories": [],
        "policy_version_applied": None,
        "last_checked_at": now,
        "retry_count": 0,
        "escalated": False,
        "join_waiting_since": None,
        "notification_log": [],
    }


def _find_item(item_list: list[Item], order_id: str, ref: SourceItemRef) -> Item | None:
    """SourceItemRef → Item 해석."""
    # SourceItemRef가 order_id를 들고 있는 건 구조상 필드일 뿐, 여러 주문을 한 패키지로
    # 합포장하는 시나리오는 없다(Order-Package는 1:N). 조회가 항상 같은 주문 내에서만
    # 일어난다는 걸 보장하는 방어 체크 — 불일치하면 데이터 오류이므로 None 반환.
    if ref["order_id"] != order_id:
        return None
    return next((item for item in item_list if item["item_id"] == ref["item_id"]), None)


def package_assembly_agent(state: GraphState) -> GraphState:
    """미배정 item을 배송지별 Package로 묶고, required==arrived면 봉인+tracking_number 발급."""
    order = state["order"]
    order_id = order["order_id"]
    item_list: list[Item] = list(order["item_list"])
    packages: list[PackageState] = list(state.get("packages", []))
    now = datetime.now(timezone.utc).isoformat()

    # 아직 package_ref가 없는 item만 수집 (이미 배정된 건 스킵 — 재진입 멱등성)
    unassigned = [(idx, item) for idx, item in enumerate(item_list) if item["package_ref"] is None]

    print(f"[패키지조립agent] 시작 미배정={len(unassigned)}, 기존패키지={len(packages)}")

    # 배송지별 그룹핑 (dict 삽입순서 = 최초 등장 순서)
    groups: dict[str, list[int]] = {}
    for idx, item in unassigned:
        groups.setdefault(item["delivery_address_id"], []).append(idx)

    for address_id, indexes in groups.items():
        # 같은 배송지의 미봉인 패키지가 있으면 합류, 없으면 신규 생성
        pos = next(
            (
                i
                for i, pkg in enumerate(packages)
                if pkg["tracking_number"] is None and pkg["delivery_address_id"] == address_id
            ),
            None,
        )
        if pos is None:
            packages.append(_new_package(address_id, now))
            pos = len(packages) - 1
            origin = "신규"
        else:
            origin = "합류"

        package = packages[pos]
        new_refs: list[SourceItemRef] = []
        for idx in indexes:
            item = item_list[idx]
            new_refs.append({"order_id": order_id, "item_id": item["item_id"]})
            item_list[idx] = cast(Item, {**item, "package_ref": package["package_id"]})

        packages[pos] = cast(
            PackageState,
            {**package, "source_items": [*package["source_items"], *new_refs]},
        )

        print(
            f"  [그룹] address_id={address_id} items={len(indexes)} "
            f"→ {package['package_id']} ({origin})"
        )

    # 미봉인 패키지 전체 재계산 (이번에 안 건드린 것도 — 3단계 self-loop 재진입 대비)
    sealed = 0
    waiting = 0
    for pos, package in enumerate(packages):
        if package["tracking_number"] is not None:
            sealed += 1
            continue

        required = len(package["source_items"])
        arrived = sum(
            1
            for ref in package["source_items"]
            if (found := _find_item(item_list, order_id, ref)) is not None
            and found["item_status"] in ARRIVED_ITEM_STATUSES
        )
        package = cast(
            PackageState,
            {
                **package,
                "required_item_count": required,
                "arrived_item_count": arrived,
                "last_checked_at": now,
            },
        )

        if required > 0 and required == arrived:
            # 봉인: tracking_number 발급. item_status "포장완료" 전이는 포장agent 몫
            package = cast(
                PackageState,
                {
                    **package,
                    "tracking_number": f"TRK-{uuid.uuid4().hex[:12].upper()}",
                    "join_waiting_since": None,
                },
            )
            sealed += 1
            print(
                f"  [봉인] {package['package_id']} required={required} arrived={arrived} "
                f"tracking_number={package['tracking_number']}"
            )
        else:
            # 대기: 첫 대기 시각을 보존한다 (무한대기 판정은 3단계 지연체크게이트 몫)
            if package["join_waiting_since"] is None:
                package = cast(PackageState, {**package, "join_waiting_since": now})
            waiting += 1
            print(
                f"  [대기] {package['package_id']} required={required} arrived={arrived} "
                f"join_waiting_since={package['join_waiting_since']}"
            )

        packages[pos] = package

    order = cast(
        OrderState,
        {
            **order,
            "item_list": item_list,
            "internal_order_status": derive_internal_order_status(item_list, packages),
        },
    )

    print(f"[패키지조립agent] 완료 - 패키지 {len(packages)}개 (봉인 {sealed}, 대기 {waiting})")
    return {"order": order, "packages": packages}
