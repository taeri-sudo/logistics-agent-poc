"""세션/DB 대체용 더미 UserProfile 저장소."""

from logistics_agent.state import UserProfile

MOCK_USER_PROFILES: dict[str, UserProfile] = {
    "user-001": {
        "user_id": "user-001",
        "delivery_address": {
            "recipient": "홍길동",
            "phone": "010-1234-5678",
            "postal_code": "06234",
            "address_line": "서울특별시 강남구 테헤란로 123",
        },
        "payment_method": {"type": "card", "last4": "4242"},
        "notification_enabled": True,
    },
    "user-002": {
        "user_id": "user-002",
        "delivery_address": {
            "recipient": "김영희",
            "phone": "010-9876-5432",
            "postal_code": "48058",
            "address_line": "부산광역시 해운대구 센텀로 456",
        },
        "payment_method": {"type": "bank_transfer", "last4": None},
        "notification_enabled": False,
    },
}
