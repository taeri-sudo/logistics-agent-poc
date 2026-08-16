"""진입 노드: UserProfile 조회, 주문요청agent."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import cast

from logistics_agent.data.mock_profiles import MOCK_USER_PROFILES
from logistics_agent.state import Address, GraphState, Item, OrderState


def user_profile_lookup(state: GraphState) -> GraphState:
    """로그인 세션에서 delivery_addresses, payment_method, notification_enabled 로드."""
    user_id = state["user_id"]
    profile = MOCK_USER_PROFILES.get(user_id)

    if profile is None:
        raise ValueError(f"UserProfile not found: {user_id}")

    print(
        f"[UserProfile 조회] user_id={user_id}, addresses={len(profile['delivery_addresses'])}, "
        f"notification_enabled={profile['notification_enabled']}"
    )
    return {"user_profile": profile}


def _resolve_item_addresses(
    profile_addresses: list[Address],
    confirmed_items: list[dict],
) -> tuple[list[str], list[Address]]:
    """item별 delivery_address_id를 해석하고, 실제 참조된 주소만 최초 참조 순서로 모아 반환.

    우선순위: delivery_address_id(주소록 참조) > delivery_address(주문 시점 신규주소) > 주소록[0].
    주소록에 없는 id는 crash시키지 않고 그대로 남긴다 — 관문 노드(주문검증agent)가 걸러낸다.
    """
    book = {addr["address_id"]: addr for addr in profile_addresses}
    default_id = profile_addresses[0]["address_id"] if profile_addresses else ""
    inline_ids: dict[tuple[str, str], str] = {}  # (postal_code, address_line) → 부여한 id
    used: dict[str, Address] = {}  # dict 삽입순서 = 최초 참조 순서

    address_ids: list[str] = []
    for raw in confirmed_items:
        raw_id = raw.get("delivery_address_id")
        inline = raw.get("delivery_address")

        if raw_id:
            addr_id = raw_id
            if raw_id in book:
                used.setdefault(raw_id, book[raw_id])
        elif inline:
            # 같은 인라인 주소를 쓴 item들이 한 패키지로 묶이도록 dedupe
            key = (inline.get("postal_code", ""), inline.get("address_line", ""))
            addr_id = inline_ids.get(key, "")
            if not addr_id:
                addr_id = f"ADDR-{uuid.uuid4().hex[:6].upper()}"
                inline_ids[key] = addr_id
                used.setdefault(addr_id, cast(Address, {**inline, "address_id": addr_id}))
        else:
            addr_id = default_id
            if default_id in book:
                used.setdefault(default_id, book[default_id])

        address_ids.append(addr_id)

    return address_ids, list(used.values())


def order_request_agent(state: GraphState) -> GraphState:
    """확정된 주문내역으로 item_list 생성."""
    profile = state["user_profile"]
    confirmed_items = state.get("confirmed_order_items", [])

    now = datetime.now(timezone.utc).isoformat()
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    trace_id = uuid.uuid4().hex

    address_ids, delivery_addresses = _resolve_item_addresses(
        profile["delivery_addresses"], confirmed_items
    )

    item_list: list[Item] = []
    for idx, raw in enumerate(confirmed_items):
        item_list.append(
            {
                "item_id": raw.get("item_id", f"ITEM-{idx + 1:03d}"),
                "item_status": "대기",
                "item_delay_reason": raw.get("item_delay_reason"),
                "package_ref": None,
                "delivery_address_id": address_ids[idx],
                "location": raw.get("location"),
                "customer_facing_status": "주문접수",
            }
        )

    payment_status = state.get("payment_status_hint", "대기")

    order: OrderState = {
        "order_id": order_id,
        "order_created_at": now,
        "delivery_addresses": delivery_addresses,
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

    print(
        f"[주문요청agent] order_id={order_id}, items={len(item_list)}, "
        f"배송지={[addr['address_id'] for addr in delivery_addresses]}"
    )
    return {"order": order}
