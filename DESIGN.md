# 물류 멀티에이전트 POC 설계 메모

## 목적
온톨로지 기반 멀티에이전트 설계 포트폴리오를 위한 학습용 최소 구현.
이 코드 자체가 최종 포트폴리오는 아님 — 핵심 패턴(State 설계, 조건분기, self-loop)을 직접 구현해보고 이해한 뒤, 타 사례를 참고/엮어서 포트폴리오화할 예정.

엔드포인트를 사람뿐 아니라 센서/로봇(액추에이터)까지 포함하는 것을 지향.
Agent-to-Agent, Agent-to-Sensor/Actuator 통신이 사람 endpoint보다 우선순위 높음.

---

## 진행 상황

- [x] 1단계: UserProfile조회 → 주문요청agent → 주문검증agent(조건분기) → Supervisor(더미) → 창고처리agent(placeholder)
- [x] 2단계: 패키지조립agent (배송지 정규화 v11 + 중첩구조 타입 승격 v12)
- [x] 3단계: 지연체크게이트 3종 (출고전/조립대기/배송중, self-loop 패턴, Item에 retry 필드 추가 v13)
- [x] 4단계: 추적agent (범용 이벤트 수신 + 파생값 재계산) — 선행 조건으로 포장agent도 함께 구현
- [x] 4단계 후속: split_delivery_preference를 패키지조립agent 그룹핑에 실제 반영, 시나리오9로 검증 완료
- [x] 4단계 후속: Supervisor predict_delay_escalation (Google Gemini 실제 호출) 배송중게이트에 통합, 시나리오10 추가

## 1단계 실행 결과 요약
- 시나리오1 (payment_status=대기): 검증 실패 → internal_order_status="검증실패", Supervisor 미진입 확인됨
- 시나리오2 (payment_status=완료): 검증 통과 → Supervisor(proceed_to_warehouse) → 창고처리(Sensor→Action 순회) → item_status="피킹완료" 확인됨

## 2단계 실행 결과 요약
- **선행 작업**: 배송지를 정규화해야 그룹핑이 성립함을 확인. `Order.delivery_address`(단수) → `delivery_addresses`(list) + `Item.delivery_address_id` 참조 구조로 변경(v11). 그룹핑 키가 dict 비교가 아니라 id 하나가 됨.
  배송지 소스는 둘 다 지원 — UserProfile 주소록에서 id 참조 / 주문 시점 인라인 신규주소(같은 주소를 쓴 item은 dedupe되어 한 패키지로). 주소록에 없는 id는 crash 대신 주문검증agent가 걸러냄(관문 노드 역할 확장).
- **대기 케이스 가시화**: 창고처리agent가 모든 item을 무조건 피킹완료로 만들어 대기 브랜치가 실행 불가였음 → `item_delay_reason` 있으면 피킹 스킵(item_status "대기" 유지)하도록 최소 수정.
- 시나리오2 (2 item, 배송지 미지정 → 기본배송지): 패키지 1개, required=2 arrived=2 → 봉인, tracking_number 발급, internal_order_status="출고준비"
- 시나리오3 (배송지 3곳 = 주소록2 + 신규1, 재고부족 1건): 패키지 3개 생성 → ADDR-HOME(2/2) 봉인, ADDR-OFFICE(1/2) **대기 + join_waiting_since 기록**, 신규주소(1/1) 봉인 → internal_order_status="조립중"
- 재고부족 item도 `package_ref`는 배정됨 (배정 ≠ 도착). 봉인 시 `item_status`는 건드리지 않음 — "포장완료" 전이는 포장agent 몫
- **배운 것**: 대기 여부는 별도 bool 없이 `tracking_number is None`으로 파생 가능 (delay_risk 폐기와 같은 원칙). `join_waiting_since`는 첫 대기 시각을 보존해야 타임아웃 기준으로 쓸 수 있음 — 재진입마다 덮어쓰면 무의미해짐

### 2단계 마무리: 타입 경고 정리 (해결됨)
TypedDict를 쓰면서 반복적으로 나던 Pylance 경고 3종을 원인별로 정리했다. **로직 변경 없음.**

| 경고 | 원인 | 결정 |
|---|---|---|
| `{**td, ...}`가 TypedDict에 대입 안 됨 (11곳) | 스프레드가 포함된 dict 표현식은 `dict[str, Unknown]`으로 추론됨 | `cast(OrderState, {**order, ...})`로 통일. 스프레드 자리에만 쓰고, 키를 새로 쓰는 자리(`_new_package`)에는 쓰지 않음 — 거기선 cast가 오타를 가려버림 |
| `Address`를 `dict` 파라미터에 못 넘김 | **TypedDict는 `dict[...]`에 대입 불가** (임의 키 추가/삭제가 구조를 깨뜨리므로). 읽기 전용 매핑에만 대입 가능 | `_is_valid_address(address: Mapping[str, object])`. `Address`로 좁히지 않은 이유: 이 함수는 "키 누락"을 검사하는데 `Address`(total=True)는 키가 다 있다고 단언 → 자기모순. 인라인 신규주소는 사용자 입력이라 실제로 키가 빠질 수 있음 |
| `state["order"]` 필수 키 아님 | `GraphState`가 `total=False`(부분 업데이트 반환용) | 코드로는 해결 불가 — `order`를 Required로 만들면 `return {"validation_passed": ...}` 같은 부분 반환이 깨짐. `pyrightconfig.json`에서 `reportTypedDictNotRequiredAccess`만 끔 |

`pyrightconfig.json`에는 `include`(venv 스캔 방지), `venvPath`/`venv`(langgraph import 해석), `typeCheckingMode: standard`(IDE 설정과 무관하게 고정)도 함께 명시했다.
**이 한 규칙 외에 다른 규칙을 끄지 않는다** — 나머지 경고는 실제 문제일 가능성이 높다.

## 3단계 실행 결과 요약

세 게이트를 `창고처리agent → 출고전게이트 → 패키지조립agent → 조립대기게이트 → 배송중게이트`
순서로 파이프라인에 삽입했다. 셋 다 "미해소면 자기 자신으로 self-loop, `retry_count`가
`MAX_GATE_RETRIES`(3)를 넘으면 `escalated=True`로 표시하고 (비차단으로) 다음 단계 진행"이라는
동일한 뼈대를 재사용한다. 데모 시나리오(main.py 4~7번)로 확인한 결과:

