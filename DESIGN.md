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
- [x] 3단계: 지연체크게이트 3종 (피킹지연/조립대기/배송중, self-loop 패턴, Item에 retry 필드 추가 v13)
- [x] 4단계: 추적agent (범용 이벤트 수신 + 파생값 재계산) — 선행 조건으로 포장agent도 함께 구현
- [x] 4단계 후속: split_delivery_preference를 패키지조립agent 그룹핑에 실제 반영, 시나리오9로 검증 완료
- [x] 4단계 후속: Supervisor predict_delay_escalation (Google Gemini 실제 호출) 배송중게이트에 통합, 시나리오10 추가
- [x] 4단계 후속: `_PACKAGE_DELAY_SIGNAL` 키를 `delivery_address_id`→`item_id`로 교체(POC단순화2번 해결), 시나리오11 추가
- [x] 4단계 후속: 출고전게이트 → **피킹지연게이트**로 개명 (아래 "이름 변경" 참고)
- [x] 5단계(코드 리뷰): 사람 개입 워크플로우 구체화 설계(도메인 분리 기반, v16 스키마 초안) —
  "사람 개입 워크플로우 구체화" 섹션 참고. **설계만 완료, 코드 미반영** — 그래프 재진입성 포함
  실제 구현은 다음 세션 계획

## 다음에 할 문서 정리 (급하지 않음)
- '확장 지점'과 '아직 결정 안 된 것' 두 섹션의 경계가 모호해지고 있음. 구분 기준(예: 확장지점=외부
  인프라 연동 필요, 아직결정안됨=내부 설계 미결)을 정하고 기존 항목들 재분류 필요
- 노드 목록 표의 Supervisor 행이 두 개념(decide_warehouse_entry, predict_delay_escalation)을
  한 셀에 담아 가독성이 떨어짐, 분리 검토

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
| `{**td, ...}`가 TypedDict에 대입 안 됨 (11곳) | 스프레드가 포함된 dict 표현식은 `dict[str, Unknown]`으로 추론됨 | `cast(OrderState, {**order, ...})`로 통일. 스프레드 자리에만 쓰고, 키를 새로 쓰는 자리(`_new_package`)에는 쓰지 않음 |
| `Address`를 `dict` 파라미터에 못 넘김 | **TypedDict는 `dict[...]`에 대입 불가** (임의 키 추가/삭제가 구조를 깨뜨리므로). 읽기 전용 매핑에만 대입 가능 | `_is_valid_address(address: Mapping[str, object])`. `Address`로 좁히지 않은 이유: 이 함수는 "키 누락"을 검사하는데 `Address`(total=True)는 키가 다 있다고 단언 → 자기모순. 인라인 신규주소는 사용자 입력이라 실제로 키가 빠질 수 있음 |
| `state["order"]` 필수 키 아님 | `GraphState`가 `total=False`(부분 업데이트 반환용) | 코드로는 해결 불가 — `order`를 Required로 만들면 `return {"validation_passed": ...}` 같은 부분 반환이 깨짐. `pyrightconfig.json`에서 `reportTypedDictNotRequiredAccess`만 끔 |

`pyrightconfig.json`에는 `include`(venv 스캔 방지), `venvPath`/`venv`(langgraph import 해석), `typeCheckingMode: standard`(IDE 설정과 무관하게 고정)도 함께 명시했다.
**이 한 규칙 외에 다른 규칙을 끄지 않는다** — 나머지 경고는 실제 문제일 가능성이 높다.

**cast(T, {...})가 정확히 뭘 가려주는지 실험으로 검증함** (4단계 후속). `Item.last_checked_at`(스키마상
`str`) 자리에 `int`를 넣고 Pylance 진단을 비교: `cast`로 감싸면 에러 0건, `cast`를 떼면 즉시 2건
("No overloads for `__setitem__` match", "dict[...]는 Item에 대입 불가"). **"키 오타를 못 잡는다"는
설명은 부정확했다** — 정확히는 `cast(T, expr)`가 `expr` dict 리터럴 전체의 타입 검사를 통째로 끈다
(키 이름·값의 타입·구조 전체 포함). 그런데도 스프레드 자리에서만 이 트레이드오프를 감수하는 이유:
원본 TypedDict가 나머지 필드를 이미 보장하는 반복 패턴이라 사람이 눈으로 훑기 쉽고, 대안(값마다
개별 대입 등)은 코드량이 2~3배로 늘어 오히려 리뷰하기 어려워지기 때문. 자세한 규칙은 CLAUDE.md 참고.

## 3단계 실행 결과 요약

세 게이트를 `창고처리agent → 피킹지연게이트 → 패키지조립agent → 조립대기게이트 → 배송중게이트`
순서로 파이프라인에 삽입했다. 셋 다 "미해소면 자기 자신으로 self-loop, `retry_count`가
`MAX_GATE_RETRIES`(3)를 넘으면 `escalated=True`로 표시하고 (비차단으로) 다음 단계 진행"이라는
동일한 뼈대를 재사용한다. 데모 시나리오(main.py 4~7번)로 확인한 결과:

- 시나리오4 (정상 통과): 지연 없는 주문 → 세 게이트 모두 self-loop 없이 1회 통과, `retry_count` 전부 0
- 시나리오5 (재시도 후 통과): 재고부족 item이 피킹지연게이트에서 2회 재시도 후 해소(`item_delay_reason=None`,
  `item_status="피킹완료"`) → 정상 봉인 → 배송중게이트에서 해당 배송지(ADDR-OFFICE)의 "교통지연"이
  1회 재시도 후 해소(`delay_categories=[]`)
- 시나리오6 (재시도 초과 에스컬레이션 — 연쇄): "파손"은 데모 매핑상 재시도로 해소되지 않도록 설계 →
  피킹지연게이트가 3회 재시도 후 4번째 진입에서 item `escalated=True` → item은 끝내 피킹되지 않아
  패키지도 `required=1, arrived=0`으로 영원히 미봉인 → 조립대기게이트도 3회 재시도 후 package
  `escalated=True`. 게이트1의 미해소가 게이트2의 에스컬레이션으로 그대로 이어지는 연쇄를 확인함
  (패키지가 미봉인 상태라 배송중게이트에는 아예 도달하지 않음 — 대상 필터가 `tracking_number is not None`이라 자연 스킵)
- 시나리오7 (즉시 에스컬레이션): 자연재해 신호는 재시도 없이 최초 진입에서 바로
  `escalated=True`(`retry_count=0` 그대로) — "재시도 초과형"과 "즉시형" 두 에스컬레이션 트리거가
  서로 다른 코드 경로임을 확인함

**설계 결정 — 조립대기게이트는 순수 워처.** 처음엔 게이트2가 스스로 "지연 아이템 도착"을 흉내 내고
패키지조립agent로 되돌아가 재봉인시키는 2노드 사이클 안도 검토했으나, 그러면 게이트2만
다른 두 게이트와 형태가 달라진다(진짜 self-loop가 아니라 게이트↔조립agent 사이클). 대신
조립대기게이트는 미봉인 Package를 감시만 한다 — `tracking_number` 유무만 확인하고, 스스로는
아무것도 해소하지 않는다. 그 결과 세 게이트가 완전히 동일한 "단일 노드 self-loop" 형태를 유지한다.

