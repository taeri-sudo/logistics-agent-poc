# CLAUDE.md

온톨로지 기반 물류 멀티에이전트 POC (LangGraph). 학습/포트폴리오용 최소 구현이며,
엔드포인트로 사람뿐 아니라 센서/로봇(액추에이터)까지 포함하는 것을 지향한다.
Agent-to-Agent, Agent-to-Sensor/Actuator 통신이 사람 endpoint보다 우선순위가 높다.

## 작업 전 필수

**코드를 수정하기 전에 [DESIGN.md](DESIGN.md)를 반드시 읽을 것.**
이 프로젝트는 "무엇을 만들었나"보다 **"왜 그렇게 정했나"와 "무엇을 폐기했나"**가 핵심이다.
DESIGN.md에는 노드 목록, State 스키마(현재 v12), 단계별 실행 결과, 그리고
**제거/통합된 것들과 그 이유**가 기록되어 있다. 아래는 그 요약일 뿐이므로,
설계 판단이 필요한 순간에는 항상 원문을 확인한다.

State 필드나 노드를 추가·변경했다면 **DESIGN.md도 같이 갱신**한다 (스키마 표 + 버전 번호 + 실행 결과 요약).

## State 설계 원칙 (6가지)

1. **원본은 사건이 실제로 발생한 계층에만 둔다.** Item / Package / Order 중 어디서 일어난 사건인지로 소속을 결정한다.
   재고부족·검수불량 → Item / 교통지연·자연재해 → Package / 여러 item·package를 아우르는 요약 → Order(**항상 파생값**).
2. **순차 단계(enum)와 교차 조건(bool/list)은 분리한다.** 동시에 하나만 가능한 진행 단계는 enum,
   다른 값과 동시에 존재 가능한 것(지연 여부 등)은 독립 필드.
3. **현재값과 과거 스냅샷은 "판단"과 "기록"으로 역할을 분리한다.**
   판단에 쓰는 현재 설정값과, 증거로 남기는 그 시점 스냅샷은 다른 필드다.
   스냅샷은 문의 대응/감사/역추적이 필요한 곳에만 만든다 (전부 만들지 않음).
4. **판단(추론)이 필요한 노드만 "Agent"라 부른다.** 단순 조회·카운트·이벤트 반영은 Agent가 아닌 일반 함수 노드다.
5. **Order-Package는 1:N 관계다 (N:M 아님).** 한 주문의 item들이 배송지별로 여러 Package에 나뉠 수 있지만,
   여러 주문을 한 Package로 합포장하는 시나리오는 없다. 실제 연결의 최소 단위는 Item (`item.package_ref`).
6. **완전동기(Join으로 전부 대기) 대신 비동기 부분배송이 기본이다.**
   각 Package/Item이 준비되는 대로 독립 진행하며, "부분배송중"은 문제 상황이 아니라 정책상 정상 상태다.

### 파생 규칙
- 다른 필드에서 계산 가능한 값은 필드로 만들지 않는다.
  (예: 지연 여부 = `delay_categories`가 비었는지 / 패키지 대기 여부 = `tracking_number is None`)
- Order 파생값(`internal_order_status`, `customer_facing_status`)의 최종 소유자는 **추적agent(4단계)**다.
  그 전까지는 각 노드가 잠정 세팅하되 `TODO(4단계)` 주석을 남긴다.

## 노드 역할 구분 기준

| 기준 | Agent | 일반 함수 노드 |
|---|---|---|
| 판단/추론이 필요한가 | O | X |
| 예 | 주문검증(조건분기), Supervisor(LLM), 패키지조립(조건카운트) | UserProfile 조회, 단순 이벤트 반영 |

분류 체계: `진입 / 관문 / 판단 / 반복 / 집계 / 액션 / 통합 / 부가` — 새 노드는 이 중 하나에 속해야 한다.

