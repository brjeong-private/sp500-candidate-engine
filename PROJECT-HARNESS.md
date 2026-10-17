# S&P 500 Candidate Engine 공통 하네스

**적용 범위**: 저장소의 코드, SQL, 설정, 배치, 모델, 테스트, 운영 문서 전체
**목적**: 수집부터 후보 선정까지 동일한 범위·시점·무결성·재현성 규칙을 강제한다.

이 문서는 프로젝트 공통 불변식의 기준 문서다. 기능별 계획이나 설계 문서가 이 문서와 충돌하면 이 문서를 우선하며, 예외가 필요하면 변경 이유·영향·검증 방법을 먼저 문서화해야 한다.

## 1. 프로젝트 범위

프로젝트의 끝은 다음 네 단계다.

```text
수집 -> 전처리 -> 모델 점수 -> 후보 선정
```

### 포함

- 시장·기업행위·종목·유니버스·공시·재무·이벤트 데이터 수집
- 원본 snapshot, 정규화, 품질 검사, point-in-time manifest 생성
- Qlib 데이터 export, 조정가격, 특징, 라벨, processor, 모델 학습·평가
- 일일 모델 점수, 전체·그룹 순위, 레거시 5~10개 정량 후보와 일일 MEDIUM_20D
  정량 분석 후보 20개 및 선정 사유 저장
- manifest로 제한된 기업·이벤트 evidence의 LLM 점수와 독립적인 20개 분석 후보군 저장
- 별도 v4 정책에서 LLM native 검색 도구·과거 원문 버전 admission gate·격리 평가를
  이용한 정보 보강·점수 반영
- MEDIUM_20D 정량 Top 20과 별도 versioned 이벤트 LLM Top 20의 RRF Fusion,
  최종 20개·SHORTFALL 저장과 versioned 외부 후보 전달 계약
- 후보 결과를 외부 소비자가 읽을 수 있는 안정적인 조회·파일 계약

### 제외

- TradingAgents 또는 다른 agent의 실행·상태·prompt·memory·report·비용 관리
- 검증되지 않은 외부 자료·모델 기억·임의 웹 검색을 이용하는 후보 LLM 분석,
  매수·매도 판단, 주문 생성과 자동 매매
- 외부 분석 시스템의 재평가·cooldown·중복 실행 정책
- 외부 소비자의 최신 뉴스·웹 검색에 대한 시점 통제

후보 결과는 **후속 분석 대상 목록**이며 매수 추천이나 포트폴리오 주문이 아니다. 외부 시스템 연동은 이 저장소 밖에서 별도로 구현한다. 이 저장소는 특정 외부 소비자에 종속된 스키마나 실행 상태를 만들지 않는다.

`LLM_PRESELECTION`은 이 저장소가 수집하고 point-in-time manifest로 고정한 evidence만
평가하는 후보 선정 단계다. 출처 없는 모델 지식·임의 웹 검색·투자 의견을 사용하지 않으며, 정량 후보와
독립적인 20개 후속 분석 후보군을 제공한다. 독립 결과는 Fusion과 구분해 보존한다.
기존 v1/v2는 DB manifest만 사용한다. 승인된 v4 검색 보강 예외는 4.3.2절과
[LLM 전용 하네스](src/sp500_candidate_engine/llm_preselection/LLM-HARNESS.md)를 따른다.

LLM 구현·실행 진입점은 `src/sp500_candidate_engine/llm_preselection/`, 설정은
`config/llm_preselection/`, 테스트는 `tests/llm_preselection/`으로 분리한다.
정량 추론 함수가 LLM을 실행하지 않는다. 공통 일일 control plane은 수집 후 고정한
context를 두 독립 파이프라인에 전달하고 각각의 결과·실패를 보존한다.
Fusion은 두 성공 run 이후의 별도 후보 선정 단계이며 앞으로도 `MEDIUM_20D` 전용이다.
기존 SHORT_5D 정량·외부 전달 경로는 유지하며 SHORT Fusion은 지원하지 않는다.

