"""LangGraph 물류 에이전트 POC — 데모 실행."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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
    print("시나리오 5: 재시도 후 통과 (피킹지연게이트: 재고부족 해소 / 배송중게이트: 교통지연 해소)")
    print("=" * 60)
    result_retry_pass = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 재고부족 → 피킹지연게이트가 2회 재시도 후 해소 → 피킹완료
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
    print("시나리오 6: Stage1 회복불가 판정 → 품목취소 (피킹지연게이트)")
    print("=" * 60)
    result_item_cancel = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 파손 → 회복불가 분류(재시도로도 영구 미해소) → 3회 재시도 소진 후 Stage1이
                    # 즉시 자동으로 품목취소 확정 (item_status="취소됨"). 이 주소엔 이 item뿐이라
                    # 패키지 자체가 만들어지지 않고, 남은 배송 대상이 없어 internal_order_status는
                    # "전체무산"(전부취소의 vacuous case)으로 종결된다
                    "item_id": "SKU-103",
                    "delivery_address_id": "ADDR-HOME",
                    "item_delay_reason": "파손",
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_item_cancel)

    print()
    print("=" * 60)
    print("시나리오 7: 즉시 보상조치 (배송중게이트: 자연재해는 재시도 없이 바로 환불)")
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

    print()
    print("=" * 60)
    print("시나리오 8: 포장agent+추적agent 풀 사이클 (배송지 2곳, 지연 없음) → 완료")
    print("=" * 60)
    result_full_cycle = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    "item_id": "SKU-201",
                    "delivery_address_id": "ADDR-HOME",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
                {
                    # 주소록에 없는 신규주소 → ADDR-OFFICE와 달리 고정 지연신호 안 붙음(진짜 무지연 확인용)
                    "item_id": "SKU-202",
                    "delivery_address": {
                        "recipient": "홍길순",
                        "phone": "010-4444-5555",
                        "postal_code": "35240",
                        "address_line": "대전광역시 유성구 대학로 99",
                    },
                    "location": {"zone": "B", "shelf": "02", "bin": "02"},
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_full_cycle)

    print()
    print("=" * 60)
    print("시나리오 9: Stage1 회복가능 판정 + 부분수령희망 → 지연 item 제외하고 형제 item만 배송")
    print("=" * 60)
    result_partial_fulfillment = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 통관지연 → 회복가능이지만 resolve_at=None이라 재시도로는 절대 안 풀림 →
                    # 3회 재시도 소진 후 Stage1이 fulfillment_preference_on_delay="부분수령희망"을
                    # 참조해 자동 적용 → 이 item은 패키지조립agent 그룹핑에서 영구 제외된다
                    "item_id": "SKU-601",
                    "delivery_address_id": "ADDR-HOME",
                    "item_delay_reason": "통관지연",
                },
                {
                    # 같은 배송지의 정상 item — 지연 item과 묶이지 않고 단독으로 봉인/배송돼야 함
                    "item_id": "SKU-602",
                    "delivery_address_id": "ADDR-HOME",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
            ],
            "payment_status_hint": "완료",
            "fulfillment_preference_on_delay_hint": "부분수령희망",
        }
    )
    _print_result(result_partial_fulfillment)

    print()
    print("=" * 60)
    print("시나리오 10: Stage1 회복가능 판정 + 계속대기희망 → 패키지가 끝내 미봉인 → 보상조치(환불)")
    print("=" * 60)
    result_continue_waiting = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # 통관지연 + 계속대기희망 → Stage1이 그룹핑에서 제외하지 않고 계속 대기시킴 →
                    # 이 배송지엔 이 item뿐이라 패키지가 영원히 미봉인 → 포장대기게이트 자체 재시도
                    # 예산(MAX_GATE_RETRIES)도 소진 → 보상조치(환불)로 귀결
                    "item_id": "SKU-701",
                    "delivery_address_id": "ADDR-OFFICE",
                    "item_delay_reason": "통관지연",
                },
            ],
            "payment_status_hint": "완료",
            "fulfillment_preference_on_delay_hint": "계속대기희망",
        }
    )
    _print_result(result_continue_waiting)

    print()
    print("=" * 60)
    print("시나리오 11: Supervisor 조기 판정 대조 - retry_count=0인데도 회복불가로 볼 수 있는가")
    print("=" * 60)
    print("(Google Gemini 실제 호출. GOOGLE_API_KEY 미설정 시 predict_delay_escalation이 폴백해서")
    print(" escalate_now=False로 처리되고, 이 경우 아래는 시나리오5와 동일하게 정상 해소로 끝남.")
    print(" escalate_now=True가 나오면 회복불가로 재해석돼 즉시 보상조치(환불)로 귀결된다)")
    old_order_created_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    result_supervisor_predict = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # ADDR-OFFICE는 교통지연(resolve_at=1)이라 고정 카운터만 보면 재시도 1번이면
                    # 곧 해소될 상황. 하지만 order_created_at을 10일 전으로 못박아서 Supervisor에게
                    # "이 주문 자체가 이미 오래 묶여있다"는 맥락을 줌 — retry_count=0인 첫 틱에서
                    # Supervisor가 그래도 조기 에스컬레이션할지가 대조 포인트
                    "item_id": "SKU-401",
                    "delivery_address_id": "ADDR-OFFICE",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
            ],
            "payment_status_hint": "완료",
            "order_created_at_hint": old_order_created_at,
        }
    )
    _print_result(result_supervisor_predict)

    print()
    print("=" * 60)
    print("시나리오 12: 배송지 2곳, 한쪽만 지연 → 무지연 패키지가 지연 패키지 해소까지 블로킹되는지 확인")
    print("=" * 60)
    result_partial_block = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": [
                {
                    # ADDR-HOME → 교통지연(resolve_at=1), 1틱 재시도 후 해소되는 패키지
                    "item_id": "SKU-501",
                    "delivery_address_id": "ADDR-HOME",
                    "location": {"zone": "A", "shelf": "01", "bin": "01"},
                },
                {
                    # ADDR-OFFICE → _PACKAGE_DELAY_SIGNAL에 없는 완전히 깨끗한 item.
                    # 원칙6대로라면 SKU-501의 지연과 무관하게 즉시 mock_carrier_signal로 전진해야 한다
                    "item_id": "SKU-505",
                    "delivery_address_id": "ADDR-OFFICE",
                    "location": {"zone": "B", "shelf": "02", "bin": "02"},
                },
            ],
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_partial_block)


def _print_result(state: dict) -> None:
    order = state.get("order", {})
    summary = {
        "validation_passed": state.get("validation_passed"),
        "validation_errors": state.get("validation_errors"),
        "supervisor_decision": state.get("supervisor_decision"),
        "order": {
            "order_id": order.get("order_id"),
            "order_created_at": order.get("order_created_at"),
            "internal_order_status": order.get("internal_order_status"),
            "payment_status": order.get("payment_status"),
            "fulfillment_preference_on_delay": order.get("fulfillment_preference_on_delay"),
            "cancel_requested_at": order.get("cancel_requested_at"),
            "cancel_status": order.get("cancel_status"),
            "delivery_addresses": [
                {
                    "address_id": addr["address_id"],
                    "recipient": addr["recipient"],
                    "phone": addr["phone"],
                    "postal_code": addr["postal_code"],
                    "address_line": addr["address_line"],
                }
                for addr in order.get("delivery_addresses", [])
            ],
            "item_list": order.get("item_list"),
            "current_item_index": order.get("current_item_index"),
            "notification_enabled": order.get("notification_enabled"),
            "trace_id": order.get("trace_id"),
        },
        "packages": [
            {
                "package_id": pkg["package_id"],
                "source_items": pkg["source_items"],
                "delivery_address_id": pkg["delivery_address_id"],
                "required_item_count": pkg["required_item_count"],
                "arrived_item_count": pkg["arrived_item_count"],
                "tracking_number": pkg["tracking_number"],
                "current_gps": pkg["current_gps"],
                "join_waiting_since": pkg["join_waiting_since"],
                "delay_categories": pkg["delay_categories"],
                "retry_count": pkg["retry_count"],
                "last_checked_at": pkg["last_checked_at"],
                "compensation": pkg["compensation"],
                "escalation_reasoning": pkg["escalation_reasoning"],
                "policy_version_applied": pkg["policy_version_applied"],
                "notification_log": pkg["notification_log"],
            }
            for pkg in state.get("packages", [])
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