**해소 판정은 전부 데모용 고정 매핑.** 실제 외부신호(재고센서, 물류사 API) 대신
`item_delay_reason`별 해소 시점(`_ITEM_RESOLVE_AT_RETRY`), `item_id`별 지연신호
(`_PACKAGE_DELAY_SIGNAL`)를 고정 딕셔너리로 뒀다. `package_id`는 uuid라 데모 스크립트가 사전에
못 박을 수 없어서, 배송중게이트의 매핑 키만 `package_id` 대신 `item_id`를 썼다(처음엔
`delivery_address_id`를 썼다가 문제가 발견돼 교체함 — 상세: 아래 POC단순화 2번) —
실제 구현이라면 패키지 자체의 속성(현재 위치, 배송 경로 등)으로 신호를 조회하겠지만 POC 범위 밖.

**타임아웃은 실제 경과시간이 아니라 재시도(틱) 횟수로 근사.** `join_waiting_since`는 여전히
최초 대기 시각을 보존하는 기록 필드로 남아있지만(원칙3), 조립대기게이트의 판단 자체는
`retry_count`(self-loop 진입 횟수)로 한다 — 동기 실행되는 POC 데모에서 실제 벽시계 시간 경과를
재현할 방법이 없기 때문. `retry_count`가 판단, `join_waiting_since`가 증거 기록이라는 역할
분리가 원칙3을 그대로 따른다.

### POC 단순화 사항 (4단계 이후 재검토 필요)

3단계 구현 과정에서 "지금 범위에서 굳이 풀 필요 없다"고 접어둔 것들. 나중에 4단계(추적agent)나
실제 온톨로지/외부 신호 연동을 붙일 때 다시 열어봐야 한다.

1. **피킹지연게이트가 창고처리agent 대신 item_status를 직접 갱신한다.** 원래 "피킹 완료" 전이는
   창고처리agent의 역할인데, 창고처리agent는 `current_item_index`를 이미 `len(item_list)`까지
   진행시켜버려서 재호출해도 스킵된 item을 다시 볼 방법이 없다 (2단계 코드 그대로 재사용).
   그래서 피킹지연게이트가 해소를 확인하는 김에 `item_status="피킹완료"`/`customer_facing_status="준비중"`
   확정까지 직접 떠맡았다 — 관측(판단)과 액션(피킹 확정)이 한 노드에 섞인 상태.
   4단계에서 창고처리agent가 "지연 해소된 item만 재피킹"할 수 있게 재진입 가능해지면,
   피킹지연게이트는 다시 순수 판단(해소 여부 체크)만 하고 액션은 창고처리agent로 돌려줘야 한다.
   **(4단계 착수 시점에 재확인 — 이번 범위에서는 그대로 보류하기로 결정.** 추적agent 작업과
   결합할 이유가 없어 별도 리팩터로 남겨둠.)
2. **[해결됨] 배송중게이트의 지연 감지가 실제 물류 신호가 아니라 고정 매핑
   (`_PACKAGE_DELAY_SIGNAL`)이다.** 원래는 패키지 자체 속성(현재 위치, GPS, 배송 경로 등)이나
   물류사 API/GPS 폴링으로 지연을 감지해야 하는데, `package_id`가 데모 시점에 미리 알 수 없는
   uuid라 데모 스크립트가 통제 가능한 값으로 대신 키잉해야 했다. 온톨로지(Neo4j) 단계에서
   실제 지연 신호 조회 경로가 생기면 이 고정 매핑 자체는 여전히 대체해야 함 — 여기서 "해결됨"은
   매핑을 없앴다는 뜻이 아니라, 매핑의 **키 선택**이 만들던 부작용 하나를 고쳤다는 뜻이다.

   **발견한 문제**: 처음엔 키를 `delivery_address_id`로 썼다. 그런데 같은 배송지로 가는
   패키지가 둘 이상이면(예: `split_delivery_preference=true`로 쪼개진 경우, 또는 그냥 서로
   다른 주문이 같은 배송지를 우연히 공유하는 경우) 그 패키지들이 전부 같은 지연 판정을
   공유해버렸다 — 실제로는 트럭/배송 경로가 다른 별개의 패키지인데도. 이 부작용이 실제로
   시나리오3에서 조용히 발생하고 있었다: 시나리오3의 `ADDR-OFFICE` 패키지(SKU-003/SKU-004,
   본래 이 시나리오는 재고부족 해소만 검증하려던 것)가 시나리오5 전용으로 만든 신호
   (`ADDR-OFFICE` → 교통지연)를 의도치 않게 그대로 물려받아 배송중게이트에서 재시도·해소를
   거쳤다 — 주소가 같다는 이유만으로 서로 무관한 두 시나리오가 결합돼 있었던 것.
   시나리오9(`split_delivery_preference=true`, 배송지 `ADDR-HOME` 공유)는 이 부작용이 드러날
   수 있는 조합이었지만, `ADDR-HOME`엔 애초에 등록된 지연 신호가 없어서(둘 다 `categories=[]`)
   증상이 관측된 적은 없었다.

   **수정**: 키를 `delivery_address_id`에서 `item_id`로 바꿨다. `item_id`도 `package_id`처럼
   데모 스크립트가 미리 정하는 값이지만(주문 시점에 이미 확정), 배송지와 달리 여러 패키지가
   같은 값을 공유할 이유가 구조적으로 없다 — item과 package는 다대일이지만 그 반대(한 item이
   여러 package에 걸침)는 없기 때문. 룩업은 `_lookup_package_delay_signal()`이
   `pkg["source_items"]`(이미 스키마에 있던 필드, 신규 필드 없음)를 순회해 매칭되는 `item_id`를
   찾는다.
   **새 시나리오11**(같은 배송지 `ADDR-HOME`, `split_delivery_preference=true`로 쪼갠 두
   패키지에 서로 다른 지연 신호(`SKU-501`=교통지연/`SKU-502`=자연재해)를 부여)로 두 패키지가
   실제로 독립적인 지연 판정을 받는 것을 확인했다 — 한쪽은 1회 재시도 후 해소, 다른 쪽은 즉시
   에스컬레이션. 기존 시나리오3/5/6/7/9/10 전체 재실행으로 회귀 확인 완료 — 유일한 차이는
   시나리오3의 `ADDR-OFFICE` 패키지가 더 이상 시나리오5의 신호를 잘못 물려받지 않는다는 것
   (원래 시나리오3의 의도였던 재고부족 해소 검증 자체는 그대로 통과).

   **부가 발견 — dead code 확인**: `in_transit_delay_gate`의 "지연이 사라지는" 분기
   (`if not categories: if pkg["delay_categories"]: ...`)는 현재 코드에서 도달 불가능(dead code)함을
   실측으로 확인함(임시 프로브 삽입 후 시나리오 1~11 전체 실행, 단 한 번도 히트 안 됨). 원인은
   `_lookup_package_delay_signal()`이 고정 딕셔너리(`_PACKAGE_DELAY_SIGNAL`)와 패키지 봉인 시점에
   고정되는 `source_items`만으로 결정되는 순수함수라, 한 번 반환된 `categories` 값이 그 패키지에
   대해 절대 바뀌지 않기 때문 — "이전 틱엔 지연이 있었는데 이번 틱엔 사라졌다"는 상황 자체가
   논리적으로 발생할 수 없다(실제 지연 해소는 이 분기가 아니라 바로 아래 `resolve_at`/`retry_count`
   기반 분기가 전담). 버그는 아니다 — 실제 물류사 API/GPS 폴링으로 교체되면(외부 시스템이
   `resolve_at` 카운터와 무관하게 스스로 신호를 거둬들이는 경우 대비) 살아나는 방어 코드로
   의도적으로 남겨둔다.