독립 후보 실행은 기존 execution context에서 QUANTITATIVE·LLM_PRESELECTION·FUSION
중 한 단계만 실행한다. 수집·학습·다른 후보 분기·외부 분석을 암묵 실행하지 않는다.
독립 stage run과 immutable 사업 결과 run ID를 구분하고, 수락 당시 context·artifact·
정책·deployment 계약과 retry 원본 ID를 보존한다. 같은 key의 다른 입력은 충돌로
실패하며 성공 결과나 terminal stage를 덮어쓰지 않는다. 기존 일일 자동 DAG는 유지한다.

기존 LLM policy와 별도로 신규 이벤트 policy는 비가격 evidence, 최근 7일 이벤트,
운영 최대 90개 이벤트 issuer와 최대 10개 무이벤트 대조 issuer를 평가한다.
실적 일정은 cutoff 전후 7일 중 cutoff까지 알려진 정보만 인정한다.
유형별 이벤트 점수는 각 1점이며 대조 표본은 context·policy·issuer 기반으로 결정적이다.
평가 5개 항목 중 근거가 있는 최소 3개 항목의 가중치를 재정규화하며 근거 없는 항목은
null·결측 사유를 보존한다. OHLCV·Quant 점수·검증되지 않은 외부 지식으로 결측을 채우지 않는다.
정확한 rubric·선별·동점·evidence 계약은 versioned 설정으로 고정한다.

성공한 최종 Fusion 20개 전체는 기존 오케스트레이터를 통해 외부 소비자에게 전달할 수 있다.
계약 version·run·payload hash·20개 identity와 수신 멱등성을 검증하기 전에는
자동 전달을 활성화하지 않는다. 5~10개로 재축소하거나 중간 목록·실패·SHORTFALL을 전달하지 않는다.
이는 후보 목록 전달이며 외부 분석 실행·리포트·비용·재평가 기능의 구현 승인이 아니다.
문서의 구현 목표 승인과 실제 기능 구현·migration·운영 활성화 승인을 구분한다.

외부 Portal·TradingAgents에 전달할 최종 후보 계약은 **20개**다(2026-10-16:
기존 5~10개에서 변경). 최종 Top 20을 다시 5~10개로 축소하거나 두 중간 목록을
40개로 전달하지 않는다. 이 계약은 SHORT_5D 레거시 정책을 변경하지 않는다.
Fusion·전달 어댑터는 기본 비활성으로 구현한다. `FUSION_ENABLED=false`인 MEDIUM은
`parallel_preselection`에서 제출 없이 종료한다. 운영 migration·배포·소비자 전량 수용과
멱등성 검증 및 명시적 승인 전에는 자동 전달을 활성화하지 않는다.

오케스트레이터는 Candidate 실행과 외부 소비자 연계를 조정하는 control plane이며,
Candidate Engine의 사업 범위를 위 네 단계 밖으로 확장하지 않는다.

## 2. 규칙의 적용 우선순위

`.local/PROJECT-HARNESS.local.md`가 존재하면 개발 머신에만 필요한 추가 규칙으로
선택 적용한다. 로컬 하네스는 이 공통 하네스의 범위와 불변식을 완화하거나 대체할 수 없다.

1. 이 문서의 공통 불변식
2. 승인된 schema와 versioned 설정
3. 기능별 설계·구현 계획
4. 실험용 notebook·임시 분석

실험 코드도 원천 데이터를 변경하거나 미래 누수 방지 규칙을 우회할 수 없다. 실험 결과가 운영 결과로 승격되려면 동일한 manifest·설정·artifact 검증을 통과해야 한다.

## 3. 데이터 무결성

### 3.1 원본 불변성

- 원본 응답은 content hash와 함께 immutable snapshot으로 보존한다.
- 정정·재수집·재계산은 기존 원본이나 논리 revision을 덮어쓰지 않는다.
- 동일 자연키와 동일 payload hash는 기존 revision을 재사용한다.
- payload가 바뀐 경우에만 다음 revision을 생성한다.
- 급등락·결측이라는 이유로 원본 값을 임의 수정하거나 삭제하지 않는다.

### 3.2 식별자와 시점

