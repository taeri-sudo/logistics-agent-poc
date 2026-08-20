# 물류 멀티에이전트 POC 설계 메모

## 목차

- [목적](#purpose)
- [진행 상황](#progress)
- [핵심 설계 원칙](#principles)
- [핵심 개념](#concepts)
  - [판단(decision) vs 개입(intervention) vs escalated](#concept-decision-intervention)
  - [지연 사유의 세 계층](#concept-delay-layers)
  - ["재고부족" 개념의 세 가지 층위](#concept-stockout-layers)
- [사람 개입 워크플로우 — 도메인 분리 기반 재설계](#human-intervention-redesign)
- [노드 목록 (최종)](#node-list)
  - [제거/통합된 것들](#removed-integrated)
- [State 스키마 (v15)](#state-schema)
  - [Address](#schema-address)
  - [Order State](#schema-order)
  - [Item](#schema-item)
  - [Package State](#schema-package)
  - [Location](#schema-location)
  - [GpsPoint](#schema-gpspoint)
  - [UserProfile](#schema-userprofile)
  - [PaymentMethod](#schema-paymentmethod)
- [아직 결정 안 된 것 / 다음에 확인할 것](#open-questions)
- [미구현/죽은 필드 종합](#dead-fields)
- [확장 지점](#extension-points)
- [실무 전환 시 고려사항](#production-notes)

<a id="purpose"></a>
## 목적
온톨로지 기반 멀티에이전트 설계 포트폴리오를 위한 학습용 최소 구현.
이 코드 자체가 최종 포트폴리오는 아님 — 핵심 패턴(State 설계, 조건분기, self-loop)을 직접 구현해보고 이해한 뒤, 타 사례를 참고/엮어서 포트폴리오화할 예정.

엔드포인트를 사람뿐 아니라 센서/로봇(액추에이터)까지 포함하는 것을 지향.
Agent-to-Agent, Agent-to-Sensor/Actuator 통신이 사람 endpoint보다 우선순위 높음.

이 문서는 "지금 무엇이 맞다고 결정됐는가"만 담는 참조 문서다. 단계별 실행 결과, 시나리오
검증 로그, gap 발견 과정, 폐기된 가설 등 "어떻게 그 결론에 도달했는가"는 [JOURNAL.md](JOURNAL.md)에 있다.

---

<a id="progress"></a>
## 진행 상황

- [x] 1단계: UserProfile조회 → 주문요청agent → 주문검증agent(조건분기) → Supervisor(더미) → 창고처리agent(placeholder)
- [x] 2단계: 패키지조립agent (배송지 정규화 v11 + 중첩구조 타입 승격 v12)
- [x] 3단계: 지연체크게이트 3종 (피킹지연/조립대기/배송중, self-loop 패턴, Item에 retry 필드 추가 v13)
- [x] 4단계: 추적agent (범용 이벤트 수신 + 파생값 재계산) — 선행 조건으로 포장agent도 함께 구현
- [x] 4단계 후속: split_delivery_preference를 패키지조립agent 그룹핑에 실제 반영
- [x] 4단계 후속: Supervisor predict_delay_escalation (Google Gemini 실제 호출) 배송중게이트에 통합
- [x] 4단계 후속: `_PACKAGE_DELAY_SIGNAL` 키를 `delivery_address_id`→`item_id`로 교체
- [x] 4단계 후속: 출고전게이트 → **피킹지연게이트**로 개명
- [x] 5단계(코드 리뷰): 사람 개입 워크플로우 구체화 설계(도메인 분리 기반, v16 스키마 초안) —
  아래 "사람 개입 워크플로우" 절 참고. **설계만 완료, 코드 미반영** — 그래프 재진입성 포함
  실제 구현은 다음 세션 계획

상세 실행 기록·시나리오 검증·gap 발견 과정은 전부 [JOURNAL.md](JOURNAL.md) 참고.

---

<a id="principles"></a>
## 핵심 설계 원칙 (State 설계 시 계속 지켜온 기준)

1. **원본은 사건이 실제로 발생한 계층에만 둔다.** (Item / Package / Order 중 어디서 일어난 사건인지로 소속 결정)
   - 재고부족·검수불량 등 개별 상품 사정 → Item
   - 교통지연·자연재해 등 묶음(트럭/박스) 사정 → Package
   - 여러 item/package를 아우르는 요약만 → Order (항상 파생값)

2. **순차 단계(enum)와 교차 조건(bool/list)은 분리한다.**
   - 동시에 하나의 값만 가능한 것(진행 단계) → enum
   - 다른 값들과 동시에 존재 가능한 것(지연 여부 등) → 독립 필드

3. **현재값과 과거 스냅샷은 "판단"과 "기록"으로 역할을 분리한다.**
   - notification_enabled(현재 설정, 판단에 사용) vs notification_log의 enabled_at_time(그 시점 스냅샷, 기록용 증거)
   - 스냅샷은 "문의 대응/감사/역추적 필요성이 있는 곳"에만 추가 (전부 다 만들지 않음)

4. **판단(추론)이 필요한 노드만 "Agent"라 부른다.** 단순 조회/카운트/이벤트 반영은 Agent가 아닌 일반 함수 노드.
   - 예: Join노드는 별도 존재가 아니라 패키지조립agent 내부의 카운트 로직으로 흡수
   - 예: 출고/배송출발은 "행동"이 아니라 외부 신호를 받는 이벤트 반영이라 추적agent로 흡수

5. **Order-Package는 1:N 관계 (N:M 아님).** 한 주문의 item들이 배송지별로 여러 Package에 나뉘어 쪼개질 수 있음
   (실 커머스에 여러 사용자의 주문을 한 패키지로 합치는 사례는 없음 — 합포장은 존재하지 않는 시나리오였음).
   실제 연결의 최소 단위는 Item (item.package_ref로 연결).

6. **완전동기(Join으로 전부 대기) 대신 비동기 부분배송을 기본으로 한다.**
   각 Package/Item이 독립적으로 준비되는 대로 진행. "부분배송중"은 문제 상황이 아니라 정책상 정상 상태.

---

<a id="concepts"></a>
## 핵심 개념

<a id="concept-decision-intervention"></a>
### 판단(decision) vs 개입(intervention) vs escalated
- **`escalated`** — State 필드명. "재시도 한도를 넘었다/조기 신호가 있었다"는 **현재 상태**를
  기록하는 값일 뿐, 그 자체로는 행위가 아니다.
- **판단(decision)** — Supervisor가 상황을 보고 어떻게 대응할지 **정하는 것**
  (`decide_warehouse_entry`/`predict_delay_escalation`).
- **개입(intervention)** — 사람이 **이미 진행 중인 자동 판단/처리에 끼어들어** 방향을 바꾸거나
  멈추는 것. 판단은 시스템이 스스로 내리는 것이고, 개입은 외부(사람)가 그 결과에 손을 대는 것.

대응 경로도 이 구분을 따라 둘로 나뉜다:
- **경로A — Supervisor 판단(자동)**: `predict_delay_escalation`이 신호를 보고 `escalate_now`를
  정하고, 결과를 `escalated`/`escalation_reasoning`에 기록한다. 그래프 실행 안에서 동기적·
  비차단으로 일어난다 — `escalated=True`가 돼도 배송은 계속 진행된다.
- **경로B — 사람 개입**: 경로A가 이미 만들어놓은 판단 결과를 사람이 **나중에** 검토해서 그
  판단을 유지/변경/확정하는 것. "처음부터 사람이 판단한다"가 아니라 **"이미 내려진 판단에
  개입한다"**는 구조.

**지금 구현된 건 경로A뿐이다. 경로B는 완전히 미구현이다.** `escalated=True`가 세팅된 뒤 사람이
그걸 어떻게 보고 어떻게 처리를 확정하는지는 시스템 어디에도 없다. 또한 Supervisor 판단 자체가
실패하는 경우(LLM 호출 실패)와 정상적으로 "지켜봐도 된다"고 판단한 경우가 지금 코드에서
구분되지 않는다 — 둘 다 `escalate_now=False`로 같은 모양의 결과를 반환한다. 판단 실패는
그 자체로 경로B 트리거가 되어야 하는데 지금은 게이트를 그냥 통과시킨다(아래 "아직 결정 안
된 것" 참고).

**사람 개입 워크플로우가 별도 진입점이어야 하는 구조적 이유**: 이 파이프라인은 `app.invoke()`
한 번으로 동기 실행된다 — 그래프 노드는 실행 도중 "사람이 승인할 때까지 멈춰서 기다리기"를 할
수 없다. 판단(경로A)은 자동화 가능한 로직이라 그래프 실행 흐름 안에 자연스럽게 들어가지만,
개입(경로B)은 그래프 노드로 표현될 수 없다 — 사람이 검토하는 시점은 그래프 실행 시점과 무관하게
일어난다. `escalated=True`로 마킹된 상태가 영속화되고, 그래프 바깥의 **완전히 별도의
진입점**(관리자 UI, CS 티켓 시스템, 별도 API 등)이 그 상태를 읽어 사람의 결정을 다시 State에
반영하는 구조여야 한다.

<a id="concept-delay-layers"></a>
### 지연 사유의 세 계층
`delay_gates.py`가 다루는 "지연 사유"는 대응 방식이 완전히 다른 세 계층으로 나뉜다:

1. **결정화된 규칙** (재고부족/검수불량 등) — 해소 시점이 경험적으로 고정 가능한 예외.
   고정 딕셔너리(`_ITEM_RESOLVE_AT_RETRY`)로 처리. Supervisor(판단) 불필요.
2. **예측 영역** (교통지연 등) — 정상적인 지연이지만 해소 시점이 불확실해서 규칙표로 못
   박기보다 예측이 맞는 영역. `predict_delay_escalation`이 담당.
3. **정상 흐름 자체가 깨지는 재난/예외 상황** (전쟁, 대규모 재해 등) — 이런 사유는 애초에 전부
   나열할 수 없다. "등록 안 된 사유를 만나면 자동으로 사람 개입 경로(경로B — 지금은 미구현)로
   넘기는 fallback"이 필요하다는 뜻.

   **별도 decision_type 후보로 남겨둔다: `assess_disruption_severity`(가칭).**
   `predict_delay_escalation`(정상적인 지연이 언제 해소될지 예측)과 다르다 — 이건 **"정상
   흐름 자체가 지금도 유효한 전제인지"를 재판단**하는 것이다.

   지금 `_PACKAGE_DELAY_SIGNAL`의 `"자연재해"`는 계층3에 속하지만, fallback이 없어서 계층1처럼
   고정 딕셔너리에 미리 등록해두고 즉시 에스컬레이션시키는 방식으로 임시 처리돼 있다 — 데모가
   "어떤 재난이 일어날지" 미리 알고 스크립트를 짜기 때문에 통했을 뿐, 실제로 계층3에 맞는
   방식이라서가 아니다.

<a id="concept-stockout-layers"></a>
### "재고부족" 개념의 세 가지 층위
창고처리agent(warehouse.py)가 다루는 "재고부족"은 서로 다른 층위 세 개를 뭉뚱그려 가리킨다:

1. **결제 시점 재고부족** — 장바구니/결제 단계에서 이미 품절인 상품을 걸러내는 UI/API 검증.
   이 프로젝트는 "확정된 주문내역"(주문요청agent)부터 시작하므로 범위 밖.
2. **수량체크 오류로 인한 재고부족** (현재 워크플로우가 다루는 것) — 창고에서 실제로 피킹하려는
   순간 발견되는, 결정화된 규칙으로 처리 가능한 예외. Supervisor(판단) 불필요 —
   `item_delay_reason="재고부족"`이 있으면 창고처리agent는 피킹만 스킵하고, 해소/재시도/
   영구 에스컬레이션 판단은 피킹지연게이트가 고정 로직으로 전담한다. 창고처리agent가 이 예외를
   만나 Supervisor를 부르지 않는 것은 의도된 설계다.
3. **판매량 예측 기반 재고 확보** — "얼마나 미리 발주/보충해둘지"를 예측하는 진짜 판단(예측)
   영역. 개별 주문의 창고처리 노드가 다룰 문제가 아니라, 이 주문 워크플로우 전체와는 독립적으로
   돌아가는 **완전히 별도의 상위 시스템**(재고관리, 배치성 수요예측)의 책임 — 범위 밖(아래
   "확장 지점" 참고).

세 층위를 하나의 "재고부족" 필드/노드로 뭉뚱그리지 않고 분리해서 본 것이 핵심 — 층위2에
Supervisor 판단을 억지로 끼워 넣거나, 층위3(예측)을 이 워크플로우 안에 노드로 만들려는
시도는 둘 다 잘못된 방향이었을 것.

---

<a id="human-intervention-redesign"></a>
## 사람 개입 워크플로우 — 도메인 분리 기반 재설계 (설계 초안, 코드 미반영)

5단계(코드 리뷰) 중 "escalated가 기업담당자/구매자 상황을 구분 못 한다"는 것과
"split_delivery_preference가 사전 선택으로 잘못 설계됐다(실제로는 문제 발생 시점의
사후 결정이어야 함)"는 두 이슈가 발견되어, 위 "핵심 개념"을 이어 구체적인 설계로 발전시켰다.
**아직 코드에는 반영하지 않았다** — 그래프 재진입성(패키지조립agent 등)을 포함한 실제 구현은
별도 세션의 계획으로 진행한다.

**두 도메인 구분.** `mock_carrier_signal`이 "실제로는 택배사 웹훅이 들어올 자리"라는 기존
경계(JOURNAL.md 4단계 후속 참고)를 워크플로우 전체에 일관되게 적용한 결과다.
- **주문/재고/창고 영역** (피킹지연게이트~포장agent): 우리가 직접 운영. 판단에 필요한 정보
  (재고 실물 상태, 파손 여부)를 시스템이 갖지 못하고 운영자만 안다.
- **실제 운송 영역** (배송중게이트~추적agent): 실제로는 택배사가 담당, 우리는 위탁하는 입장.

**결론의 핵심 근거 (상세 논의는 [JOURNAL.md](JOURNAL.md) "5단계: 사람 개입 워크플로우 재설계 —
논의 과정" 참고)**: 1차 판단자를 가르는 기준은 계층(Item/Package)이 아니라 "누가 판단에 필요한
정보를 가졌는가"이며, 창고 실물 상태는 계층과 무관하게 항상 운영자만 안다. 구매자 실시간 개입은
두 도메인 모두에서 사라지지만 이유가 다르다 — Item 도메인은 사전 선호도 등록으로 왕복이
**불필요해지고**, Package 도메인은 봉인된 패키지가 품목을 차등 취급할 수 없어 애초에
**구조적으로 불가능**하다.

**Item 도메인 (피킹지연게이트) 재설계.**
- `OrderState.fulfillment_preference_on_delay: "부분수령희망"|"계속대기희망"|None` 신설.
  `split_delivery_preference`와 다른 개념 — 그건 "확정 지시"(사전에 포장 방식을 못박음)였지만
  이건 **"미래 대비 선호도"**(문제가 실제로 생겼을 때만 참조됨)다. 주문 시점에 사전등록.
- Stage1(운영자, 항상 최초, 경로B — 실제 사람. 창고 실물 상태는 시스템이 갖지 못한 정보라
  LLM으로 대체하지 않는다):
  - **회복불가**(예: 파손) → **품목 단위 취소**로 확정. 나머지 품목은 정상 진행(결과적으로
    부분수령과 동일한 효과). **주문 전체 취소가 아니다** — 원칙6과 가장 잘 맞는 스코프.
  - **회복가능**(예: 재고부족) → `fulfillment_preference_on_delay` 값을 참조해
    부분수령/계속대기를 자동 처리.
- 구매자에게 실시간으로 묻는 단계가 없다 — 선호도 사전등록으로 운영자 판단 이후 왕복이 불필요.

**Package 도메인 (배송중게이트) 재설계.**
- "운영자가 재라우팅을 판단한다"는 표현은 부정확하다 — 실제로는 택배사(외부 시스템)의 신호를
  받아 반응하는 성격이다.
- "부분수령" 선택지가 이 도메인엔 존재할 수 없다 — 봉인된 Package는 이미 고정된 품목 구성을
  갖고, `delay_categories`는 원칙1에 따라 Package 사건이지 개별 Item 사건이 아니다.
- **회복불가** → 보상조치(환불/재발송 — 범위 미정, 아래 "미정 항목" 참고). 구매자 선택 불필요.
- **회복가능** → `notification_enabled` 참조해 알림만(선택적).
- `predict_delay_escalation`의 `escalate_now`를 회복불가/회복가능 분류값으로 재해석한다 —
  함수 자체는 유지, 출력의 의미만 재정의. 자연재해 즉시분기(위 계층3)도 "회복불가로 분류되는
  카테고리 하나"로 흡수될 가능성이 높다(코드 변경 시 재검토).
- 이 도메인은 결과적으로 **사람 개입(경로B) 자체가 불필요해진다** — 전부 결정론적 액션으로
  귀결되기 때문. persist할 "대기 상태"가 없어진다는 뜻이기도 하다.

**customer_facing_status 신규 값 — "상품준비불가".** "지연"(자동재시도/운영자 검토 중, 미확정)과
구분되는 확정 취소 상태로 신설한다. 원인 불문 중립 라벨을 쓰는 근거는 JOURNAL.md 참고.

**v16 스키마 초안 (v15 대비 diff, 아직 코드 미반영).**

*OrderState*
| 필드 | 변경 |
|---|---|
| ~~split_delivery_preference: bool~~ | 제거 |
| `fulfillment_preference_on_delay: "부분수령희망"\|"계속대기희망"\|None` | 신설 |
| `internal_order_status` | **값 추가 필요** — "부분배송중"류. 품목 단위 취소로 "일부만 배송"이 실제로 발생 가능해져, all-or-nothing enum의 gap이 이제 실제로 걸린다 |
| `cancel_status`/`cancel_requested_at` | 변경 없음 — 주문 전체 취소 흐름 전용으로 유지, 품목 단위 취소는 별도 경로(아래 `decision_log`) |

*Item*
| 필드 | 변경 |
|---|---|
| ~~escalated: bool~~ | `pending_decision: PendingDecision \| None`로 대체. `target` 필드는 없음 — 이 도메인은 항상 운영자라 파생 불필요한 상수를 필드화하면 원칙2 위반 |
| (신설) | `decision_log: list[ResolvedDecision]` — 원칙3(판단/기록 분리): `pending_decision`은 현재 열린 결정, `decision_log`는 해소된 결정의 기록 |
| `item_status` | **값 추가 필요** — "취소됨" |
| `customer_facing_status` | **값 추가 필요** — "상품준비불가" |
| `item_delay_reason` | 필드 변경 없음, 동작만 명확화: 취소 확정 후에도 null로 안 되돌린다(취소 사유 기록으로 유지) |

```python
class PendingDecision(TypedDict):
    decision_type: str  # 예: "품목_회복가능성_판단"
    reasoning: str       # 왜 이 시점에 운영자가 봐야 하는지
    requested_at: str

class ResolvedDecision(TypedDict):
    decision_type: str
    outcome: str          # 예: "회복불가_품목취소" / "회복가능_부분수령적용" / "회복가능_계속대기적용"
    decided_at: str
    reasoning: str
```

*PackageState*
| 필드 | 변경 |
|---|---|
| ~~escalated: bool~~ | 제거 후보 — 판단이 즉시 액션(보상/알림)으로 끝나 persist할 대기 상태가 없어짐 |
| `escalation_reasoning` | 유지, 의미 재해석 — "사람이 봐야 함"의 근거가 아니라 "이 액션(보상/알림)을 취한" 근거 기록으로 |

**미정으로 남기는 항목 (다음 세션에서 이어갈 것).**
1. `InternalOrderStatus`의 "부분배송중"류 값 정확한 이름과 `derive_internal_order_status`의
   판정 규칙
2. Package 도메인 보상조치의 실행/기록 방식 — 환불만 할지 재발송도 포함할지(재발송은
   fulfillment 재진입이 필요해 훨씬 복잡함), 기록할 필드 형태
3. `_ITEM_RESOLVE_AT_RETRY["재고부족"]=2`가 `MAX_GATE_RETRIES=3` 이전에 항상 해소되는
   현재 데모 설정상, "회복가능" 분기(재고부족이 실제로 `pending_decision`까지 도달하는
   경우)는 지금 시나리오로는 구조상 도달 불가능하다. 실제로 시연하려면 새 데모 트리거가 필요.

---

<a id="node-list"></a>
## 노드 목록 (최종)

| 분류 | 노드명 | 성격 | 역할 |
|---|---|---|---|
| 진입 | UserProfile 조회 | 조회(비판단) | 로그인 세션에서 delivery_addresses(주소록), payment_method, notification_enabled 로드 |
| 진입 | 주문요청agent | 이벤트 | 확정된 주문내역(장바구니 아님)으로 item_list 생성 |
| 관문 | 주문검증agent | 조건분기 | payment_status, 배송지 검증 → 통과/실패 |
| 판단 | Supervisor | LLM 판단 | "Supervisor"는 그래프 노드/함수 하나의 이름이 아니라 decision_type들을 아우르는 개념(`supervisor.py`). **decide_warehouse_entry**(decision_type=proceed_to_warehouse, 그래프 노드 자체, 규칙만으로 결정돼 아직 더미) / **predict_delay_escalation**(Google Gemini 실제 호출, 배송중게이트가 함수로 직접 호출 — 별도 그래프 노드 아님, 판단+근거텍스트를 SupervisorPrediction으로 반환) |
| 반복 | 창고처리agent | 조회+액션 (내장 루프) | item_list 순회, Sensor(위치확인)→Action(피킹). 예외(item_delay_reason)는 피킹만 스킵하고 그대로 넘김 — 해소는 피킹지연게이트가 담당 |
| 집계 | 패키지조립agent | 조건카운트 | `package_ref`가 없는 item을 `delivery_address_id` 기준으로 묶음(`split_delivery_preference=true`면 같은 배송지도 item별로 분리). 같은 배송지의 미봉인 패키지가 있으면 합류(분리배송이면 항상 신규, 단 현재 그래프 구조상 dead code — JOURNAL.md 참고). required/arrived count 체크, 충족시 봉인+tracking_number 발급 |
| 액션 | 포장agent | 액션 | 포장 완료 처리 (Package 단위 일괄, "포장중" 중간상태는 item 레벨엔 없음) |
| 판단+반복 | 피킹지연게이트 | self-loop 조건분기 | Item 기반. `item_delay_reason` 있는 item만 대상, 해소되면 피킹완료 확정, 미해소면 자기루프, retry_count 초과시 item escalated=true |
| 판단+반복 | 조립대기게이트 | self-loop 조건분기 (순수 워처) | 미봉인 Package(`tracking_number is None`) 기반. 스스로 해소하지 않고 감시만 함 — 실제 해소는 피킹지연게이트+패키지조립agent 재봉인으로 일어남. retry_count 초과시 package escalated=true |
| 판단+반복 | 배송중게이트 | self-loop 조건분기 | 봉인된 Package(`tracking_number` 있음) 기반. `delay_categories` 체크(외부신호/폴링 데모는 고정 매핑), 자연재해는 재시도 없이 즉시 escalated=true. 그 외 지연은 매 틱마다 먼저 Supervisor(predict_delay_escalation)에게 조기 에스컬레이션 여부를 묻고, "아직 지켜봐도 됨"이면 기존 retry_count 초과시 escalated=true 임계치로 폴백 |
| 액션 | mock_carrier_signal | 액션 (POC 전용 신호 발생기) | 봉인된 Package를 `포장완료→출고됨→배송중→배송완료` 고정 시퀀스로 전진시키고 GPS placeholder 채움. 실제 서비스에서는 택배사 웹훅/Kafka 이벤트가 이 자리를 대체 |
| 판단+반복 | 추적agent | self-loop 조건분기 + 파생 재계산 | 신호를 만들지 않고 현재 item_status/delay_categories만 보고 Order 파생값(internal_order_status, customer_facing_status) 재계산, 배송완료 도달 여부 판단 → 도달시 종료, 아니면 mock_carrier_signal로 재진입 |
| 부가 | 알림agent | 조건부 발송 (비차단) | notification_enabled 확인 후 notification_log에 기록. 워크플로우를 막지 않음 |

**구현 현황**: UserProfile조회 / 주문요청 / 주문검증 / Supervisor(더미) / 창고처리 / 피킹지연게이트 / 패키지조립 /
포장 / 조립대기게이트 / 배송중게이트 / mock_carrier_signal / 추적agent = 구현됨(`logistics_agent/nodes/`).
알림agent = **설계만 있고 코드 없음** (다음 단계).

<a id="removed-integrated"></a>
### 제거/통합된 것들 (설계 과정에서 폐기 — 이유 포함)
- ~~출고agent~~, ~~배송출발agent~~ → 추적agent로 흡수 (물리적 액션이 아니라 외부 신호 수신이라 판단)
- ~~Join노드~~ → 패키지조립agent 내부 카운트 로직으로 흡수 (동기화→비동기 전환하며 별도 노드일 필요 없어짐)
- ~~주문상태갱신agent~~ → 추적agent로 통합 (이름이 "주문 수정"과 혼동되어 재명명 겸 통합)
- ~~outbound_ready / notification_ready~~ → 불필요 (병렬 Join 자체가 없어지며 무의미해짐)
- ~~송장번호agent~~ → 패키지조립agent 봉인 시점에 추적agent가 함께 처리 (규모상 별도 노드 불필요)
- ~~delay_risk (bool)~~ → 불필요, delay_categories.length > 0 으로 파생 계산

---

<a id="state-schema"></a>
## State 스키마 (v15)

버전별 변경 이력(왜 이 필드가 이 시점에 생겼는지)은 [JOURNAL.md](JOURNAL.md) "State 스키마
변경 이력" 참고. 아래는 현재 상태만 담는다.

> GraphState 최상위 키: `user_id` / `confirmed_order_items` / `payment_status_hint` /
> `split_delivery_preference_hint` / `order_created_at_hint`(진입 입력),
> `user_profile`, `order`, **`packages: list[PackageState]`**, `validation_passed` / `validation_errors`, `supervisor_decision` / `supervisor_notes`.
> Package는 Order 안이 아니라 **최상위**에 있다 — 원칙 5(Order-Package는 1:N)를 State 구조로 지킨 것.

<a id="schema-address"></a>
### Address (delivery_addresses 원소)
| 필드 | 타입 | 비고 |
|---|---|---|
| address_id | string | `ADDR-HOME` 같은 주소록 id, 또는 주문 시점 신규주소면 `ADDR-{6hex}` 발급 |
| recipient / phone / postal_code / address_line | string | 주문검증agent가 이 4개의 존재 여부를 검사 |

<a id="schema-order"></a>
### Order State
| 필드 | 타입 | 비고 |
|---|---|---|
| order_id | string | |
| order_created_at | timestamp | entry.py가 `order_created_at_hint` 입력이 있으면 그대로, 없으면 실제 현재시각으로 채움 |
| delivery_addresses | list[Address] | 이 주문의 item들이 실제 참조하는 배송지만. UserProfile 주소록 참조 + 주문 시점 신규주소 |
| payment_status | string(enum) | 대기/완료/실패 |
| split_delivery_preference | bool | 생성 시 확정, 이후 불변. entry.py가 `split_delivery_preference_hint` 입력을 그대로 반영. assembly.py의 그룹핑 키에 실제로 반영됨 — true면 같은 배송지도 item별 별도 Package |
| cancel_requested_at | timestamp/null | |
| cancel_status | string(enum)/null | 요청됨/처리중/완료/거부됨 |
| internal_order_status | string(enum) | 파생값. 최종 소유자는 추적agent — `derive_internal_order_status()` (tracking.py), 패키지조립agent도 같은 함수를 import해서 씀 |
| item_list | list[Item] | 아래 Item 참고 |
| current_item_index | int | 창고처리agent 순회 위치 |
| notification_enabled | bool | 현재 설정값 (UserProfile에서 복사) |
| trace_id | string | LangSmith trace ID, Decision 역추적용 |

<a id="schema-item"></a>
### Item (item_list 원소)
| 필드 | 타입 | 비고 |
|---|---|---|
| item_id | string | |
| item_status | string(enum) | 대기/피킹중/피킹완료/포장완료/출고됨/배송중/배송지연/배송완료 |
| item_delay_reason | string/null | 재고부족/검수불량/파손 등 Item 고유 지연 원인. 값이 있으면 창고처리agent가 피킹 스킵 |
| package_ref | string/null | 소속 Package (조립 전 null) |
| delivery_address_id | string | Order.delivery_addresses 중 하나 참조. **패키지조립agent의 그룹핑 키** |
| location | Location/null | 창고 내 위치, 포장 전까지만 유효. 아래 Location 참고 |
| customer_facing_status | string(enum) | 파생값. item_status를 사용자용으로 매핑. item_delay_reason이 있는 동안(재시도/에스컬레이션 불문)은 피킹지연게이트가 "지연"으로 덮어씀 |
| policy_version_applied | string/null | 지연 감지 당시 적용 정책 버전 (PackageState 동명 필드와 대칭) |
| last_checked_at | timestamp/null | 피킹지연게이트 폴링 기록. 지연 이력이 없으면 null |
| retry_count | int | 피킹지연게이트 self-loop 진입 횟수 |
| escalated | bool | 사람 개입 필요 여부. true여도 백그라운드 자동처리는 계속(비차단) |

<a id="schema-package"></a>
### Package State
| 필드 | 타입 | 비고 |
|---|---|---|
| package_id | string | |
| source_items | list[SourceItemRef] | {order_id, item_id} — 같은 주문 내 여러 item을 담음 (여러 주문 합포장은 없음) |
| delivery_address_id | string | 이 패키지의 배송지. 미봉인 패키지 재사용 시 매칭 키 |
| required_item_count | int | source_items 개수 |
| arrived_item_count | int | item_status가 피킹완료 이상인 source_item 수 |
| current_gps | GpsPoint/null | 출고 이후에만 채워짐. 조립 시점엔 null. 아래 GpsPoint 참고 |
| tracking_number | string/null | |
| delay_categories | list[string] | 빈 배열=지연없음. 여러 원인 동시 가능 |
| policy_version_applied | string/null | 지연 감지 당시 적용 정책 버전 (역추적/감사용) |
| last_checked_at | timestamp | 모니터링 폴링 기록 |
| retry_count | int | 지연체크게이트(조립대기게이트/배송중게이트)의 self-loop 진입(폴링) 횟수 |
| escalated | bool | 사람 개입 필요 여부. true여도 백그라운드 자동처리는 계속(비차단) |
| escalation_reasoning | string/null | escalated=true로 만든 근거 텍스트 — 설명가능성. 대부분 Supervisor(predict_delay_escalation)의 판단 근거지만, 자연재해 즉시 에스컬레이션(Supervisor 미개입, 고정 규칙)은 그 사실 자체를 알 수 있는 고정 문자열을 남긴다. 해소/지연없음 전이 시 null로 복귀 |
| join_waiting_since | timestamp/null | 패키지 조립 무한대기 방지용 타임아웃 기준. **첫 대기 시각 보존** (재진입 시 덮어쓰지 않음), 봉인 시 null로 복귀 |
| notification_log | list[NotificationEntry] | {stage, sent_at, enabled_at_time} — 판단 아닌 기록 |

<a id="schema-location"></a>
### Location (item.location)
| 필드 | 타입 | 비고 |
|---|---|---|
| zone | string | 창고 구역 (A/B/C…) |
| shelf | string | 선반 번호 |
| bin | string | 칸 번호 |

창고처리agent가 값이 없는 item에 기본값 `{zone: A, shelf: 01, bin: 03}`을 채워 넣는다 (센서 조회 placeholder).

<a id="schema-gpspoint"></a>
### GpsPoint (package.current_gps)
| 필드 | 타입 | 비고 |
|---|---|---|
| lat | float | |
| lng | float | |
| updated_at | timestamp | 이 좌표를 받은 시각 |

조립 시점엔 null. 추적agent가 채운다 — item_status가 "출고됨" 이상으로 전진할 때마다
진행 단계 기반 placeholder 좌표로 갱신 (실제 GPS 폴링 아님).

<a id="schema-userprofile"></a>
### UserProfile (별도 캡슐, 참조 전용)
| 필드 | 타입 | 비고 |
|---|---|---|
| user_id | string | |
| delivery_addresses | list[Address] | 주소록. [0]이 기본배송지 |
| payment_method | PaymentMethod | 아래 참고 |
| notification_enabled | bool | Order 생성 시 이 값을 복사해 옴 |

<a id="schema-paymentmethod"></a>
### PaymentMethod (userprofile.payment_method)
| 필드 | 타입 | 비고 |
|---|---|---|
| type | string | card / bank_transfer 등 |
| last4 | string/null | 카드 뒷 4자리. 카드가 아니면 null (예: user-002는 bank_transfer라 null) |

주문검증agent는 현재 `payment_status`만 보고 `payment_method`는 검사하지 않는다.

---

<a id="open-questions"></a>
## 아직 결정 안 된 것 / 다음에 확인할 것
- `order_item_id`(item_id와 분리된 유닛 식별자) 신설 여부 — 지금은 `order_validation_agent`의
  item_id 중복 검사로 임시 대응 중(발견 경위: JOURNAL.md 참고).
  "동일 상품 복수 주문"이 이 프로젝트의 실제 검증 시나리오가 될 때 다시 열어볼 것
- 조립대기게이트는 실제 경과시간이 아니라 `retry_count`(self-loop 진입 횟수)를 타임아웃 판단 기준으로 쓴다
  — 동기 실행되는 POC 데모에서 벽시계 시간 경과를 재현할 수 없어서 튜닝한 단순화. `join_waiting_since`는
  여전히 최초 대기 시각을 보존하는 기록용 필드로 남아있음 (판단=retry_count / 기록=join_waiting_since, 원칙3).
  실제 서비스라면 폴링 주기 × 경과 tick 또는 진짜 타임스탬프 비교로 대체해야 함
- 지연 카테고리 우선순위 정책(자연재해 > 교통지연 등)의 실제 테이블 구조 — 온톨로지(Neo4j) 단계에서 확정 예정
- 자연재해 지연의 종료 조건 — 외부 재해상태 API 연동 전제, 없으면 사람 확인 fallback
- Supervisor의 decision_type 2개(proceed_to_warehouse, predict_delay_escalation)는 "하나의 노드 안에서
  분기"가 아니라 **각자 다른 함수 + 다른 호출 지점**으로 풀렸다 — 그래프 노드가 딱 하나뿐이어야 한다는
  전제 자체가 틀렸던 것으로 보임. decision_type이 더 늘어나면(예: 물체 취급주의 판단) 이 패턴이
  계속 맞을지, 아니면 진짜 dispatcher가 필요해질지는 다음에 늘어날 때 다시 볼 것
- Gemini 응답의 신뢰성(구조화 출력 파싱 실패, 프롬프트 인젝션 가능성 등)에 대한 방어는 아직 없음 —
  `.with_structured_output()`이 실패하면 그대로 예외가 나서 `predict_delay_escalation`의 폴백
  경로를 타긴 하지만, "이상하지만 파싱은 되는" 응답(예: reasoning이 텅 비거나 프롬프트를 그대로
  반복)까지 걸러내진 않음
- 온톨로지(Neo4j) 스키마는 "워크플로우가 필요로 하는 만큼만" 상향식으로 만들기로 함 — 아직 미착수
- **`decide_warehouse_entry`(구 `supervisor()`)는 지금 온톨로지 조회조차 없는 완전한 pass-through다.**
  창고처리 여부를 사실상 항상 "진행"으로 고정 반환할 뿐, 실제로 뭔가를 조회하거나 판단하지 않는다.
  온톨로지(Neo4j) 구축 이후 다음 단계로 고려할 구조: 이 자리에 **별도의 "온톨로지조회노드"**
  (판단 없음, Agent 아님 — 단순 조회)를 추가하고, 진짜 Supervisor(예측/판단 영역)는 그 조회
  결과에서 이상 신호가 발견될 때만 개입하도록 나눈다. `predict_delay_escalation`이 이미
  "이상 신호가 있을 때만 LLM 개입"이라는 같은 패턴을 배송중게이트에서 쓰고 있어 선례로 참고할 수 있다.
- 피킹지연게이트가 여전히 창고처리agent 대신 item_status를 직접 확정한다 — 창고처리agent
  재진입성 리팩터는 의도적으로 보류 중, 다음 단계 후보
- 알림agent 미착수 — notification_enabled 필드는 이미 있음 (아래 "미구현/죽은 필드 종합" 참고)
- `tracking.py`의 `_SHIP_SEQUENCE`와 `_CUSTOMER_FACING_MAP`은 서로 암묵적으로 동기화돼야 하는
  두 자료구조다 (`_SHIP_SEQUENCE`의 각 값이 `_CUSTOMER_FACING_MAP`의 키와 정확히 일치해야 함).
  지금은 둘 다 4개로 손으로 맞춰놔서 안전하지만, 나중에 배송 단계를 추가하면서 한쪽만 갱신하면
  `_CUSTOMER_FACING_MAP[next_status]`에서 `KeyError`(fallback 없는 직접 subscript)로 즉시 죽는다.
  `list[tuple[str, str]]`(상태, 매핑값) 하나로 합쳐 애초에 동기화 이슈 자체를 없애는 개선안이 있음
- **재고부족이 영구 에스컬레이션되면(`item_delay_reason="재고부족"` + `escalated=True`)
  customer_facing_status가 "지연"인 게 맞는지 재검토 필요.** "지연"은 "곧 온다"는 뜻인데
  영구화된 재고부족은 실서비스라면 품절/취소에 가깝다. 지금은 `_ITEM_RESOLVE_AT_RETRY["재고부족"]=2`라
  이 조합 자체가 구조상 도달 불가능해서(항상 MAX_GATE_RETRIES 이전에 해소됨) 실제 버그는 아니다.
  **위 "사람 개입 워크플로우" 설계가 답을 상당 부분 냈다** — `customer_facing_status`에
  "상품준비불가"를 신설하고, `cancel_status`는 재사용하지 않는다(구매자 능동 선택 흐름과 성격이
  다름). 논의된 세부 내용은 JOURNAL.md 참고.

<a id="dead-fields"></a>
## 미구현/죽은 필드 종합

스키마엔 있지만 실제로는 아무도 채우지 않거나, 채워져도 아무도 읽지 않는 필드들. 여러 대화에서
따로따로 발견된 걸 여기 한곳에 모았다 — 새 필드를 스키마에 추가하기 전에 먼저 여기부터 확인할 것.

1. **`ItemStatus`의 `"피킹중"`, `"배송지연"`** — 실제로 이 값을 세팅하는 코드가 어디에도 없는
   죽은 enum 값이다. 창고처리agent는 "대기"→"피킹완료"로 바로 건너뛰고, "배송지연"은 아예 아무도
   대입하지 않는다. 특히 "배송지연"은 이미 `item_delay_reason`(재고부족/검수불량/파손)이 지연
   사유를 표현하고 있어서 중복 개념일 가능성이 있다.
   **구현 시점 예상**: "피킹중"은 창고처리agent 재진입성 리팩터 시 진행중 상태 표시가 필요해지면
   채워질 후보. "배송지연"은 item_delay_reason과의 관계를 온톨로지 단계에서 정리하면서 결정.
2. **`NotificationEntry`(`notification_log`)** — `package_assembly_agent`의 `_new_package`가
   빈 리스트로 초기화만 하고, 실제로 항목을 append하는 코드는 어디에도 없다. 알림agent가
   미구현이라 당연한 결과.
   **구현 시점 예상**: 알림agent 구현 시.
3. **`trace_id`** — 다른 둘과는 성격이 다르다. entry.py가 `uuid.uuid4().hex`로 값 자체는
   채우지만(완전히 죽은 필드는 아님), 그 값을 실제로 참조/활용하는 코드는 어디에도 없다 —
   LangSmith 같은 관측성 연동이 없어서 "쓰기만 하고 아무도 안 읽는" 상태.
   **구현 시점 예상**: 관측성/LangSmith 연동 시.

<a id="extension-points"></a>
## 확장 지점 (지금 범위 밖, 문서에만 남김)
- 판매량 예측 기반 재고 확보(사전 발주/보충) — "재고부족" 개념의 세 층위 중 층위3(위 참고).
  이 주문 워크플로우의 예외 처리(층위2, 피킹지연게이트가 이미 담당)와는 다른 책임 — 별도 상위
  시스템(재고관리/배치성 수요예측) 영역
- Kafka/Confluent/ClickHouse 등 실제 스트리밍 인프라 — POC에서는 간단한 신호 발생기(`mock_carrier_signal`)로 대체함
- Unity Catalog류 거버넌스 계층 — Neo4j(온톨로지)와는 별개로, 데이터/툴 접근 통제용으로 향후 고려
- 취소 워크플로우 (cancel_requested_at/cancel_status는 필드만 존재, 처리 흐름 미구현)
- 사용자 endpoint "도킹" 개념 (사이트별 프로필 스키마를 표준 캡슐로 변환하는 어댑터) — 현재 기술로 완전 표준화 어려움, 개념만 남김
- `_is_valid_address`는 필드가 채워졌는지(형식)만 검사하고, 실제 존재하는 주소인지(우편번호 유효성,
  도로명주소 실존 여부)는 검증하지 않는다. 실제 서비스라면 이 지점에 외부 주소 검증 API(우체국
  도로명주소 API 등) 연동이 필요하며, 이는 `mock_carrier_signal`이 실제 캐리어 API 자리를 대신하는
  것과 같은 성격의 "외부 시스템 경계" 지점이다.

<a id="production-notes"></a>
## 실무 전환 시 고려사항
- `main.py`의 데모 시나리오 11개는 POC 검증용이다. 실제 서비스화 시 `main.py`(순수 진입점)와
  `tests/`(시나리오 이관, pytest 등 정식 프레임워크로) 분리가 필요하다.