3. **조립대기게이트/배송중게이트가 실제 경과시간이 아니라 `retry_count`(self-loop 진입 횟수,
   즉 "틱")를 기준으로 판단한다.** `join_waiting_since`(조립대기)는 최초 대기 시각을 기록만 할 뿐
   실제 타임아웃 판정에는 관여하지 않는다. 동기 실행되는 POC 데모에서는 벽시계 시간이 흐르지
   않아 tick 수로 대체할 수밖에 없었음 — 실제 서비스라면 폴링 주기 × 경과 tick 환산이나
   `datetime.now() - join_waiting_since`와 임계값 비교로 바꿔야 한다.
4. **추적agent가 봉인된 패키지들을 lockstep으로 함께 전진시킨다.** 피킹지연게이트가 패키지조립agent
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
   단계에서 enum 재설계와 함께 다시 열어봐야 한다. **(5단계 후속: 더 이상 이론상의 gap이
   아니다 — "사람 개입 워크플로우 구체화" 설계(아래)에서 품목 단위 취소가 실제로 이 조합을
   만들어내므로, "부분배송중"류 값 추가가 그 설계의 일부로 필요해졌다.)**

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
  피킹지연게이트에도 붙이지 않았다(범위를 좁게 유지).
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
- **"남은 재고부족 item 수" 신호는 구조상 대부분 0으로 읽힌다.** 피킹지연게이트가 패키지조립agent
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

### Gemini 모델 교체 (gemini-3.6-flash → gemini-3.5-flash-lite) + RPM 안전장치 추가

**이전 세션에서 RPM 6 / RPD 27 한도로 실행이 중단된 적이 있었다.** 다만 그 시점의 정확한
에러 메시지(할당량 종류가 RPM이었는지 RPD였는지를 구분해주는 `quota_metric`/`retry_delay`
필드 등)는 세션 경계를 넘기며 재구성이 불가능했다 — 어느 로그 파일에도, DESIGN.md에도, 대화
기록에도 원문이 남아있지 않았다. **교훈: 재현 어려운 외부 API 에러 메시지는 발생 즉시 파일로
남기거나 이 문서에 그대로 옮겨 적어야 한다** — "나중에 기억해서 정리하면 된다"가 세션 경계
앞에서는 성립하지 않는다.

**대응 1 — 모델 교체.** `gemini-3.6-flash` → `gemini-3.5-flash-lite`. 이 프로젝트가
Gemini에게 요구하는 작업(`SupervisorPrediction` 구조화 출력 하나, 입력 신호 4개, 판단
1~2문장)은 복잡한 추론이 아니라 단순 분류에 가까워 `flash-lite`급으로 충분하다고 판단했고,
무료 티어에서 더 가벼운 모델일수록 RPM/RPD 여유가 나은 경향이 있어(정확한 수치는 계정별로
달라 AI Studio 대시보드에서 직접 확인 필요 — https://aistudio.google.com → 좌측 "Usage and
billing" 또는 API 키 관리 화면에서 모델별 RPM/RPD/TPM을 확인할 수 있다) 교체했다.

**검증**: 시나리오10(주문 10일 경과, retry_count=0인 첫 틱)을 `gemini-3.5-flash-lite`로 격리
재실행 — `escalate_now=True`, reasoning="주문 생성 이후 이미 240시간이 경과하여 단순한
교통 지연으로 보기에는 지연 시간이 지나치게 길어졌으므로 즉시 담당자 개입이 필요합니다."
`gemini-3.6-flash` 때의 판단(escalate_now=True, "240시간이 지난 상황으로... 즉시 담당자
확인 및 에스컬레이션이 필요")과 판단/근거 품질 모두 동등한 수준임을 확인했다. (단, 이것도
시나리오10 자체가 원래 비결정론적이라 한 번의 관측일 뿐이라는 한계는 동일하게 적용된다.)

**대응 2 — RPM 안전장치를 모델과 무관하게 추가.** `supervisor.py`에 `_throttle_gemini_call()`을
신설해 `predict_delay_escalation`이 실제로 호출되기 직전에 항상 거친다. 직전 호출 시각을
모듈 전역(`_last_call_at`)에 기록해두고, 이번 호출이 `GEMINI_RPM_LIMIT`(env var, 기본 6)로
정한 최소 간격보다 일찍 들어오면 그 차이만큼 `time.sleep`으로 대기한다. 모델별 실제 한도를
조회해 정교하게 맞추기보다 보수적인 고정값을 기본으로 둔 이유는, 이 안전장치의 목적이
"어떤 모델을 쓰든 RPM 초과로 세션이 끊기는 사고를 재발시키지 않는 것"이지 처리량 최적화가
아니기 때문 — `GEMINI_MODEL`과 같은 패턴으로 env var화해뒀으니 실제 한도를 확인한 뒤 더
여유 있게(예: 대시보드에서 RPM 15로 확인되면 `GEMINI_RPM_LIMIT=15`) 조정할 수 있다.
**검증**: `predict_delay_escalation`을 프로세스 안에서 연속 2회 직접 호출 — 1차 호출
2.6초, 2차 호출은 요청 전 7.4초를 대기해 두 호출 간격을 정확히 10초(=60s/6RPM)로 맞추는
것을 확인했다. `main.py` 시나리오 1~11 전체 재실행 — 시나리오1(의도된 검증실패) 외 에러
없음, 시나리오5/10/11의 실제 Gemini 호출 3건 모두 정상 응답(시나리오10은 여기서도
`escalate_now=True`로 동일 판단). 특히 시나리오5→10 사이에서 안전장치가 실전 파이프라인
안에서도 자연 발동(대기=7.5s)하는 것까지 확인했다 — 별도 스트레스 테스트가 아니라 평소
데모 실행 흐름에서도 실제로 걸린다는 뜻.

### 이름 변경: 출고전게이트 → 피킹지연게이트

`outbound_delay_gate`(출고전게이트)라는 이름이 실제 역할보다 넓게 들린다는 지적이 나와 검토했다.

**문제**: "출고전"(pre-dispatch)은 "아직 출고되지 않은 모든 단계"를 아우르는 것처럼 들리지만,
실제 이 게이트가 체크하는 건 `item_delay_reason`(재고부족/검수불량/파손) 하나뿐이다 —
전부 **피킹 단계에서 실패하는 사유**다. 그래프 상 위치도 창고처리agent(피킹) 바로 다음,
패키지조립agent 바로 전으로 고정돼 있어서 "출고전"이 암시하는 더 넓은 범위(예: 포장 단계
이슈)를 실제로 커버할 여지가 구조적으로 없다 — 이 자리는 오직 피킹 지연만 체크하는 자리다.
형제 게이트인 조립대기게이트/배송중게이트는 이미 "지금 무슨 상태를 감시하는가"를 이름에
직접 담고 있는데(조립대기 = 미봉인 패키지 상태, 배송중 = 봉인 후 이동 상태), 출고전게이트만
"단계 이전"이라는 시점 표현을 쓰고 있어 형제 게이트들과도 이름 짓는 방식이 어긋나 있었다.

**결정**: `outbound_delay_gate` → `picking_delay_gate`(피킹지연게이트)로 개명.
`route_after_outbound_gate` → `route_after_picking_gate`도 함께. 로직 변경은 없음 —
순수 리네이밍이라 이 문서의 이후 서술에서도 전부 새 이름으로 통일한다(과거 시점을 서술하는
문장도 포함 — 코드에 더 이상 존재하지 않는 옛 이름을 문서에 남겨두면 나중에 grep했을 때
혼란만 남기기 때문).

**검증**: `pyright` 0 errors. 시나리오 1~11 전체 재실행, 정규화 diff로 회귀 없음 확인.

### 버그 수정: 피킹지연게이트가 지연 중에도 customer_facing_status를 안 바꾸던 gap

`item_delay_reason`이 있는 동안(재시도 중이든, 영구 에스컬레이션됐든) `customer_facing_status`가
계속 `"주문접수"`에 머물러 있던 걸 발견했다 — entry.py가 준 초기값이 한 번도 안 바뀐 채였다.
재고부족으로 재시도 중이든 파손으로 영구 에스컬레이션됐든 사용자 화면에는 아무 신호가 안 갔다는 뜻.

**다른 항목들과 다르게, 발견 즉시 고쳤다.** 위의 "POC 단순화 사항"이나 "아직 결정 안 된 것"에
쌓여있는 항목들은 대부분 POC 범위에서 의도적으로 접어둔 것들(실제 인프라 부재, 데모 데이터 한계
등)이라 문서화만 하고 다음 단계로 미뤄도 되는 것들이었다. 이건 성격이 다르다 — 의도한 단순화가
아니라 그냥 놓친 코드였고, 사용자에게 실질적으로 잘못된 정보(지연되고 있는데 "주문접수"로만
보임)를 노출하는 gap이라 판단을 미룰 이유가 없었다.

- **수정**: `picking_delay_gate`의 재시도/에스컬레이션 분기(`delay_gates.py`)에
  `"customer_facing_status": "지연"`을 추가. 해소 시 기존처럼 `"준비중"`으로 복귀하는 로직은
  그대로 뒀다.
- **검증**: `picking_delay_gate`를 격리 호출해서 재고부족(해소되는 케이스)과 파손(영구
  에스컬레이션되는 케이스) 둘 다 틱 단위로 확인 — 재시도 중엔 `"지연"`, 해소되면 `"준비중"`으로
  정확히 전이했고, 에스컬레이션된 뒤에는 더 이상 갱신되지 않으므로(에스컬레이션된 item은
  `picking_delay_gate`가 다음 틱부터 건너뜀) `"지연"`이 그대로 유지되는 것도 확인했다 — 이건
  의도한 동작이다(더 이상 자동으로 바뀔 이유가 없는 최종 신호). 시나리오3/5/6 전체 재실행으로
  회귀 없음도 확인.

### 발견된 gap: item_id 중복 시 패키지 봉인이 오염됨 (검증 가드로 임시 대응)

5단계(코드 리뷰 단계, 새 기능 없음)에서 assembly.py를 검토하며 "같은 item_id를 가진 item이
2개면 어떻게 되는가"를 실제로 재현해봤다 — 실제로 뒤섞인다는 것을 확인했다.

**재현**: 같은 배송지에 item_id가 같은 item 2개를 주문 — 하나는 정상 피킹, 하나는
`item_delay_reason="파손"`(재시도로도 해소 안 되는 사유 → `picking_delay_gate`가 3회 재시도 후
`escalated=True`로 영구 확정, 끝까지 피킹되지 않음). 파이프라인을 끝까지 통과시키니 파손된
(한 번도 피킹된 적 없는) item이 `item_status="배송완료"`와 `escalated=True`를 동시에 가진
자기모순 상태로 끝까지 진행됐다.

**원인**: `assembly.py`의 `_find_item()`이 `SourceItemRef → Item` 역참조를 `item_id` 하나로만
한다(`next(item for item in item_list if item["item_id"] == ref["item_id"])`). item_id가
유일하지 않으면 어떤 ref든 항상 리스트에서 "처음 매칭되는" item으로 해석돼버린다. 이 때문에
`arrived_item_count` 계산에서 파손 item의 ref가 정상 item의 "피킹완료" 상태를 대신 물려받아
`required==arrived`로 오판 → 조기 봉인. 일단 봉인되면 두 item이 같은 `package_ref`를 공유하므로
추적agent/`mock_carrier_signal`의 lockstep 전진(원칙1에 따라 의도된 동작 — POC 단순화 4번)이
파손 item까지 그대로 끌고 가 "배송완료"까지 도달시킨다. (`_lookup_package_delay_signal`
(delay_gates.py)은 고정 딕셔너리를 item_id로 조회만 하므로 중복이 있어도 데이터가 섞이지는
않음 — 문제는 assembly.py에 국한됨.)

**판단 — 근본 해법(item_id와 분리된 `order_item_id` 도입)은 지금 범위에서 보류한다.**
"같은 상품을 여러 개 주문"을 이 POC가 검증해야 할 핵심 시나리오로 볼 근거가 없다 — State 설계
6원칙 어디에도 이 축은 없고, 지금까지의 데모 시나리오 11개도 전부 item_id 유일성을 전제로 짜여
있다. 이 gap은 "새 기능이 빠진 것"이 아니라 "이미 전제하고 있던 불변조건(item_id는 주문 내에서
유일하다)이 입력 단계에서 강제되지 않은 것"에 가깝다 — item_list에 quantity 필드가 없는 지금
데이터 모델 자체가 "item 1행 = 물리적 유닛 1개"를 뜻하므로 item_id는 원래도 유일해야 맞다.
`order_item_id`를 새로 신설하는 건 "item_id는 SKU/상품코드, order_item_id는 유닛 식별자"로
개념을 쪼개는 모델링 결정이라 더 큰 설계 논의가 필요하고(예: entry.py가 호출자 입력과 무관하게
항상 자체 유일 id를 발급하는 방향과, item_id를 남겨두되 매칭 키만 바꾸는 방향은 서로 다른
결정), 지금 이 POC의 목적(핵심 패턴 시연)에 필요한 확장이 아니라고 판단했다.