- ticker 문자열을 영구 식별자로 사용하지 않고 `instrument_id`를 기준으로 한다.
- ticker, 거래소, 종목 상태, 유니버스 membership, 분류는 유효기간을 보존한다.
- `valid_from/to`, `source_available_at`, `observed_at`을 서로 다른 의미로 관리한다.
- 동일 issuer의 복수 share class는 명시된 정책 없이 하나로 합치지 않는다.

### 3.3 거래일과 결측

- 날짜 계산은 versioned 거래소 session을 기준으로 한다.
- 휴장, 상장 전, 상장폐지 후, 거래정지, provider 결측을 같은 `NaN`으로 취급하지 않는다.
- `$change`와 일일 수익률은 직전 **거래 session** 기준이다. 중간 session 값이 없으면 여러 날 수익률을 1일 수익률로 만들지 않고 결측·품질 상태를 기록한다.
- forward fill로 가격·거래량·라벨을 임의 보완하지 않는다.

### 3.4 기업행위

- raw OHLCV와 adjusted OHLCV를 분리한다.
- split·dividend factor는 사용한 action revision과 adjustment policy version을 참조한다.
- 가격과 거래량 조정 방향을 함께 검증하여 이중 조정을 막는다.
- ratio 충돌이나 action lineage 누락이 있으면 해당 종목의 특징·점수 생성을 차단한다.

## 4. 미래 데이터 누수 방지

### 4.1 의사결정 시각

- 모든 일일 실행은 `target_session`, `cutoff_at`, `generated_at`을 구분한다.
- session D 후보는 D 데이터가 확정된 뒤 정의된 cutoff에서 생성한다.
- 특징 입력은 해당 의사결정 cutoff까지 이용 가능했던 정보만 포함한다.
- 미래 가격은 라벨과 사후 평가에만 사용하고 입력 특징에 포함하지 않는다.

### 4.2 manifest 제한 조회

- 모든 분석·학습·추론 조회는 `execution_context_id`를 필수로 받는다.
- context의 `input_manifest_member`에 포함되지 않은 snapshot은 읽지 않는다.
- 단순히 `source_available_at <= cutoff_at`인 최신 row를 임의 선택하지 않는다.
- FULL/DELTA lineage가 끊기거나 precedence가 모호하면 fail closed한다.

### 4.3 재현 모드

- `OPERATIONAL_REPLAY`: 당시 시스템이 실제 관찰한 snapshot만 사용한다. `source_available_at`과 `observed_at`이 모두 cutoff 이하여야 한다.
- `HISTORICAL_RECONSTRUCTION`: 현재 확보한 원천으로 과거 cutoff를 재구성한다. 당시 운영 재현으로 표현하지 않는다.
- 과거 원천 revision, 유니버스, GICS 이력을 복원할 수 없으면 제한을 결과 metadata와 평가 보고서에 명시한다.
- 현재 분류를 과거에 적용한 실험은 point-in-time 분류 실험과 분리한다.

### 4.3.1 과거일 LLM 분석의 강제 경계

- 과거일의 정보 경계는 그 실행의 고정 `cutoff_at`이다. `price_session_date` 자정이나
  재실행한 현재 시각으로 바꾸지 않는다. D 세션을 D+1 cutoff에 처리하는 기존 규칙을 유지한다.
- LLM 입력 생성·screening lineage·캐시 입력 재사용·모델 호출 전·Fusion 근거 저장에
  동일한 `llm-cutoff-v1` 검증을 적용한다. 위반 데이터를 제거하고 성공으로 계속하지 않는다.
- 모든 사용 자료의 `source_available_at <= cutoff_at`을 강제한다. 기사 공개·공시 접수
  시각과 보고 대상 기간도 검증하며, 실제 제공 packet과 원천 link가 양방향으로 연결돼야 한다.
  cutoff 후 공개된 뉴스·실적·공시 정정본은 과거일 입력이나 설명 근거로 사용할 수 없다.
- `HISTORICAL_RECONSTRUCTION`에서 늦게 수집한 과거 자료는 허용하지만 **늦게 공개된
  정보는 허용하지 않는다**. `OPERATIONAL_REPLAY`는 원천 관찰 시각도 cutoff 이하여야 한다.