- 시나리오4 (정상 통과): 지연 없는 주문 → 세 게이트 모두 self-loop 없이 1회 통과, `retry_count` 전부 0
- 시나리오5 (재시도 후 통과): 재고부족 item이 출고전게이트에서 2회 재시도 후 해소(`item_delay_reason=None`,
  `item_status="피킹완료"`) → 정상 봉인 → 배송중게이트에서 해당 배송지(ADDR-OFFICE)의 "교통지연"이
  1회 재시도 후 해소(`delay_categories=[]`)
- 시나리오6 (재시도 초과 에스컬레이션 — 연쇄): "파손"은 데모 매핑상 재시도로 해소되지 않도록 설계 →
  출고전게이트가 3회 재시도 후 4번째 진입에서 item `escalated=True` → item은 끝내 피킹되지 않아
  패키지도 `required=1, arrived=0`으로 영원히 미봉인 → 조립대기게이트도 3회 재시도 후 package
  `escalated=True`. 게이트1의 미해소가 게이트2의 에스컬레이션으로 그대로 이어지는 연쇄를 확인함
  (패키지가 미봉인 상태라 배송중게이트에는 아예 도달하지 않음 — 대상 필터가 `tracking_number is not None`이라 자연 스킵)
- 시나리오7 (즉시 에스컬레이션): 자연재해 신호는 재시도 없이 최초 진입에서 바로
  `escalated=True`(`retry_count=0` 그대로) — "재시도 초과형"과 "즉시형" 두 에스컬레이션 트리거가
  서로 다른 코드 경로임을 확인함

**설계 결정 — 조립대기게이트는 순수 워처.** 처음엔 게이트2가 스스로 "지연 아이템 도착"을 흉내 내고
패키지조립agent로 되돌아가 재봉인시키는 2노드 사이클 안도 검토했으나, 그러면 게이트2만
다른 두 게이트와 형태가 달라진다(진짜 self-loop가 아니라 게이트↔조립agent 사이클). 대신 게이트2는
`tracking_number is None`인 패키지를 감시만 하고, 실제 해소는 항상 출고전게이트(1번)가
`item_delay_reason`을 풀어준 결과로 패키지조립agent의 다음 패스에서 자연스럽게 일어나도록 했다.
그 결과 세 게이트가 완전히 동일한 "단일 노드 self-loop" 형태를 유지한다.

**해소 판정은 전부 데모용 고정 매핑.** 실제 외부신호(재고센서, 물류사 API) 대신
`item_delay_reason`별 해소 시점(`_ITEM_RESOLVE_AT_RETRY`), `delivery_address_id`별 지연신호
(`_PACKAGE_DELAY_SIGNAL`)를 고정 딕셔너리로 뒀다. `package_id`는 uuid라 데모 스크립트가 사전에
못 박을 수 없어서, 배송중게이트의 매핑 키만 `package_id` 대신 `delivery_address_id`를 썼다 —
실제 구현이라면 패키지 자체의 속성(현재 위치, 배송 경로 등)으로 신호를 조회하겠지만 POC 범위 밖.

**타임아웃은 실제 경과시간이 아니라 재시도(틱) 횟수로 근사.** `join_waiting_since`는 여전히
최초 대기 시각을 보존하는 기록 필드로 남아있지만(원칙3), 조립대기게이트의 판단 자체는
`retry_count`(self-loop 진입 횟수)로 한다 — 동기 실행되는 POC 데모에서 실제 벽시계 시간 경과를
재현할 방법이 없기 때문. `retry_count`가 판단, `join_waiting_since`가 증거 기록이라는 역할
분리가 원칙3을 그대로 따른다.

### POC 단순화 사항 (4단계 이후 재검토 필요)

3단계 구현 과정에서 "지금 범위에서 굳이 풀 필요 없다"고 접어둔 것들. 나중에 4단계(추적agent)나
실제 온톨로지/외부 신호 연동을 붙일 때 다시 열어봐야 한다.

1. **출고전게이트가 창고처리agent 대신 item_status를 직접 갱신한다.** 원래 "피킹 완료" 전이는
   창고처리agent의 역할인데, 창고처리agent는 `current_item_index`를 이미 `len(item_list)`까지
   진행시켜버려서 재호출해도 스킵된 item을 다시 볼 방법이 없다 (2단계 코드 그대로 재사용).
   그래서 출고전게이트가 해소를 확인하는 김에 `item_status="피킹완료"`/`customer_facing_status="준비중"`
   확정까지 직접 떠맡았다 — 관측(판단)과 액션(피킹 확정)이 한 노드에 섞인 상태.
   4단계에서 창고처리agent가 "지연 해소된 item만 재피킹"할 수 있게 재진입 가능해지면,
   출고전게이트는 다시 순수 판단(해소 여부 체크)만 하고 액션은 창고처리agent로 돌려줘야 한다.
   **(4단계 착수 시점에 재확인 — 이번 범위에서는 그대로 보류하기로 결정.** 추적agent 작업과
   결합할 이유가 없어 별도 리팩터로 남겨둠.)
2. **배송중게이트의 지연 감지가 실제 물류 신호가 아니라 `delivery_address_id` 기준 고정 매핑
   (`_PACKAGE_DELAY_SIGNAL`)이다.** 원래는 패키지 자체 속성(현재 위치, GPS, 배송 경로 등)이나
   물류사 API/GPS 폴링으로 지연을 감지해야 하는데, `package_id`가 데모 시점에 미리 알 수 없는
   uuid라 데모 스크립트가 통제 가능한 유일한 키인 배송지로 대신했다. 온톨로지(Neo4j) 단계에서
   실제 지연 신호 조회 경로가 생기면 대체해야 함.
3. **조립대기게이트/배송중게이트가 실제 경과시간이 아니라 `retry_count`(self-loop 진입 횟수,
   즉 "틱")를 기준으로 판단한다.** `join_waiting_since`(조립대기)는 최초 대기 시각을 기록만 할 뿐
   실제 타임아웃 판정에는 관여하지 않는다. 동기 실행되는 POC 데모에서는 벽시계 시간이 흐르지
   않아 tick 수로 대체할 수밖에 없었음 — 실제 서비스라면 폴링 주기 × 경과 tick 환산이나
   `datetime.now() - join_waiting_since`와 임계값 비교로 바꿔야 한다.
