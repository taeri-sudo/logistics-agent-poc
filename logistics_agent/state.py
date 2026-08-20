"""State 스키마 v15 — LangGraph GraphState 정의."""

from __future__ import annotations

from typing import TypedDict

from logistics_agent.enums import (
    CancelStatus,
    CustomerFacingStatus,
    FulfillmentPreference,
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


class PendingDecision(TypedDict):
    """Item 도메인(피킹지연게이트) Stage1 판정 대기 — 이 POC 패스에서는 판정이 같은 tick
    안에서 즉시 자동 해소되므로 실제로 non-None으로 관측되는 경우가 없다. 진짜 사람이 개입하는
    별도 진입점(관리자 UI 등)이 생기면 그때부터 이 필드가 tick을 넘어 열린 채로 남게 된다."""

    decision_type: str  # 예: "품목_회복가능성_판단"
    reasoning: str
    requested_at: str


class ResolvedDecision(TypedDict):
    decision_type: str
    outcome: str  # 예: "회복불가_품목취소" / "회복가능_부분수령적용" / "회복가능_계속대기적용"
    decided_at: str
    reasoning: str


class Item(TypedDict):
    item_id: str
    item_status: ItemStatus
    item_delay_reason: ItemDelayReason | None
    package_ref: str | None
    delivery_address_id: str  # Order.delivery_addresses 중 하나를 참조
    location: Location | None
    customer_facing_status: CustomerFacingStatus
    # 아래 3개는 v13 신설 — 피킹지연게이트(지연체크게이트)의 self-loop 판단용.
    # PackageState의 동명 필드와 대칭 (같은 self-loop 패턴을 Item 층위에도 재사용)
    policy_version_applied: str | None
    last_checked_at: str | None
    retry_count: int
    # v16: escalated(bool)를 대체 — Stage1 판정의 "현재 열린 결정"과 "해소된 기록"을 분리(원칙3)
    pending_decision: PendingDecision | None
    decision_log: list[ResolvedDecision]


class SourceItemRef(TypedDict):
    order_id: str
    item_id: str


class NotificationEntry(TypedDict):
    stage: str
    sent_at: str
    enabled_at_time: bool


class CompensationRecord(TypedDict):
    """v16: PackageState.escalated(bool)를 대체 — 판단이 즉시 액션으로 끝나 persist할 대기
    상태가 없어졌다(조립대기게이트/배송중게이트 공통). POC 범위상 action은 항상 "환불"."""

    action: str  # POC 범위: "환불"만 (재발송은 확장 지점)
    executed_at: str


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
    compensation: CompensationRecord | None
    escalation_reasoning: str | None  # 이 보상조치/알림을 취한 근거 (설명가능성, v16에서 의미 재해석)
    join_waiting_since: str | None
    notification_log: list[NotificationEntry]


class OrderState(TypedDict):
    order_id: str
    order_created_at: str
    delivery_addresses: list[Address]  # 이 주문의 item들이 실제 참조하는 배송지만
    payment_status: PaymentStatus
    # v16: split_delivery_preference(사전 확정 지시)를 대체 — 문제가 실제 발생했을 때만
    # 참조되는 "미래 대비 선호도"로 재설계 (원본은 DESIGN.md 참고)
    fulfillment_preference_on_delay: FulfillmentPreference | None
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
    fulfillment_preference_on_delay_hint: FulfillmentPreference  # 주문 시점 사전등록 (데모용, 기본 None)
    order_created_at_hint: str  # 주문 생성 시각을 과거로 강제 지정 (데모용 — 없으면 실제 현재 시각)

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