**새 노드를 만들기 전에 "이게 기존 노드에 흡수될 수 있는가"를 먼저 묻는다.**
이 프로젝트는 노드를 늘리기보다 흡수·통합하는 쪽으로 여러 번 결정해 왔다
(Join노드 → 패키지조립agent의 카운트 로직 / 출고·배송출발agent → 추적agent / 송장번호agent → 봉인 시점).
DESIGN.md의 "제거/통합된 것들" 목록이 그 판단의 선례다.

## 코드 관례

- 노드 시그니처는 `(state: GraphState) -> GraphState`, **부분 업데이트 dict만 반환**한다 (전체 state 아님).
- 중첩 갱신은 제자리 변경 대신 **immutable spread**를 `cast`로 감싼다:
  `order = cast(OrderState, {**order, "item_list": item_list})`.
  `{**td, ...}`는 타입체커가 `dict[str, Unknown]`으로 추론해 TypedDict에 대입되지 않으므로 cast가 필요하다.
  **cast는 스프레드에만 쓴다** — 키 오타를 잡아주지 못하니, 키/값을 새로 쓰는 자리(`_new_package` 등)에는 쓰지 말 것.
- 노드 함수명·그래프 노드명은 snake_case 영어, **docstring·print·enum 값은 한국어**.
- 로깅은 `logging` 없이 `print()`. 형식은 `[노드명] key=value`, 내부 루프는 두 칸 들여쓰고 서브태그(`  [Sensor]`, `  [봉인]`).
- ID는 `f"PKG-{uuid.uuid4().hex[:8].upper()}"` 꼴, 타임스탬프는 `datetime.now(timezone.utc).isoformat()`.
- TypedDict를 읽기만 하는 파라미터는 `dict`가 아니라 `Mapping[str, object]`로 받는다.
  **TypedDict는 `dict[...]`에 대입되지 않는다** (임의 키 추가/삭제가 구조를 깨뜨리므로 읽기 전용 매핑에만 대입 가능).
  키 누락 가능성을 검사하는 함수라면 특히 `Address` 같은 `total=True` 타입으로 좁히지 말 것 —
  타입이 "키가 다 있다"고 단언해버려 검사가 자기모순이 되고, 동적 키 조회(`.get(변수)`)도 막힌다.
  (선례: [validation.py](logistics_agent/nodes/validation.py)의 `_is_valid_address`)
- 새 노드는 `logistics_agent/nodes/`에 추가하고 `nodes/__init__.py`의 `__all__`에 **파이프라인 순서로** 등록한다.
- 타입체커 설정은 [pyrightconfig.json](pyrightconfig.json). `reportTypedDictNotRequiredAccess`만 끈 이유는
  `GraphState`가 `total=False`(부분 업데이트 반환)라 `state["order"]` 접근이 전부 경고로 잡히는데,
  `order`를 Required로 바꾸면 `return {"validation_passed": ...}` 같은 부분 반환이 깨지기 때문이다.
  **이 규칙 외에 다른 규칙을 끄지 말 것** — 나머지 경고는 실제 문제일 가능성이 높다.

## 실행

```powershell
venv\Scripts\python.exe main.py
```

테스트 프레임워크는 없다. 검증은 `main.py`의 시나리오를 실행해 출력으로 확인하며,
새 기능을 넣으면 그 분기를 실제로 타는 시나리오를 추가한다
(예: 대기 브랜치를 보려면 `item_delay_reason`을 넣어 피킹이 스킵되게 만들어야 한다).

배송중게이트는 Supervisor의 `predict_delay_escalation`(Google Gemini 실제 호출)을 탄다.
`.env`의 `GOOGLE_API_KEY`가 없으면 실패하고 `escalate_now=False`로 폴백하므로 데모 자체는
API 키 없이도 끝까지 실행된다 — 폴백이 아니라 실제 예측 결과를 보려면 키가 필요하다.
이 호출만은 실제 네트워크에 나가는 유일한 지점이라 그 시나리오(main.py 10번)만 실행마다
결과가 달라질 수 있다(비결정론).