**대신 관문에서 막는다.** `order_validation_agent`에 item_id 중복 검사를 추가했다 — "주소록에
없는 delivery_address_id"를 이미 여기서 걸러내던 것과 대칭 구조. 데모 시나리오 11개는 전부
item_id가 유일해서 회귀 없음.

**나중에 다시 열어볼 조건**: "수량>1로 같은 상품을 여러 개 주문"이 실제로 이 프로젝트의 핵심
시나리오가 되는 시점(예: 온톨로지 단계에서 실제 커머스 데이터를 다루게 될 때) — 그때
`order_item_id` 신설 여부를 다시 검토한다.

### 발견된 gap: 패키지조립agent의 "합류" 로직이 지금 구조상 dead code

assembly.py를 검토하며 "같은 배송지의 미봉인 패키지가 있으면 합류"(`origin="합류"`) 분기가
실제로 발동하는 입력이 있는지 확인했다 — **없다. 지금 그래프 구조에서는 발동이 원천적으로
불가능하다.** 11개 데모 시나리오 전체 재실행(그룹 생성 15건)으로도 전부 `(신규)`였고
`(합류)`는 0건이었지만, 이건 우연이 아니라 구조적으로 증명된다:

1. `package_assembly_agent`는 주문당 정확히 1회만 실행된다 — graph.py에서 들어오는 edge는
   `picking_delay_gate`의 `proceed` 분기 하나뿐이고 되돌아오는 edge가 없다(다른 호출부도 없음).
2. 이 노드 이전의 어떤 노드도 `packages` state 키를 채우지 않는다 — 이 함수가 시작되는
   시점에 `packages`는 항상 빈 리스트다.
3. `app = build_graph()`가 checkpointer 없이 compile돼(`graph.py`) `app.invoke()` 호출
   간에 state가 전혀 이어지지 않는다. 여러 주문의 item이 한 실행 안에서 함께 처리되는
   경로도 없다 — `GraphState.order`가 애초에 단수 필드.
4. (non-split 케이스에 한해) `groups` dict가 같은 `address_id`의 item을 애초에 한 그룹으로
   묶어버려서, 한 번의 호출 안에서 같은 주소가 두 번 처리될 일도 없다.