4. **추적agent가 봉인된 패키지들을 lockstep으로 함께 전진시킨다.** 출고전게이트가 패키지조립agent
   진입 전에 모든 지연을 이미 해소/에스컬레이션해버리므로, 한 번의 그래프 실행에서 봉인되는
   패키지들은 전부 같은 시점에 추적agent 루프에 진입해 같은 틱마다 함께 한 단계씩 전진한다.
   실제로는 캐리어마다, 패키지마다 이벤트 도착 시각이 다르므로 서로 다른 배송지의 두 패키지가
   같은 틱에 항상 나란히 "배송중"이 되는 일은 없다. 온톨로지/실제 이벤트 연동 단계에서 패키지별
   독립적인 이벤트 타이밍으로 대체해야 함.
   **(원칙6 위반은 아님 — 패키지 간에 서로를 막는 의존성은 코드에 없다.** `tracking_agent`의
   전진 판단은 오직 그 패키지 자신의 `item_status`만 본다. 먼저 끝난 패키지는 이후 틱에서
   그냥 조용히 스킵될 뿐, 뒤처진 패키지가 앞선 패키지를 붙잡아두지 않는다. lockstep은 "봉인
   시점 자체가 이번 POC에서는 항상 한 번에 뭉쳐서 발생한다"는 상류 타이밍의 결과일 뿐, 하류의
   join/wait 구조가 아니다.)
5. **`current_gps`가 실제 GPS 신호가 아니라 진행 단계(`_SHIP_SEQUENCE`의 index)로부터 계산한
   고정 좌표다.** 창고처리agent의 기본 `Location`과 같은 성격의 placeholder — 실제로는 캐리어
   GPS 폴링으로 채워져야 한다.
6. **`derive_internal_order_status`가 패키지 하나라도 미봉인이면 order 전체를 "조립중"으로
   뭉뚱그린다.** 다른 패키지가 이미 "배송완료"에 도달했어도 마찬가지다. `InternalOrderStatus`
   enum에 "부분배송중"에 해당하는 값이 없다는 게 근본 원인 — 2~3단계부터 있던 all-or-nothing
   판정 패턴을 4단계가 그대로 이어받았다. 지금까지의 데모 시나리오에는 "한 패키지는 끝까지
   배송되고 다른 패키지는 영구 대기"인 조합이 없어서 이 gap이 드러난 적이 없었다. 온톨로지
   단계에서 enum 재설계와 함께 다시 열어봐야 한다.

## 4단계 실행 결과 요약

추적agent 자체가 유일한 목표였지만, item_status enum상 "출고됨" 이후 이벤트는 논리적으로
"포장완료"를 전제로 해서 포장agent도 함께 구현했다 (사용자와 확인 후 범위 확장).
파이프라인은 `... → 패키지조립agent → 포장agent → 조립대기게이트 → 배송중게이트 → 추적agent`.

- **추적agent도 게이트와 같은 self-loop 뼈대를 재사용하되, `retry_count`/`escalated`는 쓰지
  않는다.** 게이트들은 "지연이 해소되길 기다리는" 판단이라 재시도 횟수·에스컬레이션이 의미
  있지만, 추적agent는 "정해진 이벤트 시퀀스(포장완료→출고됨→배송중→배송완료)를 그냥 진행시키는"
  것이라 실패/타임아웃 개념이 없다. 대신 **`item_status` 값 자체가 진행 카운터** 역할을 한다 —
  틱마다 시퀀스에서 현재 값의 다음 값으로 한 칸 전진. 새 State 필드가 필요 없었다(v13 스키마 유지).
  `PackageState.retry_count`를 재사용하지 않은 이유: 그 필드는 이미 "지연체크게이트의 self-loop
  진입 횟수"로 문서화돼 있고, 배송중게이트를 통과한 패키지의 값이 0이 아닐 수 있어(교통지연 재시도 등)
  추적agent가 같은 필드를 이어 쓰면 두 노드의 서로 다른 의미가 한 필드에서 충돌했을 것.
- **이벤트는 패키지 단위로 발생시키고, 같은 패키지의 모든 item에 동일하게 반영한다.** 원칙1
  (물류사API/캐리어 신호는 Package 사건)을 그대로 따름 — item마다 독립적으로 전진시키지 않는다.
- **`escalated=true`인 패키지도 계속 전진시킨다.** `PackageState.escalated` 필드 주석의 "비차단"
  원칙을 실제로 지킨 첫 사례 — 자연재해로 에스컬레이션된 패키지(ADDR-STORM, 시나리오7)도 배송
  자체는 끝까지 진행되고, 그 사이 `customer_facing_status`는 "지연"으로 노출된다.
- **`internal_order_status`/`customer_facing_status` 파생값 소유권을 추적agent로 정식 이관.**
  `derive_internal_order_status()`를 추적agent 모듈에 두고 패키지조립agent가 import해서 쓰도록
  바꿔, 두 노드가 같은 판단 로직을 공유한다 (패키지조립agent의 `TODO(4단계)` 주석 해소).
- 시나리오8(배송지 2곳, 지연 없음)로 패키지 여러 개가 함께 봉인되고 함께 "완료"까지 도달하는
  것을 확인. 다만 두 패키지가 같은 틱에 나란히 전진한 것은 lockstep 단순화(POC 단순화 4번) 때문 —
  실제로는 각기 다른 시점에 이벤트를 받아야 한다.

### 4단계 후속: mock_carrier_signal / 추적agent 분리

처음 구현한 추적agent는 "이벤트 시뮬레이션"과 "파생값 판단"을 한 노드에 합쳐놓은 상태였다.
DESIGN.md 노드 목록이 원래 정의한 추적agent의 역할은 "상태변화 신호를 **받아서** 파생값을
재계산"하는 것이지, 신호 자체를 만들어내는 게 아니다 — 그래서 둘을 분리했다.

- **`mock_carrier_signal`(액션, POC 전용)**: 봉인된 Package를 `포장완료→출고됨→배송중→배송완료`
  고정 시퀀스로 한 틱씩 전진시키고 GPS placeholder를 채운다. 함수명에 "mock"을 명시하고
  docstring에 "실제 서비스에서는 이 자리에 택배사 웹훅/Kafka 이벤트가 들어온다"고 못박아뒀다 —
  "확장 지점" 섹션이 이미 예고했던 "간단한 신호 발생기"가 바로 이것.