- 이미 수집했던 이벤트의 변경 payload를 새 revision으로 저장할 때 원래 기사 발행 시각을
  수정본 공개 시각으로 재사용하지 않는다. 검증된 별도 수정 공개 시각이 없는 수정본은
  관찰 시각보다 과거로 소급하지 않으며, 과거의 소급 기록된 후속 revision도 조회에서 차단한다.
- cutoff 전에 알려진 미래 실적 **일정**은 기존 ±7일 정책에 따라 허용한다.
  미래 일정과 이후 공개된 실제 실적·결과를 혼동하지 않는다.
- packet/context/session/hash·시점·manifest·인용 연결 검증 실패는 명시적인 실행 실패다.
  신규 하네스·요약 계약은 입력 identity와 독립 stage 고정 계약에 포함한다.
  기존 immutable run을 수정하거나 과거 요약을 조회 시 새로 생성하지 않는다.
- LLM은 실제 제공 evidence만 평가하며 모델 기억·임의 웹 검색으로 근거를 채우지 않는다.
  인용 검증은 제공 자료와의 연결을 보장하며 모델 내부의 인과 기여를 증명하지 않는다.

### 4.3.2 LLM 검색 보강의 미래 정보 금지

- v4 검색 보강 자료의 점수 반영은 명시적으로 승인된 별도 정책이다.
  기존 v2의 입력·점수·과거 run을 소급 변경하지 않는다.
- **원천 공개 시각·원문 revision이 cutoff 이전임을 서버가 검증하지 못한 자료는
  LLM 입력·설명·점수에 사용하지 않는다.** LLM이 출력한 URL·날짜나 현재 페이지의 날짜만으로
  검증했다고 처리하지 않는다. 사전학습 기억도 과거 원천의 대체물이 아니다.
- 취득은 Azure OpenAI native `web_search`가 수행한다. 서버의 추가 원문 다운로드 경로는
  제거한다. 검색 도구에 전체 DB packet·내부 UUID·계약 payload를 전달하지 않는다.
- 초기 승인 원천은 고정 packet의 CIK/accession에 연결되는 SEC 원문 버전이다.
  공개 시점은 DB manifest에 고정한 metadata로 검증하며 모델이 출력한 날짜를 신뢰하지 않는다.
  일반 뉴스는 과거 원문 버전 증거가 없으면 점수에 넣지 않는다.
- 전체 consulted sources와 open/find URL을 검증한다. 미래·현재·미확인 버전이 하나라도
  섞인 검색 응답은 전체 폐기한다. 단순 날짜 필터나 인용만 검사한 사후 선별은 금지한다.
- 검색과 점수 모델은 대화를 분리한다. 격리된 검색 대화·추론·미승인 문단·response ID를
  평가에 전달하지 않는다. 모델 이름·버전은 재현성 기록이며 자료 승인/배제 기준이 아니다.
  자료의 공개 시점과 고정 원문 버전으로 판단한다.
- 늦은 취득은 `HISTORICAL_RECONSTRUCTION`에서만 허용하며 공개 시점 금지는 그대로다.
  `OPERATIONAL_REPLAY`는 취득·관찰도 cutoff 이하여야 한다. 과거 cutoff 이후의 신규
  다운로드로 당시 운영 재현을 가장하지 않는다.
- DB 사실·검색 모델 발췌·평가 해석을 분리한다. `DB_PACKET/LLM_SEARCH_VERIFIED`와
  검색 증거 hash를 연결하며 URL 인용만으로 사실성·원문 본문 확보를 보증했다고 주장하지 않는다.
- 외부 보강에도 없는 정보는 null·결측·`information_gaps`로 남긴다.
  미래 실적·주가·사건 결과나 현재 검색 결과로 빈칸을 채우지 않는다.
- DB 원천 수집 테이블은 확장하지 않는다. raw 검색 응답·거부 증적은 파일/객체에 격리하며
  승인된 bounded 발췌/proof만 기존 immutable LLM packet에 보존한다.
  DB 공시 metadata snapshot과 검색 tool artifact를 같은 물리적 원천으로 표현하지 않는다.
