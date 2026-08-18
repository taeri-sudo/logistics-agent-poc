"""판단 노드: Supervisor — 온톨로지/규칙으로 못 정하는 예외 판단을 모아두는 자리.

decision_type이 여러 개 있을 수 있다는 전제로 나뉘어 있다:
- proceed_to_warehouse: 창고처리 진입 여부. 예외가 없으면 규칙만으로 결정되는 판단이라
  아직 LLM이 필요 없음(더미 유지) — 그래프 노드(`supervisor`) 자체가 이 decision_type 전용.
- predict_delay_escalation: 배송 지연이 정상 재시도로 해결될지, 지금 바로 사람에게
  올려야 할지 예측. 신호가 여러 개(지연 카테고리/재시도 횟수/재고부족 품목 수/경과 시간)라
  규칙표로 못 박기보다 LLM 판단이 맞다고 봐서 Google Gemini를 실제로 호출한다.
  별도 그래프 노드로 만들지 않았다 — 배송중게이트가 이미 "판단+반복" 노드라 그 판단을
  함수 호출로 흡수하는 쪽이 노드를 늘리는 것보다 낫다고 판단(CLAUDE.md 흡수 우선 원칙).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from logistics_agent.state import GraphState, OrderState

load_dotenv()

# 모델명은 Gemini 라인업이 바뀌어도 코드 수정 없이 .env에서 덮어쓸 수 있게 env var로 뺌.
# .env에 키만 있고 값이 빈 문자열인 경우도 "설정 안 함"으로 취급 (or로 처리).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.6-flash"


def supervisor(state: GraphState) -> GraphState:
    """decision_type=proceed_to_warehouse. 예외가 없으면 규칙만으로 결정되는 판단이라 더미 유지."""
    order = state["order"]
    item_count = len(order["item_list"])

    decision = "proceed_to_warehouse"
    notes = f"예외 없음. {item_count}개 품목 창고 처리 진행."

    print(f"[Supervisor] decision={decision}, notes={notes}")

    order = cast(OrderState, {**order, "internal_order_status": "창고처리중"})
    return {
        "supervisor_decision": decision,
        "supervisor_notes": notes,
        "order": order,
    }


@dataclass(frozen=True)
class DelayRiskSignals:
    """predict_delay_escalation에 넣는 입력 신호 (payload). 로깅용 package_id 하나만 예외."""

    package_id: str
    delay_categories: list[str]
    retry_count: int
    low_stock_item_count: int
    elapsed_hours_since_order: float


class SupervisorPrediction(BaseModel):
    """predict_delay_escalation의 구조화된 출력 — 판단 + 근거(설명가능성)."""

    escalate_now: bool = Field(description="정상 재시도로 해결되기 어려워 지금 바로 사람에게 올려야 하면 true")
    reasoning: str = Field(description="판단 근거를 한국어 1~2문장으로")


_PREDICT_PROMPT = """당신은 물류센터의 배송 지연 대응 담당자입니다.
아래 신호를 보고, 이 패키지를 지금 바로 사람에게 에스컬레이션해야 할지,
아니면 자동 재시도를 몇 번 더 지켜봐도 되는지 판단하세요.

- 현재 지연 사유: {delay_categories}
- 지금까지 자동 재시도 횟수: {retry_count}
- 같은 주문에서 아직 재고부족으로 묶여있는 품목 수: {low_stock_item_count}
- 주문 생성 이후 경과 시간: {elapsed_hours_since_order:.1f}시간

재시도 횟수 자체는 적더라도, 다른 신호를 종합했을 때 상황이 계속 악화될 것으로 예상되면
지금 바로 에스컬레이션(escalate_now=true)하세요. 판단 근거를 reasoning에 한국어로 남기세요."""


@lru_cache(maxsize=1)
def _delay_prediction_llm():
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0).with_structured_output(
        SupervisorPrediction
    )


def predict_delay_escalation(signals: DelayRiskSignals) -> SupervisorPrediction:
    """decision_type=predict_delay_escalation. Google Gemini 실제 호출.

    실패(API 키 누락/네트워크 오류 등 외부 경계) 시에는 escalate_now=False로 보수적으로
    폴백한다 — 기존 retry_count>MAX_GATE_RETRIES 임계치가 안전망으로 여전히 살아있으므로,
    LLM 호출이 실패해도 배송중게이트 자체가 멈추거나 영원히 미해결로 남지 않는다.
    """
    prompt = _PREDICT_PROMPT.format(
        delay_categories=", ".join(signals.delay_categories) or "없음",
        retry_count=signals.retry_count,
        low_stock_item_count=signals.low_stock_item_count,
        elapsed_hours_since_order=signals.elapsed_hours_since_order,
    )
    try:
        prediction = cast(SupervisorPrediction, _delay_prediction_llm().invoke(prompt))
    except Exception as exc:  # 외부 API 경계 — 여기서만 넓게 잡는다
        print(f"  [Supervisor] predict_delay_escalation 호출 실패: {exc}")
        return SupervisorPrediction(
            escalate_now=False,
            reasoning=f"LLM 호출 실패({exc.__class__.__name__}) — 기존 재시도 임계치로 폴백",
        )

    print(
        f"  [Supervisor] predict_delay_escalation package_id={signals.package_id} "
        f"escalate_now={prediction.escalate_now} reasoning={prediction.reasoning}"
    )
    return prediction