- **`추적agent`(판단+반복, 원래 의도로 축소)**: 신호를 만들지 않는다. 현재 `item_status`/
  `delay_categories`만 보고 `customer_facing_status`/`internal_order_status`를 재계산하고,
  배송완료 도달 여부만 판단해서 라우팅한다(도달 시 END, 아니면 mock_carrier_signal로 재진입).
  종료 여부를 별도 bool 필드로 남기지 않은 이유는 기존 파생 원칙과 동일 — `item_status`에서
  이미 계산 가능한 값이라 필드로 만들지 않았다.
- **의도적으로 2-노드 순환(mock_carrier_signal ↔ 추적agent)을 만들었다** — 이건 3단계에서
  "조립대기게이트↔패키지조립agent 2노드 사이클보다 단일노드 self-loop을 선호"한 결정과
  겉보기엔 반대다. 다른 이유가 있다: 3단계의 게이트/조립agent는 **같은 내부 시스템**이 하는
  두 가지 역할이라 억지로 나눌 이유가 없었지만, 여기서는 mock_carrier_signal이 **외부 시스템
  (캐리어)을 흉내 낸 자리**라 추적agent(내부 판단)와 개념적으로 다른 행위자다. 나중에
  mock_carrier_signal을 실제 웹훅 핸들러로 갈아끼울 때 추적agent 코드는 안 건드려도 되게
  하려면, 지금부터 그래프 구조로도 분리해두는 게 맞다고 판단했다.
- 노드 목록 분류: mock_carrier_signal=액션, 추적agent=판단+반복 (기존 "통합"에서 재분류).

### 4단계 후속: split_delivery_preference를 그룹핑에 실제 반영

`OrderState.split_delivery_preference` 필드는 2단계부터 스키마에 있었지만 entry.py가
항상 `False`로 하드코딩해서 죽은 값이었다. 이번에 두 가지를 연결했다:

- **입력 경로**: `GraphState`에 `split_delivery_preference_hint`를 추가해 `payment_status_hint`와
  같은 패턴으로 데모에서 켤 수 있게 함 (entry.py가 `state.get(...)`으로 읽어 그대로 Order에 반영).
- **실제 반영 지점**: 패키지조립agent의 그룹핑 키를 `(delivery_address_id, split이면 item_id도)`
  튜플로 바꿔, `true`면 같은 배송지라도 item마다 별도 Package가 되도록 함. 미봉인 패키지 "합류"
  탐색도 `split_pref`일 땐 항상 건너뛰어 다른 item의 패키지에 잘못 합류하지 않게 했다.
- 시나리오9(같은 배송지 item 2개, `split_delivery_preference_hint=true`)로 검증 — 두 item이
  각각 독립된 Package로 봉인되고(서로 다른 tracking_number), 끝까지 개별적으로 배송완료에
  도달하는 것을 확인. 시나리오3(기본값 `false`)은 여전히 같은 배송지 item들을 한 Package로
  묶어 회귀가 없음을 재확인.

### 4단계 후속: Supervisor의 배송 지연 위험 예측 (실제 LLM 호출)

Supervisor는 처음부터 "decision_type + payload 구조로 여러 판단 종류를 분기"한다고 설계만
해뒀을 뿐 실제로 구현된 decision_type은 `proceed_to_warehouse`(규칙 기반 더미) 하나뿐이었다.
이번에 `predict_delay_escalation`을 추가하면서 이 프로젝트에서 **처음으로 실제 LLM을 호출**한다.

- **LLM 선택 — Anthropic이 아니라 Google Gemini(무료 티어).** `langchain-google-genai`로 구현
  (langgraph 기반이라 provider 교체가 쉬움 — LangChain의 채팅모델 인터페이스로 감싸뒀기 때문).
  `GOOGLE_API_KEY`를 `.env`에서 읽는다(`python-dotenv`). 모델명은 `GEMINI_MODEL` env var로
  코드 수정 없이 바꿀 수 있게 뺐다(기본값 `gemini-3.6-flash`) — Gemini 라인업이 이후 바뀌어도
  대응 가능하도록. **실제로 이 대비가 바로 쓰였다**: 처음 기본값으로 넣었던 `gemini-2.5-flash`가
  실제 키로 호출해보니 "신규 사용자에게는 더 이상 제공 안 함, `gemini-3.6-flash` 쓰라"는 404를
  반환해서(라이브 API가 알려준 값 그대로 반영), 하드코딩이 아니라 env var였던 덕분에 로직 변경 없이
  기본값만 바꾸는 걸로 끝났다.
- **별도 그래프 노드를 만들지 않았다.** `predict_delay_escalation`은 배송중게이트가 필요할 때
  함수로 직접 호출한다 — 배송중게이트가 이미 "판단+반복" 노드라 그 판단 로직에 흡수하는 쪽이
  노드를 늘리는 것보다 낫다고 판단(CLAUDE.md의 "새 노드보다 흡수" 원칙).
- **적용 범위는 배송중게이트만.** "남은 재고부족 item 수" 같은 입력 신호는 Item을 가로지르는
  집계값이지만, 그 집계는 배송중게이트 안에서 `order["item_list"]`를 보고 계산한다 — 별도로
  출고전게이트에도 붙이지 않았다(범위를 좁게 유지).
- **기존 고정 임계치(retry_count>MAX_GATE_RETRIES)를 대체하지 않고, 그 앞에 조기 에스컬레이션
  경로를 추가했다.** Supervisor가 "아직 지켜봐도 됨"(escalate_now=false)이라고 하면 기존
  로직으로 그대로 폴백한다. 이 덕분에 LLM 호출이 실패해도(키 누락/네트워크 오류) 안전망이
  살아있다 — `predict_delay_escalation`은 실패 시 `escalate_now=False`로 보수적으로 폴백하고,
  기존 임계치가 게이트를 계속 진행시킨다.
- **판단 근거는 `PackageState.escalation_reasoning`에 남긴다** (설명가능성). 해소되거나
  지연이 사라지면 null로 되돌린다 — 판단(escalated)과 기록(escalation_reasoning)을 분리한
  원칙3을 여기에도 그대로 적용.
- **"주문 생성 이후 경과 시간"을 의미 있게 만들려고 `order_created_at_hint`를 추가했다.**
  동기 실행되는 데모에서는 주문 생성～게이트 진입까지 항상 몇 밀리초라 실제 시각을 쓰면
  이 신호가 사실상 죽은 값이 된다 — 데모에서 과거 시각을 강제할 방법이 필요해서 넣었다.