즉 "합류"가 발동하려면 이 함수가 시작하는 시점에 이미 `packages`에 해당 배송지의 미봉인
패키지가 들어있어야 하는데, 위 네 조건이 겹치면 그런 입력 자체가 존재할 수 없다 — 지금
시나리오뿐 아니라 앞으로 어떤 입력을 넣어도 마찬가지다.

**완전히 폐기 확정은 아니다 — 코드는 지우지 않고 그대로 둔다.** `split_delivery_preference`를
지금처럼 주문 시점의 사전 선택(bool)이 아니라 "지연/재고부족 등 상황이 실제로 발생했을 때
사람이 개입해서 그 자리에서 분리배송 여부를 정하는" 방식으로 재설계하는 안이 논의 중이다.
이 방향으로 가면 `package_assembly_agent`가 재진입 가능해져야 한다(사람 개입 시점에 이미
일부 item은 패키지에 배정된 채로 대기 중이고, 나머지 item이 나중에 도착하며 그 미봉인
패키지에 합류해야 하는 상황이 실제로 생김) — 그때 "합류" 로직이 이름 그대로 다시 필요해질
수 있다. 3단계에서 조립대기게이트를 "순수 워처"로 만들며 함께 기각했던 재진입 경로가, 이
경로(사람 개입 재설계)를 통해 다른 이유로 다시 열릴 가능성이 있는 셈 — 그때까지는 죽어있는
채로 남겨둔다. **(5단계 후속: 이 방향이 "사람 개입 워크플로우 구체화"(아래) 설계로
구체화됐다 — `split_delivery_preference` 자체는 폐기되고 `fulfillment_preference_on_delay`로
대체되지만, 여기서 예고한 재진입성 필요는 그대로 유효하다. 품목 단위 취소가 확정되면
`package_assembly_agent`가 줄어든 required count로 재봉인해야 하므로, "합류" 로직이 다시
필요해지는 경로는 이쪽이다.)**

### Package 봉인 메커니즘

Package 봉인(`tracking_number` 발급)은 피킹지연게이트가 원인을 제거하면, 그 결과
(`item_status`)를 `package_assembly_agent`가 참조해서 봉인 여부를 판단하는 식으로 이루어진다.

다만 "새로 해소된 item을 반영해 봉인"하는 형태로 일어나려면 `package_assembly_agent`가
다시 호출돼야 한다. 이번 리뷰에서 확인한 바로는 현재 구조상 이 노드는 주문당 정확히 1회만
실행되고, 그 재진입 경로 자체가 없다 — "합류" 로직이 dead code인 것과 원인이 같다(위
"발견된 gap: 패키지조립agent의 '합류' 로직이 지금 구조상 dead code" 참고).

지금 데모 시나리오들이 이 문제를 겪지 않는 이유는 파이프라인 순서(`창고처리agent →
피킹지연게이트 → package_assembly_agent`) 덕분이다 — 피킹지연게이트의 self-loop가 모든
item의 지연을 이미 완전히 해소/에스컬레이션한 **뒤에야** `package_assembly_agent`로
넘어가므로, 이 노드는 자신이 실행되는 단 한 번 안에서 이미 최종 확정된 상태를 보고 봉인
여부를 판단한다. 즉 지금은 "재호출로 새 해소를 반영"하는 게 아니라 "피킹지연게이트가
전부 끝난 뒤에 package_assembly_agent가 정확히 한 번 실행"되는 구조라 우연히 문제가
안 드러난다.

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

### 사람 개입 경로의 구조적 한계

지금까지 "escalation"이라는 한 단어가 서로 다른 세 가지를 뭉뚱그려 가리키고 있었다. 구분한다:

- **`escalated`** — State 필드명. "재시도 한도를 넘었다/조기 신호가 있었다"는 **현재 상태**를
  기록하는 값일 뿐, 그 자체로는 행위가 아니다.
- **판단(decision)** — Supervisor가 상황을 보고 어떻게 대응할지(지금 `escalated`로 표시할지,
  계속 재시도할지) **정하는 것**. `decide_warehouse_entry`/`predict_delay_escalation`이 하는
  일이 정확히 이것.
- **개입(intervention)** — 사람이 **이미 진행 중인 자동 판단/처리에 끼어들어** 방향을 바꾸거나
  멈추는 것. 판단과는 다른 행위다 — 판단은 시스템이 스스로 내리는 것이고, 개입은 외부(사람)가
  그 결과에 손을 대는 것.

**대응 경로도 이 구분을 따라 둘로 나뉜다:**

- **경로A — Supervisor 판단(자동)**: `predict_delay_escalation`이 신호를 보고 `escalate_now`를
  정하고, 결과를 `escalated`/`escalation_reasoning`에 기록한다. 전부 그래프 실행 안에서 동기적·
  비차단으로 일어난다 — `escalated=True`가 돼도 배송은 계속 진행된다(`PackageState.escalated`
  필드 주석의 "비차단" 원칙).
- **경로B — 사람 개입**: 경로A가 이미 만들어놓은 판단 결과(`escalated=True` + `escalation_reasoning`)를
  사람이 **나중에** 검토해서 그 판단을 **유지/변경/확정**하는 것. "처음부터 사람이 판단한다"가
  아니라 **"이미 내려진 판단에 개입한다"**는 구조 — Supervisor가 먼저 뭔가를 정해놓고, 사람은
  그 결정을 승인하거나 뒤집는 역할만 한다.

지금 구현된 건 경로A뿐이다. 경로B는 완전히 미구현이다 — `escalated=True`가 세팅된 뒤 사람이
그걸 어떻게 보고 어떻게 처리를 확정하는지는 시스템 어디에도 없다("재고부족 영구 에스컬레이션 =
취소" TODO가 경로B가 실제로 필요해지는 구체적 사례).

**Supervisor 판단 자체가 실패하는 경우도 "개입"이 아니라 "판단 실패"다.**
`predict_delay_escalation`이 LLM 호출에 실패하면(키 누락/네트워크 오류) 지금은
`escalate_now=False`로 폴백한다. 이건 판단 실패이지, 사람이 개입한 것도 Supervisor가 "지켜봐도
된다"고 정상 판단을 내린 것도 아니다. 그런데 지금 코드는 이 둘을 구분하지 않는다 —
`SupervisorPrediction(escalate_now=False, reasoning="LLM 호출 실패...")`이 정상 판단과 똑같은
모양으로 반환돼서, 호출자(배송중게이트)는 "정상적으로 지켜봐도 된다는 판단"과 "판단 자체가 안
내려진 것"을 구분할 수 없다(`reasoning` 텍스트에 실패 사실이 남아 로그로는 보이지만, 타입/필드로
구분되진 않는다). **판단 실패는 그 자체로 경로B(사람 개입)로 이어져야 하는 트리거**인데, 지금은
둘 다 같은 값으로 게이트를 그냥 통과시켜버린다.

**사람 개입 워크플로우가 별도 진입점이어야 하는 구조적 이유**: 이 파이프라인은 `app.invoke()`
한 번으로 동기 실행된다 — 그래프 노드는 실행 도중 "사람이 승인할 때까지 멈춰서 기다리기"를 할
수 없다(POC뿐 아니라 실제 서비스에서도, 그래프 실행을 사람 응답 대기로 블로킹하는 건 일반적으로
맞지 않는 설계). 판단(경로A)은 자동화 가능한 로직이라 그래프 실행 흐름 안에 자연스럽게 들어가지만,
개입(경로B)은 그래프 노드로 표현될 수 없다 — 사람이 검토하는 시점은 그래프 실행 시점과 무관하게
(몇 시간 뒤, 며칠 뒤) 일어난다. `escalated=True`로 마킹된 상태가 영속화되고, 그래프 바깥의
**완전히 별도의 진입점**(관리자 UI, CS 티켓 시스템, 별도 API 등)이 그 상태를 읽어 사람의 결정을
다시 State에 반영하는 구조여야 한다. 즉 경로B는 "배송중게이트 안에 또 하나의 분기"로 만들 수
있는 게 아니라, 이 그래프와는 완전히 별도로 설계해야 하는 컴포넌트다.