- 검증·원문 접근·artifact 재현 실패는 명시적 실패이며 구 정책/영문 cache/무보강 성공으로
  조용히 대체하지 않는다. 본문 미확보도 보강 성공이 아니며 승인 문단이 없으면 평가하지 않는다.
  운영 활성화에는 별도 정책 선택·artifact 보존·배포 검증이 필요하다.

### 4.4 학습 누수

- 무작위 train/validation/test split을 사용하지 않는다.
- processor는 train segment에서만 fit하고 validation/test/일일 추론에서 refit하지 않는다.
- 라벨 horizon이 split 경계를 넘는 표본은 purge한다.
- embargo는 관습적으로 고정하지 않고 검증 구조·horizon과 함께 version 관리한다.
- walk-forward test window가 겹치면 운영 성과에는 날짜별 당시 모델 예측 하나만 사용한다.

### 4.5 사후 사건

- 후보 선정 시점에 알려지지 않았던 거래정지·상장폐지·정정 정보를 이유로 과거 표본을 제거하지 않는다.
- 미래에 exit 거래가 불가능해진 경우 제거하지 않고 versioned 평가 규칙에 따라 손실, 지연 청산 또는 미평가 상태를 기록한다.

## 5. 전처리·Qlib 하네스

- Qlib export는 adjusted `open`, `high`, `low`, `close`, `volume`, `factor`와 versioned calendar를 포함한다.
- 피처 계산용 가격 이력 범위와 후보 자격 membership 범위를 분리한다.
- 편입 전 이력이 합법적으로 확보되어 있으면 warm-up 계산에 사용하되, 편입 전 날짜에는 후보 자격을 부여하지 않는다.
- warm-up 길이는 고정 60일이 아니라 활성 feature definition의 최대 lookback으로 계산한다.
- 초기 Qlib 모델은 Alpha158 단독으로 검증한다. 추가 특징은 별도 feature definition/version으로 관리한다.
- 기본 label은 `D+5 adjusted close / D+1 adjusted open - 1`의 개별 종목 raw 5거래일 수익률이다.
- SPY는 optional 비교 series이며 label 생성·학습·선정의 필수 입력이 아니다.
- label normalization·횡단면 표준화·rank 변환을 적용하지 않는다. 다른 변환을 실험하면 추론값을 원래 수익률 단위로 복원하고 별도 version으로 기록한다.

## 6. 모델 점수 하네스

- v2 score는 `PREDICTED_5D_RETURN` 회귀값이며 상승 확률이나 신뢰도가 아니다.
- 모델별 raw score, rank, percentile, model version, processor version, feature run을 함께 저장한다.
- 모델 버전 간 raw score 차이를 직접 비교하지 않는다. 필요하면 rank percentile 변화나 별도 calibration을 사용한다.
- calibration 없이 `confidence`나 `probability`라는 이름을 사용하지 않는다.
- 동일 scoring run 안에서 rank는 유일하고 결정적이어야 한다.
- 동점 정렬 기준은 설정에 고정한다. 기본값은 `score DESC, instrument_id ASC`다.

## 7. 후보 선정 하네스

### 7.1 적격성

다음 hard gate는 완화할 수 없다.

- cutoff와 manifest 위반 없음
- 대상 날짜의 universe membership 충족
- 필요한 lookback과 필수 특징 충족
- 기업행위·식별자·가격 품질 통과
- 유효한 model/processor/feature artifact 조합
- blocking 품질 이슈 없음

### 7.2 선택 알고리즘

- 상위 10개를 먼저 자른 뒤 제약을 적용하지 않는다.
- 원천 정량 선정은 전체 적격 universe를 결정적 순서로 순회하면서 issuer 중복,
  sector 제한 등 정책을 적용하고 목표 개수를 채운다. Fusion의 승인된 후보 풀 예외는 아래와 같다.
