"""LangGraph 물류 에이전트 POC — 데모 실행."""

from __future__ import annotations

import json

from logistics_agent.graph import app


def run_demo() -> None:
    base_items = [
        {
            "item_id": "SKU-001",
            "location": {"zone": "A", "shelf": "12", "bin": "04"},
        },
        {
            "item_id": "SKU-002",
            "location": {"zone": "B", "shelf": "03", "bin": "01"},
        },
    ]

    print("=" * 60)
    print("시나리오 1: payment_status=대기 → 검증 실패 (Supervisor 미진입)")
    print("=" * 60)
    result_fail = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": base_items,
        }
    )
    _print_result(result_fail)

    print()
    print("=" * 60)
    print("시나리오 2: payment_status=완료 → 검증 통과 → Supervisor → 창고처리 → 패키지조립")
    print("=" * 60)
    result_pass = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": base_items,
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_pass)

    print()
    print("=" * 60)
    print("시나리오 3: 배송지 3곳(주소록2 + 신규1) + 재고부족 1건 → 봉인 2 / 대기 1")
    print("=" * 60)
    split_items = [
        {
            "item_id": "SKU-001",
            "delivery_address_id": "ADDR-HOME",
            "location": {"zone": "A", "shelf": "12", "bin": "04"},
        },
        {
            "item_id": "SKU-002",
            "delivery_address_id": "ADDR-HOME",
            "location": {"zone": "B", "shelf": "03", "bin": "01"},
        },
        {
            "item_id": "SKU-003",
            "delivery_address_id": "ADDR-OFFICE",
            "location": {"zone": "C", "shelf": "07", "bin": "02"},
        },
        {
            # 재고부족 → 피킹 스킵 → ADDR-OFFICE 패키지는 required=2 arrived=1 로 대기
            "item_id": "SKU-004",
            "delivery_address_id": "ADDR-OFFICE",
            "item_delay_reason": "재고부족",
        },
        {
            # 주문 시점 신규주소 (주소록에 없음) → 새 address_id 발급
            "item_id": "SKU-005",
            "delivery_address": {
                "recipient": "홍길순",
                "phone": "010-2222-3333",
                "postal_code": "13529",
                "address_line": "경기도 성남시 분당구 판교역로 235",
            },
            "location": {"zone": "D", "shelf": "01", "bin": "09"},
        },
    ]
    result_split = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": split_items,
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_split)


def _print_result(state: dict) -> None:
    order = state.get("order", {})
    summary = {
        "validation_passed": state.get("validation_passed"),
        "validation_errors": state.get("validation_errors"),
        "supervisor_decision": state.get("supervisor_decision"),
        "order": {
            "order_id": order.get("order_id"),
            "internal_order_status": order.get("internal_order_status"),
            "payment_status": order.get("payment_status"),
            "delivery_addresses": [
                {"address_id": addr["address_id"], "address_line": addr["address_line"]}
                for addr in order.get("delivery_addresses", [])
            ],
            "item_list": order.get("item_list"),
        },
        "packages": [
            {
                "package_id": pkg["package_id"],
                "delivery_address_id": pkg["delivery_address_id"],
                "required_item_count": pkg["required_item_count"],
                "arrived_item_count": pkg["arrived_item_count"],
                "tracking_number": pkg["tracking_number"],
                "join_waiting_since": pkg["join_waiting_since"],
            }
            for pkg in state.get("packages", [])
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
