"""판단+반복 노드: 지연체크게이트 3종 — 피킹지연(Item)/조립대기(미봉인 Package)/배송중(봉인 Package).

셋 다 같은 뼈대: 조건 미해소면 자기 자신으로 self-loop. Item(피킹지연게이트)은 재시도 예산을
넘기면 Stage1 판정(회복불가→품목취소 / 회복가능→선호도 자동적용)으로 즉시 귀결되고,
Package(포장대기게이트/배송중게이트)는 재시도 예산을 넘기거나 회복불가로 분류되면 보상조치
(환불) 실행으로 즉시 귀결된다 — 어느 쪽도 "escalated"로 표시만 해두고 사람을 기다리는 대기
상태를 persist하지 않는다(v16 재설계, DESIGN.md "사람 개입 워크플로우" 참고).
"""

from __future__ import annotations

from datetime import datetime
from typing import cast

from logistics_agent.enums import ItemDelayReason
from logistics_agent.nodes._common import _now
from logistics_agent.nodes.supervisor import DelayRiskSignals, predict_delay_escalation
from logistics_agent.state import CompensationRecord, GraphState, Item, OrderState, PackageState, ResolvedDecision

MAX_GATE_RETRIES = 3
POLICY_VERSION = "DELAY-POLICY-v1"

# 데모용 고정 해소 시점 (실제로는 재고센서/외부 API 폴링 결과). retry_count가 이 값 이상이면 해소.
# None이면 재시도로는 해소되지 않음 — 반드시 Stage1 판정으로 귀결된다.
# ItemDelayReason(Literal)이 늘어날 때 이 딕셔너리 등록을 깜빡하면 아래 룩업이 KeyError로 즉시
# 죽는다 — 의도한 동작이다. .get()으로 조용히 넘기면 미등록 reason이 "파손"(resolve_at=None)과
# 똑같이 취급돼 재시도만 소모하다 Stage1 판정으로 가는데, 로그로는 등록 누락과 구분이 안 된다.
_ITEM_RESOLVE_AT_RETRY: dict[ItemDelayReason, int | None] = {
    "재고부족": 2,
    "검수불량": 1,
    "파손": None,
    "통관지연": None,
}

# "해소 시점(resolve_at)"과 "회복가능 여부"는 서로 다른 축이다 — resolve_at=None이 계속
# "회복불가"를 암묵적으로 겸하면 "회복가능인데 재시도로는 절대 안 풀리는" 사유(통관지연)를
# 표현할 수 없다. 그래서 별도 매핑으로 분리한다.
_ITEM_RECOVERABLE: dict[ItemDelayReason, bool] = {
    "재고부족": True,
    "검수불량": True,
    "파손": False,
    "통관지연": True,
}

# 데모용 고정 지연 신호 (실제로는 물류사 API/GPS 폴링). package_id는 uuid라 사전에 못 박을 수 없어
# item_id를 키로 대신 쓴다 (item_id는 데모 스크립트가 미리 정하는 값이라 예측 가능).
# delivery_address_id였다가 item_id로 교체함 — 같은 배송지로 가는 패키지가 여럿이면
# 전부 같은 지연을 공유해버리는 문제가 있었음(상세: JOURNAL.md 4단계 후속 참고).
# (categories, 해소에 필요한 retry_count / None=영구미해소)
_PACKAGE_DELAY_SIGNAL: dict[str, tuple[list[str], int | None]] = {
    "SKU-102": (["교통지연"], 1),
    "SKU-104": (["자연재해"], None),
    "SKU-401": (["교통지연"], 1),
    "SKU-501": (["교통지연"], 1),
    "SKU-502": (["자연재해"], None),
}


def _lookup_package_delay_signal(pkg: PackageState) -> tuple[list[str], int | None]:
    """패키지에 속한 item_id 중 첫 매칭을 반환 (item_id 키잉 — 위 주석 참고)."""
    for source in pkg["source_items"]:
        signal = _PACKAGE_DELAY_SIGNAL.get(source["item_id"])
        if signal is not None:
            return signal
    return ([], None)