- **"남은 재고부족 item 수" 신호는 구조상 대부분 0으로 읽힌다.** 출고전게이트가 패키지조립agent
  진입 *전에* 모든 item의 지연을 이미 해소/에스컬레이션해버리기 때문에(3단계 설계), 배송중게이트가
  실행되는 시점엔 "재고부족"으로 남아있는 item이 있을 수 없다(재고부족은 `_ITEM_RESOLVE_AT_RETRY`상
  retry_count=2에서 항상 해소되도록 고정돼 있어서 escalated로 영구히 남지도 않음). 틀린 값이
  아니라 실제로 0인 게 맞는 상황이라 신호는 그대로 뒀다 — 다만 이 특정 신호가 지금 데모에서
  판단에 기여할 일은 거의 없다는 걸 기록해둔다.
- **시나리오10(대조 시나리오)**: ADDR-OFFICE(교통지연, retry_count=1이면 해소되는 가벼운 지연)에
  `order_created_at_hint`를 10일 전으로 못박아 "retry_count=0인 첫 틱인데도 Supervisor가 그래도
  조기 에스컬레이션할까"를 관찰하게 설계. **결과는 실제 Gemini 호출에 달려있어 결정론적이지
  않다** — 지금까지의 모든 시나리오와 다른 점. `GOOGLE_API_KEY` 미설정 시에는 폴백 경로를 타서
  시나리오5와 동일하게 정상 해소로 끝난다(회귀 확인 완료, API 키 없이도 데모 전체가 깨지지 않음).
  **실제 키로 라이브 검증 완료**: `retry_count=0`인 첫 틱에서 Gemini가 `escalate_now=True`,
  reasoning="주문 생성 후 240시간이 지난 상황으로, 자동 재시도 횟수와 관계없이 지연 시간이
  매우 길어 즉시 담당자 확인 및 에스컬레이션이 필요합니다"를 반환 — 고정 카운터라면 그냥
  1틱 더 기다렸을 상황을 Supervisor가 실제로 앞당겨 잡아낸 것을 확인했다. 다만 이건 한 번의
  관측일 뿐 매 실행마다 같은 결과가 보장되지는 않는다(비결정론은 여전함).

### 버그 수정: 출고전게이트가 지연 중에도 customer_facing_status를 안 바꾸던 gap

`item_delay_reason`이 있는 동안(재시도 중이든, 영구 에스컬레이션됐든) `customer_facing_status`가
계속 `"주문접수"`에 머물러 있던 걸 발견했다 — entry.py가 준 초기값이 한 번도 안 바뀐 채였다.
재고부족으로 재시도 중이든 파손으로 영구 에스컬레이션됐든 사용자 화면에는 아무 신호가 안 갔다는 뜻.

**다른 항목들과 다르게, 발견 즉시 고쳤다.** 위의 "POC 단순화 사항"이나 "아직 결정 안 된 것"에
쌓여있는 항목들은 대부분 POC 범위에서 의도적으로 접어둔 것들(실제 인프라 부재, 데모 데이터 한계
등)이라 문서화만 하고 다음 단계로 미뤄도 되는 것들이었다. 이건 성격이 다르다 — 의도한 단순화가
아니라 그냥 놓친 코드였고, 사용자에게 실질적으로 잘못된 정보(지연되고 있는데 "주문접수"로만
보임)를 노출하는 gap이라 판단을 미룰 이유가 없었다.

- **수정**: `outbound_delay_gate`의 재시도/에스컬레이션 분기(`delay_gates.py`)에
  `"customer_facing_status": "지연"`을 추가. 해소 시 기존처럼 `"준비중"`으로 복귀하는 로직은
  그대로 뒀다.
- **검증**: `outbound_delay_gate`를 격리 호출해서 재고부족(해소되는 케이스)과 파손(영구
  에스컬레이션되는 케이스) 둘 다 틱 단위로 확인 — 재시도 중엔 `"지연"`, 해소되면 `"준비중"`으로
  정확히 전이했고, 에스컬레이션된 뒤에는 더 이상 갱신되지 않으므로(에스컬레이션된 item은
  `outbound_delay_gate`가 다음 틱부터 건너뜀) `"지연"`이 그대로 유지되는 것도 확인했다 — 이건
  의도한 동작이다(더 이상 자동으로 바뀔 이유가 없는 최종 신호). 시나리오3/5/6 전체 재실행으로
  회귀 없음도 확인.

---

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

## 노드 목록 (최종)

| 분류 | 노드명 | 성격 | 역할 |
|---|---|---|---|
| 진입 | UserProfile 조회 | 조회(비판단) | 로그인 세션에서 delivery_addresses(주소록), payment_method, notification_enabled 로드 |
| 진입 | 주문요청agent | 이벤트 | 확정된 주문내역(장바구니 아님)으로 item_list 생성 |
| 관문 | 주문검증agent | 조건분기 | payment_status, 배송지 검증 → 통과/실패 |
| 판단 | Supervisor | LLM 판단 | decision_type별로 나뉨. **proceed_to_warehouse**(그래프 노드 자체, 규칙만으로 결정돼 아직 더미) / **predict_delay_escalation**(Google Gemini 실제 호출, 배송중게이트가 함수로 직접 호출 — 별도 그래프 노드 아님, 판단+근거텍스트를 SupervisorPrediction으로 반환) |
| 반복 | 창고처리agent | 조회+액션 (내장 루프) | item_list 순회, Sensor(위치확인)→Action(피킹). 정상 케이스는 온톨로지 조회로 처리, 예외만 Supervisor 호출 |
| 집계 | 패키지조립agent | 조건카운트 | `package_ref`가 없는 item을 `delivery_address_id` 기준으로 묶음(`split_delivery_preference=true`면 같은 배송지도 item별로 분리). 같은 배송지의 미봉인 패키지가 있으면 합류(분리배송이면 항상 신규). required/arrived count 체크, 충족시 봉인+tracking_number 발급. (구 Join노드 흡수) |
| 액션 | 포장agent | 액션 | 포장 완료 처리 (Package 단위 일괄, "포장중" 중간상태는 item 레벨엔 없음) |
| 판단+반복 | 출고전게이트 | self-loop 조건분기 | Item 기반. `item_delay_reason` 있는 item만 대상, 해소되면 피킹완료 확정, 미해소면 자기루프, retry_count 초과시 item escalated=true |
| 판단+반복 | 조립대기게이트 | self-loop 조건분기 (순수 워처) | 미봉인 Package(`tracking_number is None`) 기반. 스스로 해소하지 않고 감시만 함 — 실제 해소는 출고전게이트+패키지조립agent 재봉인으로 일어남. retry_count 초과시 package escalated=true |
| 판단+반복 | 배송중게이트 | self-loop 조건분기 | 봉인된 Package(`tracking_number` 있음) 기반. `delay_categories` 체크(외부신호/폴링 데모는 고정 매핑), 자연재해는 재시도 없이 즉시 escalated=true. 그 외 지연은 매 틱마다 먼저 Supervisor(predict_delay_escalation)에게 조기 에스컬레이션 여부를 묻고, "아직 지켜봐도 됨"이면 기존 retry_count 초과시 escalated=true 임계치로 폴백 |
| 액션 | mock_carrier_signal | 액션 (POC 전용 신호 발생기) | 봉인된 Package를 `포장완료→출고됨→배송중→배송완료` 고정 시퀀스로 전진시키고 GPS placeholder 채움. 실제 서비스에서는 택배사 웹훅/Kafka 이벤트가 이 자리를 대체 |
| 판단+반복 | 추적agent | self-loop 조건분기 + 파생 재계산 | 신호를 만들지 않고 현재 item_status/delay_categories만 보고 Order 파생값(internal_order_status, customer_facing_status) 재계산, 배송완료 도달 여부 판단 → 도달시 종료, 아니면 mock_carrier_signal로 재진입 |
| 부가 | 알림agent | 조건부 발송 (비차단) | notification_enabled 확인 후 notification_log에 기록. 워크플로우를 막지 않음 |

