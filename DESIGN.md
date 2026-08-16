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
- [ ] 3단계: 지연체크게이트 (self-loop 패턴)
- [ ] 4단계: 추적agent (범용 이벤트 수신 + 파생값 재계산)

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

5. **Order-Package는 N:M 관계.** 한 주문이 여러 배송지로 쪼개질 수 있고, 여러 주문이 한 패키지로 묶일 수 있음.
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
| 판단 | Supervisor | LLM 판단 | 온톨로지/규칙으로 못 정하는 예외만 처리 (물체 취급주의 판단, 지연 대응 판단 등). 호출 시 decision_type + payload 구조로 여러 판단 종류를 분기 |
| 반복 | 창고처리agent | 조회+액션 (내장 루프) | item_list 순회, Sensor(위치확인)→Action(피킹). 정상 케이스는 온톨로지 조회로 처리, 예외만 Supervisor 호출 |
| 집계 | 패키지조립agent | 조건카운트 | `package_ref`가 없는 item을 `delivery_address_id` 기준으로 묶음. 같은 배송지의 미봉인 패키지가 있으면 합류. required/arrived count 체크, 충족시 봉인+tracking_number 발급. (구 Join노드 흡수) |
| 액션 | 포장agent | 액션 | 포장 완료 처리 (Package 단위 일괄, "포장중" 중간상태는 item 레벨엔 없음) |
| 판단+반복 | 지연체크게이트 | self-loop 조건분기 | 출고전(Item 기반)/배송중(Package 기반) 공용 서브그래프. 외부신호/폴링 기반 지연 감지, 미해소시 자기루프, retry_count 초과시 escalated=true |
| 통합 | 추적agent | 이벤트 수신 + 파생 재계산 | 모든 상태변화 신호(로봇완료, 물류사API, GPS 등) 수신 → 원본 필드 갱신 → 그 자리에서 Order 파생값(internal_order_status, customer_facing_status)도 재계산. (구 이벤트핸들러+상태집계agent 통합) |
| 부가 | 알림agent | 조건부 발송 (비차단) | notification_enabled 확인 후 notification_log에 기록. 워크플로우를 막지 않음 |

**구현 현황**: UserProfile조회 / 주문요청 / 주문검증 / Supervisor(더미) / 창고처리 / 패키지조립 = 구현됨(`logistics_agent/nodes/`).
포장agent · 지연체크게이트 · 추적agent · 알림agent = **설계만 있고 코드 없음**(3~4단계).

### 제거/통합된 것들 (설계 과정에서 폐기 — 이유 포함)
- ~~출고agent~~, ~~배송출발agent~~ → 추적agent로 흡수 (물리적 액션이 아니라 외부 신호 수신이라 판단)
- ~~Join노드~~ → 패키지조립agent 내부 카운트 로직으로 흡수 (동기화→비동기 전환하며 별도 노드일 필요 없어짐)
- ~~주문상태갱신agent~~ → 추적agent로 통합 (이름이 "주문 수정"과 혼동되어 재명명 겸 통합)
- ~~outbound_ready / notification_ready~~ → 불필요 (병렬 Join 자체가 없어지며 무의미해짐)
- ~~송장번호agent~~ → 패키지조립agent 봉인 시점에 추적agent가 함께 처리 (규모상 별도 노드 불필요)
- ~~delay_risk (bool)~~ → 불필요, delay_categories.length > 0 으로 파생 계산

---

## State 스키마 (v12)

> v10 → v11 변경: 배송지 정규화. `Address.address_id` 신설, `UserProfile.delivery_address`/`Order.delivery_address`(단수) → `delivery_addresses`(list),
> `Item.delivery_address_id`(참조) 추가, `Package.delivery_address_id` 추가. 원칙 5(한 주문이 여러 배송지로 쪼개짐)를 스키마로 실제 지원하기 위함.
>
> v11 → v12 변경: **문서에만 있던 중첩 구조를 타입으로 승격.** `Item.location`과 `Package.current_gps`가 코드에선 그냥 `dict`라
> 문서가 명시한 `{zone, shelf, bin}` / `{lat, lng, updated_at}` 구조를 아무것도 강제하지 못했다 → `Location` / `GpsPoint` TypedDict 신설.
> `PaymentMethod`도 표를 만들어 문서화(타입은 이미 있었음). 필드 추가·삭제는 없고 **표현만 정밀해진 변경**이라 실행 결과는 동일.

> GraphState 최상위 키: `user_id` / `confirmed_order_items` / `payment_status_hint`(진입 입력),
> `user_profile`, `order`, **`packages: list[PackageState]`**, `validation_passed` / `validation_errors`, `supervisor_decision` / `supervisor_notes`.
> Package는 Order 안이 아니라 **최상위**에 있다 — 원칙 5(Order-Package는 N:M)를 State 구조로 지킨 것.

