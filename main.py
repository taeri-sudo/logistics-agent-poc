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
    print("시나리오 2: payment_status=완료 → 검증 통과 → Supervisor → 창고처리")
    print("=" * 60)
    result_pass = app.invoke(
        {
            "user_id": "user-001",
            "confirmed_order_items": base_items,
            "payment_status_hint": "완료",
        }
    )
    _print_result(result_pass)


def _print_result(state: dict) -> None:
    summary = {
        "validation_passed": state.get("validation_passed"),
        "validation_errors": state.get("validation_errors"),
        "supervisor_decision": state.get("supervisor_decision"),
        "order": {
            "order_id": state.get("order", {}).get("order_id"),
            "internal_order_status": state.get("order", {}).get("internal_order_status"),
            "payment_status": state.get("order", {}).get("payment_status"),
            "item_list": state.get("order", {}).get("item_list"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run_demo()
