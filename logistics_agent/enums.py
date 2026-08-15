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
]
ItemDelayReason = Literal["재고부족", "검수불량", "파손"]
CustomerFacingStatus = Literal[
    "주문접수",
    "준비중",
    "배송중",
    "배송완료",
    "지연",
]
