from typing import Literal

PaymentStatus = Literal["대기", "완료", "실패"]
CancelStatus = Literal["요청됨", "처리중", "완료", "거부됨"]
InternalOrderStatus = Literal[
    "접수",
    "검증실패",
    "창고처리중",
    "조립중",
    "출고준비",
    "배송중",
    "완료",
    "부분완료",
    "전체무산",
]
ItemStatus = Literal[
    "대기",
    "피킹중",
    "피킹완료",
    "포장완료",
    "출고됨",
    "배송중",
    "배송지연",
    "배송완료",
    "취소됨",
]
ItemDelayReason = Literal["재고부족", "검수불량", "파손", "통관지연"]
FulfillmentPreference = Literal["부분수령희망", "합배송희망"]
CustomerFacingStatus = Literal[
    "주문접수",
    "준비중",
    "배송중",
    "배송완료",
    "지연",
    "상품준비불가",
]