**구현 현황**: UserProfile조회 / 주문요청 / 주문검증 / Supervisor(더미) / 창고처리 / 출고전게이트 / 패키지조립 /
포장 / 조립대기게이트 / 배송중게이트 / mock_carrier_signal / 추적agent = 구현됨(`logistics_agent/nodes/`).
알림agent = **설계만 있고 코드 없음** (다음 단계).

### 제거/통합된 것들 (설계 과정에서 폐기 — 이유 포함)
- ~~출고agent~~, ~~배송출발agent~~ → 추적agent로 흡수 (물리적 액션이 아니라 외부 신호 수신이라 판단)
- ~~Join노드~~ → 패키지조립agent 내부 카운트 로직으로 흡수 (동기화→비동기 전환하며 별도 노드일 필요 없어짐)
- ~~주문상태갱신agent~~ → 추적agent로 통합 (이름이 "주문 수정"과 혼동되어 재명명 겸 통합)
- ~~outbound_ready / notification_ready~~ → 불필요 (병렬 Join 자체가 없어지며 무의미해짐)
- ~~송장번호agent~~ → 패키지조립agent 봉인 시점에 추적agent가 함께 처리 (규모상 별도 노드 불필요)
- ~~delay_risk (bool)~~ → 불필요, delay_categories.length > 0 으로 파생 계산

---

## State 스키마 (v15)

> v10 → v11 변경: 배송지 정규화. `Address.address_id` 신설, `UserProfile.delivery_address`/`Order.delivery_address`(단수) → `delivery_addresses`(list),
> `Item.delivery_address_id`(참조) 추가, `Package.delivery_address_id` 추가. 원칙 5(한 주문이 여러 배송지로 쪼개짐)를 스키마로 실제 지원하기 위함.
>
> v11 → v12 변경: **문서에만 있던 중첩 구조를 타입으로 승격.** `Item.location`과 `Package.current_gps`가 코드에선 그냥 `dict`라
> 문서가 명시한 `{zone, shelf, bin}` / `{lat, lng, updated_at}` 구조를 아무것도 강제하지 못했다 → `Location` / `GpsPoint` TypedDict 신설.
> `PaymentMethod`도 표를 만들어 문서화(타입은 이미 있었음). 필드 추가·삭제는 없고 **표현만 정밀해진 변경**이라 실행 결과는 동일.
>
> v12 → v13 변경: **3단계 지연체크게이트를 위해 `Item`에 4필드 추가**
> (`policy_version_applied`, `last_checked_at`, `retry_count`, `escalated`) — `PackageState`의 동명 필드와
> 대칭시켜 출고전게이트가 Item 층위에서도 같은 self-loop 판단 뼈대를 쓸 수 있게 함. 이 참에 `PackageState.retry_count`의
> 의미도 명확히 함: "Supervisor 재시도 조치 횟수"가 아니라 **지연체크게이트의 self-loop 진입(폴링) 횟수**로 실제 쓰임
> (문서만 갱신, 필드 자체는 원래도 이 용도로 예약돼 있었음).
>
> v13 → 4단계: **필드 변경 없음.** 추적agent도 self-loop 뼈대를 쓰지만 `retry_count`를 재사용하지
> 않았다 — 그 필드는 이미 "지연체크게이트의 폴링 횟수"로 의미가 좁혀져 있고, 배송중게이트를 거친
> 패키지는 0이 아닌 값을 들고 올 수 있어 추적agent가 이어 쓰면 두 노드의 의미가 충돌한다. 대신
> `item_status` 값 자체(포장완료→출고됨→배송중→배송완료)가 진행 카운터를 겸하도록 설계해 새
> 필드 없이 해결했다.
>
> v13 → v14 변경: **`GraphState`에 `split_delivery_preference_hint: bool` 입력 필드 신설.**
> `OrderState.split_delivery_preference` 자체는 2단계부터 있었지만 entry.py가 항상 `False`로
> 하드코딩해서 죽은 값이었다 — 이번에 패키지조립agent 그룹핑에 실제로 연결하면서, `payment_status_hint`와
> 같은 패턴으로 데모에서 켤 수 있는 입력 경로가 필요해졌다. `OrderState`/`Item`/`PackageState` 자체는
> 변경 없음, `GraphState` 최상위 입력 키 추가만 있는 변경.
>
> v14 → v15 변경: **Supervisor의 배송 지연 위험 예측(predict_delay_escalation)을 위해 필드 2개 추가.**
> `PackageState.escalation_reasoning: str | None` — Supervisor 판단의 설명가능성을 위한 근거 텍스트
> (판단=escalated bool, 기록=escalation_reasoning이라는 원칙3 그대로). `GraphState.order_created_at_hint: str`
> — "주문 생성 이후 경과 시간"을 predict_delay_escalation의 입력 신호로 쓰려면 데모에서 과거 시각을
> 강제할 방법이 필요해서 추가(`payment_status_hint`류와 같은 진입 입력 패턴).