- sector cap처럼 완화 가능한 soft constraint와 데이터·시점 gate 같은 hard constraint를 설정에서 구분한다.
- 레거시 `QUANTITATIVE` 기본 후보 수는 5~10개다. 일일 MEDIUM_20D 경로는 별도
  versioned policy로 정량 분석 후보 20개를 생성한다. 각 정책의 최소 수를 충족하지
  못하면 `SHORTFALL`로 종료하고 성공 모양의 fallback을 만들지 않는다.
- 초기 정량 경로는 `selection_type=QUANTITATIVE`로 기록한다. 추후 이벤트·재평가 경로를 추가할 때 별도 type과 quota를 사용한다.
- `LLM_PRESELECTION`은 별도 schema와 policy version으로 정확히 20개를 선정한다. 20개를
  만들 수 없거나 LLM 호출·검증이 실패하면 `SHORTFALL` 또는 `FAILED`로 종료하며 정량
  후보나 과거 결과를 fallback으로 사용하지 않는다.
- 후보 선정 결과는 분석 예산 또는 매수 수량을 의미하지 않는다.

#### Fusion 후보 풀 예외와 정책

- 적용 대상은 `selection_type=FUSION`, `model_purpose=MEDIUM_20D`뿐이다.
- 입력은 같은 execution context·manifest·universe·session·cutoff·재현 모드의
  성공 Quant Top 20과 신규 이벤트 policy의 성공 LLM Top 20으로 고정한다.
- 예외 이유는 두 독립 Top 20의 합의·보완 효과를 유지·평가하기 위해서다.
  후보 풀은 두 목록의 instrument union으로 제한하고 후순위로 확장하지 않는다.
  중복·품질·섹터 제약에 따라 매일 20개 생성이 보장되지 않는 영향을 명시한다.
- 원천 목록의 연속 position 1~20과 기본 `k=10`을 사용한다.
  동일 instrument에만 두 기여도를 합산한다. 다른 share class는 합산하지 않고
  issuer별 적격 RRF 최고 종목 하나를 남기며 동점은 `instrument_id ASC`다.
- 원천별 instrument·예측값·순위를 보존하고 같은 issuer의 다른 종목 값을 복사하지 않는다.
- 모든 hard gate를 유지하고 섹터당 2개·부족 시 4개까지 한 번 완화한다.
  부족하면 `SHORTFALL`로 저장하며 원천 후순위·과거 결과로 채우지 않는다.
- 검증은 목록 순위·share class·정확한 RRF·동점·섹터 완화·union 밖 후보 미사용·
  SHORTFALL 전달 차단·context 불일치·rollback·멱등성 테스트를 포함한다.

### 7.3 결과 계약

`QUANTITATIVE` 최소 필드:

- `selection_run_id`
- `selection_type`
- `price_session_date`
- `cutoff_at`
- `generated_at`
- `scoring_run_id`
- `model_version_id`
- `policy_version`
- 후보별 `instrument_id`, 당시 symbol, position, raw score, rank, percentile, 품질 상태, reason codes

후보 run은 단일 transaction으로 저장한다. position·instrument 중복, 점수 누락, rank 불일치가 있으면 전체를 rollback한다.

`LLM_PRESELECTION` 결과는 별도 run ID, `execution_context_id`, prompt/deployment/evidence
schema version, source evidence lineage, 구조화 score와 reason code를 저장한다.
LLM score는 예상 수익률·확률·confidence로 표현하지 않는다.

`FUSION`은 원천 Quant selection·scoring run ID, LLM preselection·ranking run ID,
공통 execution context·manifest identity, 양쪽 policy와 Fusion 설정 hash를 고정한다.
최종 instrument·issuer·원천 목록 순위·RRF·position·품질·선정/제외 사유를 보존한다.
run·candidate·필수 audit는 단일 transaction으로 저장하고 입력 불일치와 중복은 fail closed한다.
원천 두 결과·Fusion 결과·외부 전달 상태를 구분하며 전달 실패로 성공 후보를 덮어쓰지 않는다.
전달 재시도와 수신 확인은 오케스트레이터 control plane에 두고 Candidate schema에
외부 분석 job·report 상태를 추가하지 않는다.

## 8. 평가 하네스

### 8.1 모델·후보 평가

