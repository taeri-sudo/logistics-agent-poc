"""관문 노드: 주문검증agent — payment_status, 배송지 검증 → 통과/실패."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from logistics_agent.state import GraphState, OrderState


def _is_valid_address(address: Mapping[str, object]) -> bool:
    """필수 필드가 실제로 채워졌는지 검사.

    Address가 아닌 Mapping으로 받는 이유: 이 함수는 "키가 누락됐을 수 있는 데이터"를 검사하는데,
    Address는 total=True라 모든 키가 있다고 단언한다. 타입을 Address로 좁히면 검사 자체가 자기모순이 되고,
    동적 키 조회(`.get(field)`)도 TypedDict에선 리터럴 키만 허용돼 막힌다.
    """
    required = ("recipient", "phone", "postal_code", "address_line")
    return all(address.get(field) for field in required)


def order_validation_agent(state: GraphState) -> GraphState:
    order = state["order"]
    errors: list[str] = []

    if order["payment_status"] != "완료":
        errors.append(f"payment_status={order['payment_status']} (완료 필요)")

    delivery_addresses = order["delivery_addresses"]
    if not delivery_addresses:
        errors.append("delivery_addresses 비어 있음")

    for address in delivery_addresses:
        if not _is_valid_address(address):
            errors.append(f"{address.get('address_id')}: delivery_address 필수 필드 누락")

    # item의 배송지 참조가 실제로 해석됐는지 (주소록에 없는 id는 여기서 걸린다)
    known_ids = {address["address_id"] for address in delivery_addresses}
    for item in order["item_list"]:
        if item["delivery_address_id"] not in known_ids:
            errors.append(
                f"{item['item_id']}: delivery_address_id={item['delivery_address_id']} 참조 불가"
            )

    passed = len(errors) == 0
    status = "통과" if passed else "실패"
    print(f"[주문검증agent] {status}: {errors or 'OK'}")

    updates: GraphState = {
        "validation_passed": passed,
        "validation_errors": errors,
    }

    if not passed:
        order = cast(OrderState, {**order, "internal_order_status": "검증실패"})
        updates["order"] = order

    return updates


def route_after_validation(state: GraphState) -> str:
    """조건분기: 통과 → supervisor, 실패 → END."""
    return "supervisor" if state.get("validation_passed") else "end"
