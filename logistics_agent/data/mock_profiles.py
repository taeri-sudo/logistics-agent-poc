"""세션/DB 대체용 더미 UserProfile 저장소."""

from logistics_agent.state import UserProfile

MOCK_USER_PROFILES: dict[str, UserProfile] = {
    "user-001": {
        "user_id": "user-001",
        "delivery_addresses": [
            {
                "address_id": "ADDR-HOME",
                "recipient": "홍길동",
                "phone": "010-1234-5678",
                "postal_code": "06234",
                "address_line": "서울특별시 강남구 테헤란로 123",
            },
            {
                "address_id": "ADDR-OFFICE",
                "recipient": "홍길동",
                "phone": "010-1234-5678",
                "postal_code": "07326",
                "address_line": "서울특별시 영등포구 여의대로 108 9층",
            },
            {
                # 3단계 배송중게이트 자연재해 데모 전용 (package_id는 uuid라 고정 못하므로 주소로 대체)
                "address_id": "ADDR-STORM",
                "recipient": "홍길동",
                "phone": "010-1234-5678",
                "postal_code": "63127",
                "address_line": "제주특별자치도 제주시 첨단로 242",
            },
        ],
        "payment_method": {"type": "card", "last4": "4242"},
        "notification_enabled": True,
    },
    "user-002": {
        "user_id": "user-002",
        "delivery_addresses": [
            {
                "address_id": "ADDR-HOME",
                "recipient": "김영희",
                "phone": "010-9876-5432",
                "postal_code": "48058",
                "address_line": "부산광역시 해운대구 센텀로 456",
            },
        ],
        "payment_method": {"type": "bank_transfer", "last4": None},
        "notification_enabled": False,
    },
}