- 일별 IC, Rank IC, coverage, score dispersion을 기록한다.
- 최종 선정 후보의 Top-5/10 raw return, 양의 raw return 비율, 비용 차감 return과 중첩 cohort drawdown을 주요 지표로 평가한다.
- benchmark excess return은 optional 비교 지표로만 유지한다.
- 후보 정책 비교는 같은 날짜, universe, cutoff, label, 거래비용 가정으로 수행한다.
- reconstruction 결과와 operational replay 결과를 합쳐 하나의 실운영 성과로 표현하지 않는다.

### 8.2 포트폴리오 평가

매일 생성한 후보의 성과와 포트폴리오 성과를 구분한다. 연환산 수익률, drawdown, turnover를 주장하려면 다음을 먼저 versioned policy로 정의해야 한다.

- 자금 배분과 현금 처리
- 동시 보유 한도
- 동일 종목 재선정
- 보유 기간과 중첩 position
- 거래 가능성, 거래비용, 청산 실패

Qlib `TopkDropoutStrategy` 결과를 본 프로젝트의 일일 후보 정책과 동일한 전략으로 간주하지 않는다.

## 9. 실패·재실행·운영

- 데이터, export, feature, model, scoring, selection 상태를 분리한다.
- optional 데이터 실패를 성공으로 숨기지 않고 disabled/stale/missing 상태로 기록한다.
- core gate 실패 시 점수·후보 단계를 실행하지 않는다.
- 오늘 실행 실패 시 과거 후보를 오늘 결과처럼 재사용하지 않는다.
- 승인된 fallback이 있다면 별도 policy/version과 `fallback_used=true`를 기록한다.
- 동일 idempotency key와 동일 payload는 재사용하고, 같은 key의 다른 payload는 충돌로 실패한다.
- 로그에 secret, token, password, 원문 payload를 기록하지 않는다.
- SKU 하향, 리소스 중지, replica 축소는 비용 절감 목적이라도 실행 전에 사용자 승인을 받는다.
- PostgreSQL, MySQL, Candidate App Service, Portal App Service, TradingAgents,
  orchestrator는 항상 실행 상태를 유지하는 운영 리소스다.

## 10. 필수 검증

변경 범위에 따라 최소한 다음을 검증한다.

- 원본·revision·observation 중복 방지
- cutoff 이후 데이터와 manifest 밖 snapshot 차단
- split 전후 가격·거래량 연속성과 factor lineage
- 거래일·결측·instrument span
- processor train-only fit과 feature dimension
- label entry/exit session, purge, benchmark optionality
- scoring rank·percentile 결정성
- 레거시 정량 후보 5~10개, 일일 MEDIUM_20D 정량 분석 후보 20개와 LLM 분석 후보
  20개, hard/soft constraint, `SHORTFALL`, transaction rollback
- 신규 LLM의 이벤트·대조 표본 결정성, 최소 3개 항목 근거·가중치 재정규화·비가격 packet
- Fusion의 승인된 union 예외·동일 instrument 합산·issuer 중복·k=10·섹터 2/4 정책
- 원천 identity 일치, 양쪽 장애 격리, Fusion SHORTFALL·FAILED의 외부 전달 차단
- 성공 Fusion 20개 전량 전달의 versioned 계약·수신 identity 검증·재전달 멱등성
- 재실행 idempotency와 artifact hash

문서만 바꾸는 경우에도 범위·용어·상태 표현이 다른 기준 문서와 충돌하지 않는지 검색한다.

## 11. 변경 규율

- 새 기능은 어느 단계에 속하는지 먼저 밝힌다: 수집, 전처리, 모델 점수, 후보 선정.
- 범위 밖 기능은 이 저장소에 구현하지 않고 외부 의존 계약만 일반화한다.
- schema·모델·processor·label·selection policy 변경은 version을 올린다.
- 데이터나 모델 품질 제한은 숨기지 않고 결과 metadata와 문서에 기록한다.
- 사용자 요청으로 변경한 코드·설정·스키마·문서는 `CHANGELOG.md`에 한 줄씩 기록한다.