### 지연 사유의 세 계층 — 새 decision_type 후보

`delay_gates.py`를 검토하다가 "지연 사유"라고 뭉뚱그려 부르던 것이 실제로는 대응 방식이
완전히 다른 세 계층이라는 걸 발견했다:

1. **결정화된 규칙** (재고부족/검수불량 등) — 해소 시점이 경험적으로 고정 가능한 예외.
   고정 딕셔너리(`_ITEM_RESOLVE_AT_RETRY`)로 처리. Supervisor(판단)가 필요 없다 — 위
   "'재고부족' 개념의 세 가지 층위"의 층위2와 같은 것.
2. **예측 영역** (교통지연 등) — 정상적인 지연이지만 해소 시점이 불확실해서 규칙표로 못
   박기보다 예측이 맞는 영역. `predict_delay_escalation`이 담당.
3. **정상 흐름 자체가 깨지는 재난/예외 상황** (전쟁, 대규모 재해 등) — 위 둘과 근본적으로
   다르다. 고정 딕셔너리에 미리 등록하는 방식 자체가 안 맞는다 — 이런 사유는 애초에 전부
   나열할 수 없고, 나열을 시도하는 것 자체가 잘못된 전제다. "등록 안 된 사유를 만나면
   자동으로 사람 개입 경로(위 "사람 개입 경로의 구조적 한계" 참고, 경로B — 지금은 미구현)로
   넘기는 fallback"이 필요하다는 뜻.

   **별도 decision_type 후보로 남겨둔다: `assess_disruption_severity`(가칭).**
   `predict_delay_escalation`과 목적이 다르다 — 후자는 "정상적인 지연이 언제 해소될지"를
   예측하는 것이고, 이건 **"정상 흐름 자체가 지금도 유효한 전제인지"를 재판단**하는 것이다.
   같은 Supervisor 개념 아래 있어도 입력·출력·트리거 시점이 다른 별개의 판단이라 기존
   decision_type에 욱여넣지 않는다 — "아직 결정 안 된 것"의 "decision_type이 늘어나면 이
   패턴이 계속 맞을지 다시 볼 것"이 예고했던 바로 그 확장 사례.

   지금 `_PACKAGE_DELAY_SIGNAL`의 `"자연재해"`는 사실 이 계층3에 속하는데, 아직 fallback이
   없어서 계층1처럼 고정 딕셔너리에 미리 등록해두고 즉시 에스컬레이션시키는 방식으로
   임시 처리돼 있다(시나리오7/11) — 임시 처리가 지금까지는 통했던 이유는 데모가 "어떤 재난이
   일어날지"를 미리 알고 스크립트를 짜기 때문이지, 실제로 계층3에 맞는 방식이라서가 아니다.

### 사람 개입 워크플로우 구체화 — 도메인 분리 기반 재설계 (설계 초안, 코드 미반영)

5단계(코드 리뷰) 중 "escalated가 기업담당자/구매자 상황을 구분 못 한다"는 것과
"split_delivery_preference가 사전 선택으로 잘못 설계됐다(실제로는 문제 발생 시점의
사후 결정이어야 함)"는 두 이슈가 발견됐다. 위 "사람 개입 경로의 구조적 한계"와 "지연 사유의
세 계층"을 이어 구체적인 설계로 발전시킨 결과를 남긴다. **아직 코드에는 반영하지 않았다** —
그래프 재진입성(패키지조립agent 등)을 포함한 실제 구현은 별도 세션의 계획으로 진행한다.

**폐기된 가설 두 개.** 이 프로젝트는 무엇을 만들었는지보다 무엇을 폐기했는지가 핵심이라(위
"제거/통합된 것들" 참고), 논의 중 틀린 것으로 확인된 초기 가설도 남긴다.

- **가설1 (폐기): "계층(Item vs Package)으로 운영자/구매자가 나뉜다."** 처음엔 Item에서
  발생한 예외(재고부족/파손)는 구매자가, Package에서 발생한 예외(교통지연/자연재해)는
  운영자가 판단한다고 가정했다. 틀렸다 — 실제 기준은 계층이 아니라 **"누가 그 상황을 판단할
  정보를 가졌는가"**다. 창고 실물 상태(재고가 진짜 있는지, 파손 정도가 어떤지)는 계층과
  무관하게 전부 운영자만 아는 영역이라, Item층위든 Package층위든 1차 판단자는 항상 운영자다.
- **가설2 (폐기): "운영자 1차 판단 → 구매자 2차 판단"의 실시간 2단계 결정 체인.** 가설1을
  고친 뒤 "그럼 운영자가 먼저 보고, 필요하면 구매자에게 좁혀진 선택지를 실시간으로 묻는다"로
  재설계했으나 이것도 틀렸다. 워크플로우가 실제로는 성격이 다른 두 도메인으로 나뉘고, 각
  도메인에서 구매자 실시간 개입 자체가 사라지는데 **그 이유가 도메인마다 다르다**:
  - Item 도메인(피킹지연게이트) — 실시간으로 물어볼 **필요가 없어진다**. 선호도를
    (`fulfillment_preference_on_delay`) 미리 등록해두면 운영자 판단만으로 결론이 나서, 굳이
    그 시점에 구매자에게 다시 묻는 왕복이 불필요해질 뿐이다. 실시간으로 물어보는 것 자체는
    여전히 가능했을 것이다(단지 비효율적이고 블로킹 원칙에 안 맞을 뿐).
  - Package 도메인(배송중게이트) — 실시간으로 물어보는 것 자체가 **물리적으로 성립하지
    않는다**. 봉인된 패키지는 이미 고정된 품목 구성을 갖고, 지연 원인(교통지연/자연재해)이
    Package 사건이지 특정 품목의 사건이 아니다 — 즉 지연이 "이 박스 안 품목 A는 괜찮고 B만
    문제"라는 식으로 품목을 차등 취급하지 않는다. "부분수령"이 성립하려면 품목별로 다른
    결과가 나올 수 있어야 하는데, 이 도메인엔 애초에 그런 차등 지점이 없다 — 그래서 이
    선택지 자체를 제시할 수가 없다(아래 참고).
  "운영자가 판단을 끝내면 구매자에게 물어야 한다"는 전제 자체가 두 도메인 모두에서 깨졌지만,
  Item은 "불필요해서", Package는 "구조적으로 불가능해서"라는 서로 다른 이유였다는 게 이번
  발견의 핵심이다.

**두 도메인 구분.** DESIGN.md에는 이미 "mock_carrier_signal은 실제로는 택배사 웹훅이 들어올
자리"라는 서술이 있었다(4단계 후속 섹션) — 이번 재설계는 이 경계를 워크플로우 전체에 일관되게
적용한 결과다.

- **주문/재고/창고 영역** (피킹지연게이트~포장agent): 우리가 직접 운영. 판단에 필요한 정보
  (재고 실물 상태, 파손 여부)를 시스템이 갖지 못하고 운영자만 안다.
- **실제 운송 영역** (배송중게이트~추적agent): 실제로는 택배사가 담당, 우리는 위탁하는
  입장. `predict_delay_escalation`도 사실 "택배사가 흘려준 외부 신호를 해석"하는 성격이지,
  우리가 물류(트럭/경로)를 직접 판단하는 게 아니었다.

