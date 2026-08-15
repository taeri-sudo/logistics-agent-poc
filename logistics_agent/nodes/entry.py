"""진입 노드: UserProfile 조회, 주문요청agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from logistics_agent.data.mock_profiles import MOCK_USER_PROFILES
from logistics_agent.state import GraphState, Item, OrderState


def user_profile_lookup(state: GraphState) -> GraphState:
    """로그인 세션에서 delivery_address, payment_method, notification_enabled 로드."""
    user_id = state["user_id"]
    profile = MOCK_USER_PROFILES.get(user_id)

    if profile is None:
        raise ValueError(f"UserProfile not found: {user_id}")

    print(f"[UserProfile 조회] user_id={user_id}, notification_enabled={profile['notification_enabled']}")
    return {"user_profile": profile}


def order_request_agent(state: GraphState) -> GraphState:
    """확정된 주문내역으로 item_list 생성."""
    profile = state["user_profile"]
    confirmed_items = state.get("confirmed_order_items", [])

    now = datetime.now(timezone.utc).isoformat()
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    trace_id = uuid.uuid4().hex

    item_list: list[Item] = []
    for idx, raw in enumerate(confirmed_items):
        item_list.append(
            {
                "item_id": raw.get("item_id", f"ITEM-{idx + 1:03d}"),
                "item_status": "대기",
                "item_delay_reason": None,
                "package_ref": None,
                "location": raw.get("location"),
                "customer_facing_status": "주문접수",
            }
        )

    payment_status = state.get("payment_status_hint", "대기")

    order: OrderState = {
        "order_id": order_id,
        "order_created_at": now,
        "delivery_address": profile["delivery_address"],
        "payment_status": payment_status,
        "split_delivery_preference": False,
        "cancel_requested_at": None,
        "cancel_status": None,
        "internal_order_status": "접수",
        "item_list": item_list,
        "current_item_index": 0,
        "notification_enabled": profile["notification_enabled"],
        "trace_id": trace_id,
    }

    print(f"[주문요청agent] order_id={order_id}, items={len(item_list)}")
    return {"order": order}