> GraphState 최상위 키: `user_id` / `confirmed_order_items` / `payment_status_hint` /
> `split_delivery_preference_hint` / `order_created_at_hint`(진입 입력),
> `user_profile`, `order`, **`packages: list[PackageState]`**, `validation_passed` / `validation_errors`, `supervisor_decision` / `supervisor_notes`.
> Package는 Order 안이 아니라 **최상위**에 있다 — 원칙 5(Order-Package는 1:N)를 State 구조로 지킨 것.

### Address (delivery_addresses 원소)
| 필드 | 타입 | 비고 |
|---|---|---|
| address_id | string | v11 신설. `ADDR-HOME` 같은 주소록 id, 또는 주문 시점 신규주소면 `ADDR-{6hex}` 발급 |
| recipient / phone / postal_code / address_line | string | 주문검증agent가 이 4개의 존재 여부를 검사 |

### Order State
| 필드 | 타입 | 비고 |
|---|---|---|
| order_id | string | |
| order_created_at | timestamp | entry.py가 `order_created_at_hint` 입력이 있으면 그대로, 없으면 실제 현재시각으로 채움 (데모에서 "경과 시간"을 predict_delay_escalation 신호로 쓰려고 과거로 못박을 수 있게 함) |
| delivery_addresses | list[Address] | 이 주문의 item들이 실제 참조하는 배송지만. UserProfile 주소록 참조 + 주문 시점 신규주소 |
| payment_status | string(enum) | 대기/완료/실패 |
| split_delivery_preference | bool | 생성 시 확정, 이후 불변 (스냅샷 불필요). entry.py가 `split_delivery_preference_hint` 입력을 그대로 반영. **assembly.py의 그룹핑 키에 실제로 반영됨 (v14)** — true면 같은 배송지도 item별 별도 Package |
| cancel_requested_at | timestamp/null | |
| cancel_status | string(enum)/null | 요청됨/처리중/완료/거부됨 |
| internal_order_status | string(enum) | 파생값. 최종 소유자는 추적agent — `derive_internal_order_status()` (tracking.py), 패키지조립agent도 같은 함수를 import해서 씀 |
| item_list | list[Item] | 아래 Item 참고 |
| current_item_index | int | 창고처리agent 순회 위치 |
| notification_enabled | bool | 현재 설정값 (UserProfile에서 복사) |
| trace_id | string | LangSmith trace ID, Decision 역추적용 |

### Item (item_list 원소)
| 필드 | 타입 | 비고 |
|---|---|---|
| item_id | string | |
| item_status | string(enum) | 대기/피킹중/피킹완료/포장완료/출고됨/배송중/배송지연/배송완료 |
| item_delay_reason | string/null | 재고부족/검수불량/파손 등 Item 고유 지연 원인. 값이 있으면 창고처리agent가 피킹 스킵 |
| package_ref | string/null | 소속 Package (조립 전 null) |
| delivery_address_id | string | Order.delivery_addresses 중 하나 참조. **패키지조립agent의 그룹핑 키** |
| location | Location/null | 창고 내 위치, 포장 전까지만 유효. 아래 Location 참고 |
| customer_facing_status | string(enum) | 파생값. item_status를 사용자용으로 매핑. item_delay_reason이 있는 동안(재시도/에스컬레이션 불문)은 출고전게이트가 "지연"으로 덮어씀 |
| policy_version_applied | string/null | v13 신설. 지연 감지 당시 적용 정책 버전 (PackageState 동명 필드와 대칭) |
| last_checked_at | timestamp/null | v13 신설. 출고전게이트 폴링 기록. 지연 이력이 없으면 null |
| retry_count | int | v13 신설. 출고전게이트 self-loop 진입 횟수 |
| escalated | bool | v13 신설. 사람 개입 필요 여부. true여도 백그라운드 자동처리는 계속(비차단) |

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
| escalation_reasoning | string/null | v15 신설. Supervisor(predict_delay_escalation)의 판단 근거 텍스트 — 설명가능성. 해소/지연없음 전이 시 null로 복귀 |
| join_waiting_since | timestamp/null | 패키지 조립 무한대기 방지용 타임아웃 기준. **첫 대기 시각 보존** (재진입 시 덮어쓰지 않음), 봉인 시 null로 복귀 |
| notification_log | list[NotificationEntry] | {stage, sent_at, enabled_at_time} — 판단 아닌 기록 |

### Location (item.location)
| 필드 | 타입 | 비고 |
|---|---|---|
| zone | string | 창고 구역 (A/B/C…) |
| shelf | string | 선반 번호 |
| bin | string | 칸 번호 |

창고처리agent가 값이 없는 item에 기본값 `{zone: A, shelf: 01, bin: 03}`을 채워 넣는다 (센서 조회 placeholder).

### GpsPoint (package.current_gps)
| 필드 | 타입 | 비고 |
|---|---|---|
| lat | float | |
| lng | float | |
| updated_at | timestamp | 이 좌표를 받은 시각 |

조립 시점엔 null. **4단계부터 추적agent가 채운다** — item_status가 "출고됨" 이상으로 전진할 때마다
진행 단계 기반 placeholder 좌표로 갱신 (POC 단순화 5번, 실제 GPS 폴링 아님).

### UserProfile (별도 캡슐, 참조 전용)
| 필드 | 타입 | 비고 |
|---|---|---|
| user_id | string | |
| delivery_addresses | list[Address] | 주소록. [0]이 기본배송지 |
| payment_method | PaymentMethod | 아래 참고 |
| notification_enabled | bool | Order 생성 시 이 값을 복사해 옴 |

### PaymentMethod (userprofile.payment_method)
| 필드 | 타입 | 비고 |
|---|---|---|
| type | string | card / bank_transfer 등 |
| last4 | string/null | 카드 뒷 4자리. 카드가 아니면 null (예: user-002는 bank_transfer라 null) |

주문검증agent는 현재 `payment_status`만 보고 `payment_method`는 검사하지 않는다.

---

## 아직 결정 안 된 것 / 다음에 확인할 것
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
- 출고전게이트가 여전히 창고처리agent 대신 item_status를 직접 확정한다 (POC 단순화 1번) — 창고처리agent
  재진입성 리팩터는 4단계에서도 의도적으로 보류, 다음 단계 후보
- 알림agent 미착수 — notification_enabled 필드는 이미 있음 (notification_log 관련은 아래
  "미구현/죽은 필드 종합" 참고)