**Item 도메인 (피킹지연게이트) 재설계.**
- `OrderState.fulfillment_preference_on_delay: "부분수령희망"|"계속대기희망"|None`
  신설. `split_delivery_preference`와 다른 개념이다 — 그건 "확정 지시"(사전에 포장 방식을
  못박음)였지만 이건 **"미래 대비 선호도"**(문제가 실제로 생겼을 때만 참조됨)다. 주문 시점에
  사전등록.
- Stage1(운영자, 항상 최초, 경로B — 실제 사람. 창고 실물 상태는 시스템이 갖지 못한 정보라
  LLM으로 대체하지 않는다):
  - **회복불가**(예: 파손) → **품목 단위 취소**로 확정. 나머지 품목은 정상 진행(결과적으로
    부분수령과 동일한 효과). **주문 전체 취소가 아니다** — 원칙6(비동기 부분배송 기본)과
    가장 잘 맞는 스코프.
  - **회복가능**(예: 재고부족) → `fulfillment_preference_on_delay` 값을 참조해
    부분수령/계속대기를 자동 처리.
- **구매자에게 실시간으로 묻는 단계가 없다.** 선호도가 이미 사전등록돼 있어 운영자 판단
  이후 별도 왕복이 불필요해진다 — "그래프가 사람 응답 대기로 블로킹될 수 없다"는 기존 원칙과
  더 깔끔하게 맞는 구조(운영자 리뷰만 그래프 밖에서 기다리면 됨, 구매자 왕복까지 이중으로
  기다릴 필요가 없어짐).

**Package 도메인 (배송중게이트) 재설계.**
- "운영자가 재라우팅을 판단한다"는 표현은 부정확하다 — 실제로는 택배사(외부 시스템)의 신호를
  받아 반응하는 성격이다.
- **"부분수령" 선택지가 이 도메인엔 존재할 수 없다.** Item 도메인과 달리, 여기서 구매자에게
  실시간으로 묻지 않는 이유는 "불필요"가 아니라 **"물리적으로 불가능"**하기 때문이다. 봉인된
  Package는 이미 고정된 품목 구성을 갖고, `delay_categories`(교통지연/자연재해)는 원칙1에
  따라 Package 사건이지 개별 Item 사건이 아니다 — 지연이 박스 안 특정 품목만 골라서 괜찮고
  나쁘고를 가르지 않는다는 뜻이다. "부분수령"은 품목별로 다른 결과가 나올 수 있어야 성립하는
  선택지인데, 이 도메인엔 그 차등 지점 자체가 없다.
- **회복불가** → 보상조치(환불/재발송 — 범위 미정, 아래 "미정 항목" 참고). 구매자 선택 불필요
  (위 이유로).
- **회복가능** → `notification_enabled` 참조해 알림만(선택적).
- `predict_delay_escalation`의 `escalate_now`를 회복불가/회복가능 분류값으로 재해석한다 —
  함수 자체는 유지, 출력의 의미만 재정의. 자연재해 즉시분기(위 계층3)도 "회복불가로 분류되는
  카테고리 하나"로 흡수될 가능성이 높다(코드 변경 시 재검토 — 이게 맞다면
  `assess_disruption_severity`를 별도 decision_type으로 새로 만들 필요가 없어질 수도 있다).
- 이 도메인은 결과적으로 **사람 개입(경로B) 자체가 불필요해진다** — 전부 결정론적 액션으로
  귀결되기 때문. 판단이 그 자리에서 즉시 액션으로 끝나 persist할 "대기 상태"가 없어진다는 뜻이기도
  하다.

**customer_facing_status 신규 값 — "상품준비불가".** "지연"(자동재시도/운영자 검토 중,
미확정)과 구분되는 확정 취소 상태로 신설한다. 원인 불문 중립 라벨을 쓰는 이유:
`ItemDelayReason`(재고부족/검수불량/파손) 중 "품절"이 사실과 일치하는 건 재고부족뿐이다 —
파손/검수불량은 "그 SKU가 없다"가 아니라 개별 유닛 문제라, 이 셋을 전부 "품절"로 뭉뚱그리면
오히려 부정확한 안내가 된다. `item_delay_reason`은 내부 기록으로 그대로 남아 감사/CS
대응 능력을 잃지 않는다(원칙3) — `customer_facing_status`가 애초에 내부값의 단순화된
투영이라는 기존 역할과도 일치하는 적용일 뿐, 새 원칙을 만드는 게 아니다.

실무 전환 시 참고: 소비자보호법상 "판매자 귀책(파손/검수불량)"과 "단순 재고없음"이 환불·보상
처리에서 다르게 취급될 수 있는 법역이 있다 — 중립 라벨은 고객 노출용일 뿐이고, 내부적으로는
`item_delay_reason`이 사유를 정확히 구분해 보존하므로 그 처리 자체는 여전히 가능하다. POC
범위 밖이라 지금은 참고만 남긴다.

**v16 스키마 초안 (v15 대비 diff, 아직 코드 미반영).**

*OrderState*
| 필드 | 변경 |
|---|---|
| ~~split_delivery_preference: bool~~ | 제거 |
| `fulfillment_preference_on_delay: "부분수령희망"\|"계속대기희망"\|None` | 신설 |
| `internal_order_status` | **값 추가 필요** — "부분배송중"류. 품목 단위 취소로 "일부만 배송"이 실제로 발생 가능해져, POC단순화 6번이 예고했던 all-or-nothing enum의 gap이 이제 실제로 걸린다 |
| `cancel_status`/`cancel_requested_at` | 변경 없음 — 주문 전체 취소 흐름 전용으로 유지, 품목 단위 취소는 별도 경로(아래 `decision_log`) |

*Item*
| 필드 | 변경 |
|---|---|
| ~~escalated: bool~~ | `pending_decision: PendingDecision \| None`로 대체. `target` 필드는 없음 — 이 도메인은 항상 운영자라 파생 불필요한 상수를 필드화하면 원칙2 위반 |
| (신설) | `decision_log: list[ResolvedDecision]` — 원칙3(판단/기록 분리): `pending_decision`은 현재 열린 결정, `decision_log`는 해소된 결정의 기록 |
| `item_status` | **값 추가 필요** — "취소됨" |
| `customer_facing_status` | **값 추가 필요** — "상품준비불가"(위 참고) |
| `item_delay_reason` | 필드 변경 없음, 동작만 명확화: 취소 확정 후에도 null로 안 되돌린다(취소 사유 기록으로 유지, `item_status="취소됨"`이 이미 "더 이상 자동처리 없음"을 나타내므로 중복 필드 불필요) |

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
   경우)는 지금 시나리오로는 구조상 도달 불가능하다(아래 "재고부족 영구 에스컬레이션" 항목과
   같은 성격의 gap). 실제로 시연하려면 새 데모 트리거가 필요.

---

## 노드 목록 (최종)