### Address (delivery_addresses 원소)
| 필드 | 타입 | 비고 |
|---|---|---|
| address_id | string | v11 신설. `ADDR-HOME` 같은 주소록 id, 또는 주문 시점 신규주소면 `ADDR-{6hex}` 발급 |
| recipient / phone / postal_code / address_line | string | 주문검증agent가 이 4개의 존재 여부를 검사 |

### Order State
| 필드 | 타입 | 비고 |
|---|---|---|
| order_id | string | |
| order_created_at | timestamp | |
| delivery_addresses | list[Address] | 이 주문의 item들이 실제 참조하는 배송지만. UserProfile 주소록 참조 + 주문 시점 신규주소 |
| payment_status | string(enum) | 대기/완료/실패 |
| split_delivery_preference | bool | 생성 시 확정, 이후 불변 (스냅샷 불필요) |
| cancel_requested_at | timestamp/null | |
| cancel_status | string(enum)/null | 요청됨/처리중/완료/거부됨 |
| internal_order_status | string(enum) | 파생값. 최종 소유자는 추적agent(4단계). 현재는 각 노드가 잠정 세팅(검증실패/창고처리중/조립중/출고준비) |
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
| customer_facing_status | string(enum) | 파생값. item_status를 사용자용으로 매핑 |

### Package State
| 필드 | 타입 | 비고 |
|---|---|---|
| package_id | string | |
| source_items | list[SourceItemRef] | {order_id, item_id} — 여러 주문 소속 item 포함 가능 |
| delivery_address_id | string | 이 패키지의 배송지. 미봉인 패키지 재사용 시 매칭 키 |
| required_item_count | int | source_items 개수 |
| arrived_item_count | int | item_status가 피킹완료 이상인 source_item 수 |
| current_gps | GpsPoint/null | 출고 이후에만 채워짐. 조립 시점엔 null. 아래 GpsPoint 참고 |
| tracking_number | string/null | |
| delay_categories | list[string] | 빈 배열=지연없음. 여러 원인 동시 가능 |
| policy_version_applied | string/null | 지연 감지 당시 적용 정책 버전 (역추적/감사용) |
| last_checked_at | timestamp | 모니터링 폴링 기록 |
| retry_count | int | Supervisor 재시도 조치 횟수 (모니터링 횟수 아님) |
| escalated | bool | 사람 개입 필요 여부. true여도 백그라운드 자동처리는 계속(비차단) |
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

**아직 아무도 채우지 않는다** — 4단계 추적agent가 GPS 신호를 받으면서 처음 쓰게 됨. 조립 시점엔 null.

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
- `join_waiting_since` 타임아웃 임계값과 초과 시 조치 — 3단계 지연체크게이트에서 확정 (2단계는 기록만 함)
- 다중 주문 합포장 시 `source_items`의 타 주문 item 조회 경로 — 현재 단일 주문 State 전제라 `_find_item`이 타 주문은 None 반환. 실제 합포장은 주문 간 공유 저장소(또는 온톨로지 조회)가 전제
- `internal_order_status`(조립중/출고준비)를 지금은 패키지조립agent가 잠정 세팅 — 4단계에서 추적agent로 이관 예정
- 지연 카테고리 우선순위 정책(자연재해 > 교통지연 등)의 실제 테이블 구조 — 온톨로지(Neo4j) 단계에서 확정 예정
- 자연재해 지연의 종료 조건 — 외부 재해상태 API 연동 전제, 없으면 사람 확인 fallback
- Supervisor의 여러 decision_type을 어떻게 하나의 노드 안에서 깔끔하게 분기할지 (payload 구조는 정했으나 실제 프롬프트 설계는 미정)
- 온톨로지(Neo4j) 스키마는 "워크플로우가 필요로 하는 만큼만" 상향식으로 만들기로 함 — 아직 미착수

## 확장 지점 (지금 범위 밖, 문서에만 남김)
- Kafka/Confluent/ClickHouse 등 실제 스트리밍 인프라 — POC에서는 간단한 신호 발생기로 대체 예정
- Unity Catalog류 거버넌스 계층 — Neo4j(온톨로지)와는 별개로, 데이터/툴 접근 통제용으로 향후 고려
- 취소 워크플로우 (cancel_requested_at/cancel_status는 필드만 존재, 처리 흐름 미구현)
- 사용자 endpoint "도킹" 개념 (사이트별 프로필 스키마를 표준 캡슐로 변환하는 어댑터) — 현재 기술로 완전 표준화 어려움, 개념만 남김
