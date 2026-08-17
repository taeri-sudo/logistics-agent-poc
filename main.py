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

    print()
    print("=" * 60)
    print("시나리오 4: 지연 없음 → 3개 게이트 모두 self-loop 없이 1회 통과")
    print("=" * 60)
    result_clean = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    "item_id": "SKU-101",
                    "delivery_address_id": "ADDR-HOME",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_clean)

    print()
    print("=" * 60)
    print("시나리오 5: 재시도 후 통과 (출고전게이트: 재고부족 해소 / 배송중게이트: 교통지연 해소)")
    print("=" * 60)
    result_retry_pass = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 재고부족 → 출고전게이트가 2회 재시도 후 해소 → 피킹완료
                    "item_id": "SKU-102",
                    "delivery_address_id": "ADDR-OFFICE",
                    "item_delay_reason": "재고부족",
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_retry_pass)

    print()
    print("=" * 60)
    print("시나리오 6: 재시도 초과 에스컬레이션 (출고전게이트→조립대기게이트 연쇄)")
    print("=" * 60)
    result_escalate_chain = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 파손 → 재시도로 영구 미해소 → 출고전게이트 3회 재시도 후 item escalated=true
                    # → 패키지도 영원히 미봉인 → 조립대기게이트도 3회 재시도 후 package escalated=true
                    "item_id": "SKU-103",
                    "delivery_address_id": "ADDR-HOME",
                    "item_delay_reason": "파손",
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_escalate_chain)

    print()
    print("=" * 60)
    print("시나리오 7: 즉시 에스컬레이션 (배송중게이트: 자연재해는 재시도 없이 바로 escalated=true)")
    print("=" * 60)
    result_disaster = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    "item_id": "SKU-104",
                    "delivery_address_id": "ADDR-STORM",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_disaster)


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
                "delay_categories": pkg["delay_categories"],
                "retry_count": pkg["retry_count"],
                "escalated": pkg["escalated"],
                "policy_version_applied": pkg["policy_version_applied"],
            }
            for pkg in state.get("packages", [])
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