| 분류 | 노드명 | 성격 | 역할 |
|---|---|---|---|
| 진입 | UserProfile 조회 | 조회(비판단) | 로그인 세션에서 delivery_addresses(주소록), payment_method, notification_enabled 로드 |
| 진입 | 주문요청agent | 이벤트 | 확정된 주문내역(장바구니 아님)으로 item_list 생성 |
| 관문 | 주문검증agent | 조건분기 | payment_status, 배송지 검증 → 통과/실패 (빈 주소록/`delivery_address_id=""` 케이스는 격리 테스트로 실패 처리 확인 완료, 별도 시나리오 미추가) |
| 판단 | Supervisor | LLM 판단 | "Supervisor"는 그래프 노드/함수 하나의 이름이 아니라 decision_type들을 아우르는 개념(`supervisor.py`). **decide_warehouse_entry**(decision_type=proceed_to_warehouse, 그래프 노드 자체, 규칙만으로 결정돼 아직 더미) / **predict_delay_escalation**(Google Gemini 실제 호출, 배송중게이트가 함수로 직접 호출 — 별도 그래프 노드 아님, 판단+근거텍스트를 SupervisorPrediction으로 반환) |
| 반복 | 창고처리agent | 조회+액션 (내장 루프) | item_list 순회, Sensor(위치확인)→Action(피킹). 예외(item_delay_reason)는 피킹만 스킵하고 그대로 넘김 — 해소는 피킹지연게이트가 담당, Supervisor는 이 경로에 관여하지 않음 |
| 집계 | 패키지조립agent | 조건카운트 | `package_ref`가 없는 item을 `delivery_address_id` 기준으로 묶음(`split_delivery_preference=true`면 같은 배송지도 item별로 분리). 같은 배송지의 미봉인 패키지가 있으면 합류(분리배송이면 항상 신규). required/arrived count 체크, 충족시 봉인+tracking_number 발급. (구 Join노드 흡수) |
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
> 대칭시켜 피킹지연게이트가 Item 층위에서도 같은 self-loop 판단 뼈대를 쓸 수 있게 함. 이 참에 `PackageState.retry_count`의
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
| customer_facing_status | string(enum) | 파생값. item_status를 사용자용으로 매핑. item_delay_reason이 있는 동안(재시도/에스컬레이션 불문)은 피킹지연게이트가 "지연"으로 덮어씀 |
| policy_version_applied | string/null | v13 신설. 지연 감지 당시 적용 정책 버전 (PackageState 동명 필드와 대칭) |
| last_checked_at | timestamp/null | v13 신설. 피킹지연게이트 폴링 기록. 지연 이력이 없으면 null |
| retry_count | int | v13 신설. 피킹지연게이트 self-loop 진입 횟수 |
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
| escalation_reasoning | string/null | v15 신설. escalated=true로 만든 근거 텍스트 — 설명가능성. 대부분 Supervisor(predict_delay_escalation)의 판단 근거지만, 자연재해 즉시 에스컬레이션(Supervisor 미개입, 고정 규칙)은 그 사실 자체를 알 수 있는 고정 문자열("자연재해 감지로 즉시 에스컬레이션 (규칙 기반, Supervisor 미개입)")을 남긴다 — 나중에 이 필드만 보고도 "이게 LLM 판단인지 규칙인지" 구분 가능. 해소/지연없음 전이 시 null로 복귀 |
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
- `order_item_id`(item_id와 분리된 유닛 식별자) 신설 여부 — 지금은 `order_validation_agent`의
  item_id 중복 검사로 임시 대응 중(상세: "발견된 gap: item_id 중복 시 패키지 봉인이 오염됨" 참고).
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
  결과에서 이상 신호가 발견될 때만 개입하도록 나눈다. 지금의 "예외 없으면 규칙만으로 결정"이라는
  더미 판단을, 실제 조회 결과 기반 판단으로 교체하는 것과 같은 방향 — `predict_delay_escalation`이
  이미 "이상 신호가 있을 때만 LLM 개입"이라는 같은 패턴을 배송중게이트에서 쓰고 있어 선례로
  참고할 수 있다.
- 피킹지연게이트가 여전히 창고처리agent 대신 item_status를 직접 확정한다 (POC 단순화 1번) — 창고처리agent
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
  나중에 이 경로가 열리면 다시 열어봐야 한다. **(5단계 후속: "사람 개입 워크플로우 구체화"
  설계(위)가 이 항목의 답을 상당 부분 내놨다 — `customer_facing_status`에 "상품준비불가"를
  신설하고, 아래 "cancel_status 재사용 불가" 결론도 최종 설계에서 그대로 유지된다(다만 이유가
  갱신됨: 구매자가 능동적으로 선택하는 흐름 자체가 없어지고 운영자 판단만으로 품목 단위 취소가
  확정되므로, "요청/승인/거부" 흐름인 `cancel_status`와는 애초에 성격이 다르다). 아래 논의된
  범위는 그 결론에 이르기까지의 기록으로 남겨둔다.)** 논의된 범위:
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
    새 decision_type(예: `confirm_item_cancellation`)이 승인하는 흐름이 더 현실적. 용어로 말하면
    이건 정확히 "경로B(사람 개입)"에 해당한다 — 위 "사람 개입 경로의 구조적 한계" 섹션 참고.
  - **데모로 재현하려면 별도 트리거가 필요하다.** `_ITEM_RESOLVE_AT_RETRY["재고부족"]`은 시나리오3/5가
    "정상 해소"를 검증하는 데 쓰고 있어 값을 바꾸면 안 된다 — 이 경로를 실제로 타는 데모를 만들려면
    기존 재고부족과 구분되는 새 신호(예: "완전 단종" 전용 지연 사유나 별도 fixed-mapping)가 필요하다.

### "재고부족" 개념의 세 가지 층위

창고처리agent(warehouse.py)를 검토하다가 "재고부족"이라는 한 단어가 실제로는 서로 다른
층위 세 개를 뭉뚱그려 가리키고 있다는 걸 발견했다. 구분한다:

1. **결제 시점 재고부족** — 장바구니/결제 단계에서 이미 품절인 상품을 걸러내는 UI/API 검증.
   이 프로젝트는 "확정된 주문내역"(주문요청agent)부터 시작하므로 범위 밖.
2. **수량체크 오류로 인한 재고부족** (현재 워크플로우가 다루는 것) — 창고에서 실제로 피킹하려는
   순간 발견되는, 결정화된 규칙으로 처리 가능한 예외. Supervisor(판단)가 필요 없다 —
   `item_delay_reason="재고부족"`이 있으면 창고처리agent는 피킹만 스킵하고, 해소/재시도/
   영구 에스컬레이션 판단은 피킹지연게이트가 고정 로직(`_ITEM_RESOLVE_AT_RETRY`, retry_count
   임계치)으로 전담한다. **지금 코드가 정확히 이 층위를 다루고 있고, 이게 맞는 설계였음을
   재확인했다** — 창고처리agent가 이 예외를 만나 Supervisor를 부르지 않는 것은 문서 오류가
   아니라 의도된 설계다(위 창고처리agent 행 정정 참고).
3. **판매량 예측 기반 재고 확보** — "얼마나 미리 발주/보충해둘지"를 예측하는 진짜 판단(예측)
   영역. 하지만 이건 개별 주문의 창고처리 노드 하나가 다룰 문제가 아니라, 이 주문 워크플로우
   전체와는 독립적으로 돌아가는 **완전히 별도의 상위 시스템**(재고관리, 배치성 수요예측)의
   책임이다. 지금 프로젝트 범위 밖 — "확장 지점" 섹션에 기록만 해둔다.

세 층위를 하나의 "재고부족" 필드/노드로 뭉뚱그리지 않고 분리해서 본 것이 핵심 — 층위2에
Supervisor 판단을 억지로 끼워 넣거나, 층위3(예측)을 이 워크플로우 안에 노드로 만들려는
시도는 둘 다 잘못된 방향이었을 것.

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

## 실무 전환 시 고려사항
- `main.py`의 데모 시나리오 11개는 POC 검증용이다. 실제 서비스화 시 `main.py`(순수 진입점)와
  `tests/`(시나리오 이관, pytest 등 정식 프레임워크로) 분리가 필요하다.