def picking_delay_gate(state: GraphState) -> GraphState:
    """피킹지연게이트: item_delay_reason이 있는 item만 대상으로 해소 여부 재확인.

    재시도 예산을 넘기면 Stage1 판정을 같은 tick 안에서 자동으로 끝낸다 — 회복불가면
    품목취소, 회복가능이면 fulfillment_preference_on_delay를 참조해 부분수령/계속대기를
    자동 적용한다. 진짜 사람이 개입하는 별도 진입점은 아직 없어(경로B 미구현) 이 판정은
    항상 즉시 자동 해소된다 — pending_decision은 그 미래를 위한 스키마 자리일 뿐이다.
    """
    order = state["order"]
    item_list: list[Item] = list(order["item_list"])
    preference = order["fulfillment_preference_on_delay"]
    now = _now()

    for idx, item in enumerate(item_list):
        reason = item["item_delay_reason"]
        if not reason or item["decision_log"]:
            continue

        resolve_at = _ITEM_RESOLVE_AT_RETRY[reason]
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
        if new_retry <= MAX_GATE_RETRIES:
            item_list[idx] = cast(
                Item,
                {
                    **item,
                    "retry_count": new_retry,
                    "customer_facing_status": "지연",
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                },
            )
            print(f"  [재시도] item_id={item['item_id']} {reason} retry_count={new_retry}")
            continue

        recoverable = _ITEM_RECOVERABLE[reason]
        decision: ResolvedDecision = {
            "decision_type": "품목_회복가능성_판단",
            "decided_at": now,
            "reasoning": "",
            "outcome": "",
        }

        if not recoverable:
            decision["outcome"] = "회복불가_품목취소"
            decision["reasoning"] = f"{reason}은(는) 회복불가 사유로 분류돼 품목 단위 취소 확정"
            item_list[idx] = cast(
                Item,
                {
                    **item,
                    "retry_count": new_retry,
                    "item_status": "취소됨",
                    "customer_facing_status": "상품준비불가",
                    "last_checked_at": now,
                    "policy_version_applied": POLICY_VERSION,
                    "decision_log": [*item["decision_log"], decision],
                },
            )
            print(f"  [품목취소] item_id={item['item_id']} {reason} → 취소됨")
            continue

        if preference == "부분수령희망":
            decision["outcome"] = "회복가능_부분수령적용"
            decision["reasoning"] = f"{reason} 회복가능, 구매자 선호도(부분수령희망) 적용 - 그룹핑 제외"
            print(f"  [부분수령적용] item_id={item['item_id']} {reason} → 그룹핑 제외, 이후 별도 처리")
        else:
            decision["outcome"] = "회복가능_계속대기적용"
            decision["reasoning"] = f"{reason} 회복가능, 구매자 선호도(계속대기희망 또는 미설정) 적용 - 계속 대기"
            print(f"  [계속대기적용] item_id={item['item_id']} {reason} → 계속 대기")

        item_list[idx] = cast(
            Item,
            {
                **item,
                "retry_count": new_retry,
                "customer_facing_status": "지연",
                "last_checked_at": now,
                "policy_version_applied": POLICY_VERSION,
                "decision_log": [*item["decision_log"], decision],
            },
        )

    order = cast(OrderState, {**order, "item_list": item_list})
    print(f"[피킹지연게이트] 완료 - 미해소 지연 item {sum(1 for i in item_list if i['item_delay_reason'])}개")
    return {"order": order}


def route_after_picking_gate(state: GraphState) -> str:
    """조건분기: 해소 대기 중인(Stage1 판정을 아직 못 받은) 지연 item이 남아있으면 재시도."""
    pending = any(
        item["item_delay_reason"] and not item["decision_log"] for item in state["order"]["item_list"]
    )
    return "retry" if pending else "proceed"


def _compensate(pkg: PackageState, reasoning: str, now: str) -> PackageState:
    """Package 보상조치(환불) 실행 — 포장대기게이트/배송중게이트 공통. POC 범위: 환불만
    (재발송은 fulfillment 재진입이 필요한 별도 과제 — 확장 지점)."""
    compensation: CompensationRecord = {"action": "환불", "executed_at": now}
    return cast(
        PackageState,
        {**pkg, "compensation": compensation, "escalation_reasoning": reasoning, "last_checked_at": now},
    )


def packaging_wait_gate(state: GraphState) -> GraphState:
    """포장대기게이트: 미봉인 Package를 감시만 한다 (순수 워처, 스스로 해소하지 않음).

    실제 해소는 피킹지연게이트가 item_delay_reason을 풀고 패키지조립agent가 재봉인하는
    경로로만 일어난다 — 이 게이트에 진입했을 때 이미 봉인돼 있으면 그대로 통과. 재시도
    예산이 소진되면(전형적으로 "계속대기희망"으로 결정된 item을 영원히 기다리다 끝내
    실패한 경우) 더 이상 기다리지 않고 보상조치(환불)로 귀결한다.
    """
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is not None or pkg["compensation"] is not None:
            continue

        new_retry = pkg["retry_count"] + 1
        if new_retry > MAX_GATE_RETRIES:
            packages[pos] = _compensate(
                pkg, f"재시도 예산 소진(retry_count={new_retry}) - 미봉인 상태 지속으로 보상조치", now
            )
            print(f"  [보상조치] {pkg['package_id']} 미봉인 retry_count={new_retry} → 환불")
        else:
            packages[pos] = cast(
                PackageState,
                {**pkg, "retry_count": new_retry, "last_checked_at": now, "policy_version_applied": POLICY_VERSION},
            )
            print(f"  [재시도] {pkg['package_id']} 미봉인 retry_count={new_retry}")

    waiting = sum(1 for p in packages if p["tracking_number"] is None and p["compensation"] is None)
    print(f"[포장대기게이트] 완료 - 대기중(재시도 예산 남음) {waiting}개")
    return {"packages": packages}


