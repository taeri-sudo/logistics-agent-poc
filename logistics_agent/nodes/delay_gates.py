"""판단+반복 노드: 지연체크게이트 3종 — 출고전(Item)/조립대기(미봉인 Package)/배송중(봉인 Package).

셋 다 같은 뼈대: 조건 미해소면 자기 자신으로 self-loop, retry_count가 최대 반복 횟수를
넘으면 escalated=true로 표시하고 (비차단으로) 다음 단계로 진행한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from logistics_agent.nodes._common import _now
from logistics_agent.nodes.supervisor import DelayRiskSignals, predict_delay_escalation
from logistics_agent.state import GraphState, Item, OrderState, PackageState

MAX_GATE_RETRIES = 3
POLICY_VERSION = "DELAY-POLICY-v1"

# 데모용 고정 해소 시점 (실제로는 재고센서/외부 API 폴링 결과). retry_count가 이 값 이상이면 해소.
# None이면 재시도로는 해소되지 않음 — 반드시 escalated=true로 귀결된다.
_ITEM_RESOLVE_AT_RETRY: dict[str, int | None] = {
    "재고부족": 2,
    "검수불량": 1,
    "파손": None,
}

# 데모용 고정 지연 신호 (실제로는 물류사 API/GPS 폴링). package_id는 uuid라 사전에 못 박을 수 없어
# delivery_address_id를 키로 대신 쓴다. (categories, 해소에 필요한 retry_count / None=영구미해소)
_PACKAGE_DELAY_SIGNAL: dict[str, tuple[list[str], int | None]] = {
    "ADDR-OFFICE": (["교통지연"], 1),
    "ADDR-STORM": (["자연재해"], None),
}


def outbound_delay_gate(state: GraphState) -> GraphState:
    """출고전게이트: item_delay_reason이 있는 item만 대상으로 해소 여부 재확인."""
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    now = _now()

    for idx, item in enumerate(item_list):
        reason = item["item_delay_reason"]
        if not reason or item["escalated"]:
            continue

        resolve_at = _ITEM_RESOLVE_AT_RETRY.get(reason)
        if resolve_at is not None and item["retry_count"] >= resolve_at:
            item_list[idx] = cast(
                Item,
                {
                    **item,
                    "item_delay_reason": None,
                    "item_status": "피킹완료",
                    "customer_facing_status": "준비중",
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                },
            )
            print(f"  [해소] item_id={item['item_id']} {reason} → 피킹완료")
            continue

        new_retry = item["retry_count"] + 1
        escalated = new_retry > MAX_GATE_RETRIES
        item_list[idx] = cast(
            Item,
            {
                **item,
                "retry_count": new_retry,
                "escalated": escalated,
                "customer_facing_status": "지연",
                "last_checked_at": now,
                "policy_version_applied": POLICY_VERSION,
            },
        )
        if escalated:
            print(f"  [에스컬레이션] item_id={item['item_id']} {reason} retry_count={new_retry}")
        else:
            print(f"  [재시도] item_id={item['item_id']} {reason} retry_count={new_retry}")

    order = cast(OrderState, {**order, "item_list": item_list})
    print(f"[출고전게이트] 완료 - 미해소 지연 item {sum(1 for i in item_list if i['item_delay_reason'])}개")
    return {"order": order}


def route_after_outbound_gate(state: GraphState) -> str:
    """조건분기: 해소 대기 중인(escalated 아닌) 지연 item이 남아있으면 재시도."""
    pending = any(
        item["item_delay_reason"] and not item["escalated"] for item in state["order"]["item_list"]
    )
    return "retry" if pending else "proceed"


def assembly_wait_gate(state: GraphState) -> GraphState:
    """조립대기게이트: 미봉인 Package를 감시만 한다 (순수 워처, 스스로 해소하지 않음).

    실제 해소는 출고전게이트가 item_delay_reason을 풀고 패키지조립agent가 재봉인하는
    경로로만 일어난다 — 이 게이트에 진입했을 때 이미 봉인돼 있으면 그대로 통과.
    """
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is not None or pkg["escalated"]:
            continue

        new_retry = pkg["retry_count"] + 1
        escalated = new_retry > MAX_GATE_RETRIES
        packages[pos] = cast(
            PackageState,
            {
                **pkg,
                "retry_count": new_retry,
                "escalated": escalated,
                "last_checked_at": now,
                "policy_version_applied": POLICY_VERSION,
            },
        )
        if escalated:
            print(
                f"  [에스컬레이션] {pkg['package_id']} 미봉인 retry_count={new_retry} "
                f"join_waiting_since={pkg['join_waiting_since']}"
            )
        else:
            print(f"  [재시도] {pkg['package_id']} 미봉인 retry_count={new_retry}")

    waiting = sum(1 for p in packages if p["tracking_number"] is None and not p["escalated"])
    print(f"[조립대기게이트] 완료 - 대기중(재시도 예산 남음) {waiting}개")
    return {"packages": packages}


def route_after_assembly_wait_gate(state: GraphState) -> str:
    """조건분기: 재시도 예산이 남은 미봉인 패키지가 있으면 재시도."""
    pending = any(
        pkg["tracking_number"] is None and not pkg["escalated"] for pkg in state.get("packages", [])
    )
    return "retry" if pending else "proceed"


def in_transit_delay_gate(state: GraphState) -> GraphState:
    """배송중게이트: 봉인된 Package의 delay_categories 체크.

    자연재해는 재시도 없이 즉시 escalated=true. 그 외 지연은 매 틱마다 Supervisor에게
    조기 에스컬레이션 여부를 먼저 물어보고(predict_delay_escalation), Supervisor가
    "아직 지켜봐도 됨"이라고 하면 기존 재시도 예산(retry_count>MAX_GATE_RETRIES) 임계치로
    폴백한다 — Supervisor 판단이 고정 임계치를 대체하는 게 아니라, 그보다 먼저 나서는
    조기경보 경로를 하나 더 추가하는 구조.
    """
    order = state["order"]
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is None or pkg["escalated"]:
            continue

        categories, resolve_at = _PACKAGE_DELAY_SIGNAL.get(pkg["delivery_address_id"], ([], None))

        if "자연재해" in categories:
            packages[pos] = cast(
                PackageState,
                {
                    **pkg,
                    "delay_categories": categories,
                    "escalated": True,
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                },
            )
            print(f"  [즉시에스컬레이션] {pkg['package_id']} 자연재해")
            continue

        if not categories:
            if pkg["delay_categories"]:
                packages[pos] = cast(
                    PackageState,
                    {**pkg, "delay_categories": [], "escalation_reasoning": None, "last_checked_at": now},
                )
            continue

        if resolve_at is not None and pkg["retry_count"] >= resolve_at:
            packages[pos] = cast(
                PackageState,
                {
                    **pkg,
                    "delay_categories": [],
                    "escalation_reasoning": None,
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                },
            )
            print(f"  [해소] {pkg['package_id']} {categories} → 지연없음")
            continue

        low_stock_item_count = sum(
            1 for item in order["item_list"] if item["item_delay_reason"] == "재고부족"
        )
        elapsed_hours = (
            datetime.fromisoformat(now) - datetime.fromisoformat(order["order_created_at"])
        ).total_seconds() / 3600
        prediction = predict_delay_escalation(
            DelayRiskSignals(
                package_id=pkg["package_id"],
                delay_categories=categories,
                retry_count=pkg["retry_count"],
                low_stock_item_count=low_stock_item_count,
                elapsed_hours_since_order=elapsed_hours,
            )
        )

        if prediction.escalate_now:
            packages[pos] = cast(
                PackageState,
                {
                    **pkg,
                    "delay_categories": categories,
                    "escalated": True,
                    "escalation_reasoning": prediction.reasoning,
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                },
            )
            print(f"  [Supervisor 조기에스컬레이션] {pkg['package_id']} {categories} retry_count={pkg['retry_count']}")
            continue

        new_retry = pkg["retry_count"] + 1
        escalated = new_retry > MAX_GATE_RETRIES
        packages[pos] = cast(
            PackageState,
            {
                **pkg,
                "delay_categories": categories,
                "retry_count": new_retry,
                "escalated": escalated,
                "escalation_reasoning": prediction.reasoning,
                "last_checked_at": now,
                "policy_version_applied": POLICY_VERSION,
            },
        )
        if escalated:
            print(f"  [에스컬레이션] {pkg['package_id']} {categories} retry_count={new_retry}")
        else:
            print(f"  [재시도] {pkg['package_id']} {categories} retry_count={new_retry}")

    print("[배송중게이트] 완료")
    return {"packages": packages}


def route_after_in_transit_gate(state: GraphState) -> str:
    """조건분기: 재시도 예산이 남은 지연 패키지가 있으면 재시도."""
    pending = any(
        pkg["tracking_number"] is not None and pkg["delay_categories"] and not pkg["escalated"]
        for pkg in state.get("packages", [])
    )
    return "retry" if pending else "proceed"