- `tracking.py`의 `_SHIP_SEQUENCE`와 `_CUSTOMER_FACING_MAP`은 서로 암묵적으로 동기화돼야 하는
  두 자료구조다 (`_SHIP_SEQUENCE`의 각 값이 `_CUSTOMER_FACING_MAP`의 키와 정확히 일치해야 함).
  지금은 둘 다 4개로 손으로 맞춰놔서 안전하지만, 나중에 배송 단계를 추가하면서 한쪽만 갱신하면
  `_CUSTOMER_FACING_MAP[next_status]`에서 `KeyError`(fallback 없는 직접 subscript)로 즉시 죽는다.
  `list[tuple[str, str]]`(상태, 매핑값) 하나로 합쳐 애초에 동기화 이슈 자체를 없애는 개선안이 있음
- **재고부족이 영구 에스컬레이션되면(`item_delay_reason="재고부족"` + `escalated=True`)
  customer_facing_status가 "지연"인 게 맞는지 재검토 필요.** "지연"은 "곧 온다"는 뜻인데
  영구화된 재고부족은 실서비스라면 품절/취소에 가깝다. 지금은 `_ITEM_RESOLVE_AT_RETRY["재고부족"]=2`라
  이 조합 자체가 구조상 도달 불가능해서(항상 MAX_GATE_RETRIES 이전에 해소됨) 실제 버그는 아니지만,
  나중에 이 경로가 열리면 다시 열어봐야 한다. 논의된 범위:
  - **지연 사유별로 처리가 달라야 한다.** "재고부족"의 영구화만 취소/품절과 자연스럽게 연결된다
    (SKU 자체가 없는 것). "검수불량"/"파손"은 개별 유닛 문제라 다른 유닛 재시도·재입고 대기가
    정상 처리이지, escalated라고 곧장 취소로 보내면 안 된다 — 세 사유를 뭉뚱그려 "escalated=True
    → 취소"로 일괄 처리하면 오히려 새로운 오류가 된다.
  - **기존 `OrderState.cancel_status`(요청됨/처리중/완료/거부됨)는 재사용할 수 없다.** 이건
    "사용자가 취소를 요청하고 그걸 승인/거부하는" 워크플로우용 값이다("거부됨"이 존재한다는 게 그
    증거). 시스템이 재고부족을 감지한 상황엔 요청도 거부도 없다 — Item 레벨에 별개의, 더 단순한
    개념이 새로 필요하다(형태/이름 미정). `CustomerFacingStatus`에도 "취소"(또는 "품절")에
    해당하는 값이 없다.
  - **자동 전이보다 승인 흐름이 맞을 가능성이 높다.** 취소는 환불이 걸린 되돌리기 어려운 액션이라,
    영구화 즉시 자동 확정하기보다 "취소 검토 필요" 같은 중간 신호만 세우고 사람 또는 Supervisor의
    새 decision_type(예: `confirm_item_cancellation`)이 승인하는 흐름이 더 현실적 — `predict_delay_escalation`이
    "비차단이지만 사람 개입 필요"를 다룬 선례를 참고할 수 있다.
  - **데모로 재현하려면 별도 트리거가 필요하다.** `_ITEM_RESOLVE_AT_RETRY["재고부족"]`은 시나리오3/5가
    "정상 해소"를 검증하는 데 쓰고 있어 값을 바꾸면 안 된다 — 이 경로를 실제로 타는 데모를 만들려면
    기존 재고부족과 구분되는 새 신호(예: "완전 단종" 전용 지연 사유나 별도 fixed-mapping)가 필요하다.

## 미구현/죽은 필드 종합

스키마엔 있지만 실제로는 아무도 채우지 않거나, 채워져도 아무도 읽지 않는 필드들. 여러 대화에서
따로따로 발견된 걸 여기 한곳에 모았다 — 새 필드를 스키마에 추가하기 전에 먼저 여기부터 확인할 것.

1. **`ItemStatus`의 `"피킹중"`, `"배송지연"`** — 실제로 이 값을 세팅하는 코드가 어디에도 없는
   죽은 enum 값이다. 창고처리agent는 "대기"→"피킹완료"로 바로 건너뛰고, "배송지연"은 아예 아무도
   대입하지 않는다. 특히 "배송지연"은 이미 `item_delay_reason`(재고부족/검수불량/파손)이 지연
   사유를 표현하고 있어서 중복 개념일 가능성이 있다.
   **구현 시점 예상**: "피킹중"은 창고처리agent 재진입성 리팩터(POC 단순화 1번) 시 진행중 상태
   표시가 필요해지면 채워질 후보. "배송지연"은 item_delay_reason과의 관계를 온톨로지 단계에서
   정리하면서 (별도 값으로 유지할지, item_delay_reason 유무로만 판단하고 아예 제거할지 결정).
2. **`NotificationEntry`(`notification_log`)** — `package_assembly_agent`의 `_new_package`가
   빈 리스트로 초기화만 하고, 실제로 항목을 append하는 코드는 어디에도 없다. 알림agent가
   미구현이라 당연한 결과.
   **구현 시점 예상**: 알림agent 구현 시.
3. **`trace_id`** — 다른 둘과는 성격이 다르다. entry.py가 `uuid.uuid4().hex`로 값 자체는
   채우지만(완전히 죽은 필드는 아님), 그 값을 실제로 참조/활용하는 코드는 어디에도 없다 —
   LangSmith 같은 관측성 연동이 없어서 "쓰기만 하고 아무도 안 읽는" 상태.
   **구현 시점 예상**: 관측성/LangSmith 연동 시.

## 확장 지점 (지금 범위 밖, 문서에만 남김)
- Kafka/Confluent/ClickHouse 등 실제 스트리밍 인프라 — POC에서는 간단한 신호 발생기(`mock_carrier_signal`)로 대체함
- Unity Catalog류 거버넌스 계층 — Neo4j(온톨로지)와는 별개로, 데이터/툴 접근 통제용으로 향후 고려
- 취소 워크플로우 (cancel_requested_at/cancel_status는 필드만 존재, 처리 흐름 미구현)
- 사용자 endpoint "도킹" 개념 (사이트별 프로필 스키마를 표준 캡슐로 변환하는 어댑터) — 현재 기술로 완전 표준화 어려움, 개념만 남김

## 실무 전환 시 고려사항
- `main.py`의 데모 시나리오 9개는 POC 검증용이다. 실제 서비스화 시 `main.py`(순수 진입점)와
  `tests/`(시나리오 이관, pytest 등 정식 프레임워크로) 분리가 필요하다.
