"""State 스키마 v10 — LangGraph GraphState 정의."""

from __future__ import annotations

from typing import TypedDict

from logistics_agent.enums import (
    CancelStatus,
    CustomerFacingStatus,
    InternalOrderStatus,
    ItemDelayReason,
    ItemStatus,
    PaymentStatus,
)


class Address(TypedDict):
    recipient: str
    phone: str
    postal_code: str
    address_line: str


class PaymentMethod(TypedDict):
    type: str
    last4: str | None


class UserProfile(TypedDict):
    user_id: str
    delivery_address: Address
    payment_method: PaymentMethod
    notification_enabled: bool


class Item(TypedDict):
    item_id: str
    item_status: ItemStatus
    item_delay_reason: ItemDelayReason | None
    package_ref: str | None
    location: dict | None
    customer_facing_status: CustomerFacingStatus


class SourceItemRef(TypedDict):
    order_id: str
    item_id: str


class NotificationEntry(TypedDict):
    stage: str
    sent_at: str
    enabled_at_time: bool


class PackageState(TypedDict):
    package_id: str
    source_items: list[SourceItemRef]
    required_item_count: int
    arrived_item_count: int
    current_gps: dict | None
    tracking_number: str | None
    delay_categories: list[str]
    policy_version_applied: str | None
    last_checked_at: str
    retry_count: int
    escalated: bool
    join_waiting_since: str | None
    notification_log: list[NotificationEntry]


class OrderState(TypedDict):
    order_id: str
    order_created_at: str
    delivery_address: Address
    payment_status: PaymentStatus
    split_delivery_preference: bool
    cancel_requested_at: str | None
    cancel_status: CancelStatus | None
    internal_order_status: InternalOrderStatus
    item_list: list[Item]
    current_item_index: int
    notification_enabled: bool
    trace_id: str


class GraphState(TypedDict, total=False):
    """LangGraph 런타임 상태.

    total=False: 노드별 부분 업데이트 허용.
    """

    # 진입 입력
    user_id: str
    confirmed_order_items: list[dict]
    payment_status_hint: PaymentStatus  # 주문 생성 시 payment_status (데모/외부결제 연동용)

    # UserProfile (조회 전용 캡슐)
    user_profile: UserProfile

    # Order State
    order: OrderState

    # 주문검증agent 분기용
    validation_passed: bool
    validation_errors: list[str]

    # Supervisor 판단 결과 (더미)
    supervisor_decision: str | None
    supervisor_notes: str | None
