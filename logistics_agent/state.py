"""State 스키마 v13 — LangGraph GraphState 정의."""

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
    address_id: str
    recipient: str
    phone: str
    postal_code: str
    address_line: str


class PaymentMethod(TypedDict):
    type: str  # card / bank_transfer 등
    last4: str | None  # 카드가 아니면 None


class Location(TypedDict):
    """창고 내 물리 위치. 포장 전까지만 유효."""

    zone: str
    shelf: str
    bin: str


class GpsPoint(TypedDict):
    """출고 이후 Package의 현재 위치."""

    lat: float
    lng: float
    updated_at: str


class UserProfile(TypedDict):
    user_id: str
    delivery_addresses: list[Address]  # 주소록. [0]이 기본배송지
    payment_method: PaymentMethod
    notification_enabled: bool


class Item(TypedDict):
    item_id: str
    item_status: ItemStatus
    item_delay_reason: ItemDelayReason | None
    package_ref: str | None
    delivery_address_id: str  # Order.delivery_addresses 중 하나를 참조
    location: Location | None
    customer_facing_status: CustomerFacingStatus
    # 아래 4개는 v13 신설 — 출고전게이트(지연체크게이트)의 self-loop 판단용.
    # PackageState의 동명 필드와 대칭 (같은 self-loop 패턴을 Item 층위에도 재사용)
    policy_version_applied: str | None
    last_checked_at: str | None
    retry_count: int
    escalated: bool


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
    delivery_address_id: str  # 이 패키지의 배송지 (미봉인 패키지 재사용 시 매칭 키)
    required_item_count: int
    arrived_item_count: int
    current_gps: GpsPoint | None
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
    delivery_addresses: list[Address]  # 이 주문의 item들이 실제 참조하는 배송지만
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

    # Package State (패키지조립agent가 생성/갱신)
    packages: list[PackageState]

    # 주문검증agent 분기용
    validation_passed: bool
    validation_errors: list[str]

    # Supervisor 판단 결과 (더미)
    supervisor_decision: str | None
    supervisor_notes: str | None