def route_after_packaging_wait_gate(state: GraphState) -> str:
    """조건분기: 재시도 예산이 남은 미봉인 패키지가 있으면 재시도."""
    pending = any(
        pkg["tracking_number"] is None and pkg["compensation"] is None
        for pkg in state.get("packages", [])
    )
    return "retry" if pending else "proceed"


def in_transit_delay_gate(state: GraphState) -> GraphState:
    """배송중게이트: 봉인된 Package의 delay_categories 체크.

    자연재해는 재시도 없이 즉시 보상조치(환불). 그 외 지연은 매 틱마다 Supervisor에게
    회복가능 여부를 먼저 물어보고(predict_delay_escalation, escalate_now=True를 "회복불가"로
    재해석), 회복불가로 나오면 즉시 보상조치. 회복가능(escalate_now=False)이면 기존 재시도
    예산으로 지켜보다가, 예산까지 소진되면(끝내 해소 안 됨) 안전장치로 보상조치에 수렴한다 —
    사람을 기다리는 "escalated" 대기 상태를 persist하지 않는다.

    舊 구조에서는 배송 시작 전 한 번만 호출됐지만, order-wide 블로킹 gap 수정(DESIGN.md 참고)
    이후로는 mock_carrier_signal/추적agent와 하나의 통합 루프로 묶여 배송 진행 중에도 매 틱
    재호출된다. `_lookup_package_delay_signal`은 item_id 기반 고정 매핑이라 이미 해소된 패키지를
    다시 봐도 똑같은 신호를 돌려주는데, "이미 해소됨"과 "아직 한 번도 안 봄"을 구분할 안전한
    필드가 없다(`retry_count`/`policy_version_applied` 모두 포장대기게이트와 공유돼 재사용
    불가 — 시도했다가 첫 방문까지 걷어차는 버그로 확인). 그래서 해소 분기는 재실행돼도
    `delay_categories`를 다시 []로 세팅할 뿐이라 멱등하고, 로그만 재실행 시 `was_active`로
    걸러 첫 해소 순간에만 찍는다(아래 참고).
    """
    order = state["order"]
    packages: list[PackageState] = list(state.get("packages", []))
    now = _now()

    for pos, pkg in enumerate(packages):
        if pkg["tracking_number"] is None or pkg["compensation"] is not None:
            continue

        categories, resolve_at = _lookup_package_delay_signal(pkg)

        if "자연재해" in categories:
            packages[pos] = _compensate(
                cast(PackageState, {**pkg, "delay_categories": categories}),
                "자연재해 감지로 즉시 보상조치 (규칙 기반, Supervisor 미개입)",
                now,
            )
            print(f"  [보상조치] {pkg['package_id']} 자연재해 → 환불")
            continue

        if not categories:
            if pkg["delay_categories"]:
                packages[pos] = cast(
                    PackageState,
                    {**pkg, "delay_categories": [], "escalation_reasoning": None, "last_checked_at": now},
                )
            continue

        if resolve_at is not None and pkg["retry_count"] >= resolve_at:
            was_active = bool(pkg["delay_categories"])
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
            # 정적 매핑(_lookup_package_delay_signal)은 이미 해소된 패키지를 다시 봐도 같은
            # 신호를 돌려줘 이 분기가 이후 틱에도 계속 재실행된다(멱등, 위 docstring 참고) —
            # was_active로 "진짜 지금 막 해소되는 순간"에만 로그를 남겨 중복 출력을 막는다.
            if was_active:
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
            packages[pos] = _compensate(
                cast(PackageState, {**pkg, "delay_categories": categories}), prediction.reasoning, now
            )
            print(f"  [보상조치] {pkg['package_id']} Supervisor 회복불가 판정 → 환불")
            continue

        new_retry = pkg["retry_count"] + 1
        if new_retry > MAX_GATE_RETRIES:
            packages[pos] = _compensate(
                cast(PackageState, {**pkg, "delay_categories": categories}),
                f"재시도 예산 소진(retry_count={new_retry}), 회복가능으로 지켜봤으나 끝내 미해소 - 보상조치",
                now,
            )
            print(f"  [보상조치] {pkg['package_id']} {categories} retry_count={new_retry} → 환불")
            continue

        packages[pos] = cast(
            PackageState,
            {
                **pkg,
                "delay_categories": categories,
                "retry_count": new_retry,
                "escalation_reasoning": prediction.reasoning,
                "last_checked_at": now,
                "policy_version_applied": POLICY_VERSION,
            },
        )
        print(f"  [재시도] {pkg['package_id']} {categories} retry_count={new_retry}")

    print("[배송중게이트] 완료")
    return {"packages": packages}


# route_after_in_transit_gate는 제거됐다 (order-wide 블로킹 gap 수정) — "미해소 지연 패키지가
# 있는가" 조건은 tracking.py의 route_after_in_transit_cycle이 "미배송 item이 있는가" 조건과
# 합쳐서 대신 판단한다. 두 조건이 사실상 하나의 종료 판단이라 라우터를 통합했다 (DESIGN.md 참고).
