# Agent Implementation Instructions — Hybrid Candidate Selection with RRF

## 변경 기록과 구현 경계

- 2026-10-16: TradingAgents 전달 후보를 **기존 5~10개에서 20개로 변경**한다.
  최종 Top 20 전체를 전달하며 별도의 5~10개 축소 정책은 폐기한다.
- 공통 수집 → 고정 cutoff/manifest → 독립 Quant Top 20·LLM Top 20 병렬 생성은
  구현된 구조다. LLM은 `LLM_PRESELECTION_ENABLED=false`가 기본값이다.
- 이 문서는 **후속 RRF 통합 설계**이며 통합·최종 전달은 아직 구현하지 않았다.
  현재 MEDIUM workflow는 `parallel_preselection`에서 종료하고 외부 제출은 0개다.
  문서 변경은 기능 활성화·migration·운영 배포를 의미하지 않는다.
- SHORT_5D·명시적 API 모델 선택의 레거시 계약과 기존 모델 평가 지표는 유지한다.

## 1. 목표

기존 `sp500-candidate-engine`에 LLM 기반 기업·이벤트 분석 경로를 추가하고, 기존 정량 모델과 LLM이 각각 선정한 Top 20을 Reciprocal Rank Fusion(RRF)으로 통합하여 최종 Top 20을 선정한다.

### 목표 파이프라인

```text
S&P 500 Universe
       |
Collect / Normalize / Shared Cutoff + Manifest
       |
       +-- Quantitative Model
       |   Qlib Alpha158 → LightGBM
       |   → Quant Top 20
       |
       +-- LLM Analysis
           SEC / XBRL / Earnings / News
           → Event Screening
           → LLM Evaluation
           → LLM Top 20
                    |
             Candidate Union
                    |
             RRF Rank Fusion
                    |
             Risk / Sector Policy
                    |
             Final Top 20
                    |
             PostgreSQL
                    |
             Candidate API
                    |
             TradingAgents (20; future handoff)
```

기존 정량 모델의 학습, 예측 수익률, 데이터 전처리 및 평가 방식을 변경하지 않는다.

기존 `MEDIUM_20D`를 기본 모델로 사용하고 `SHORT_5D` 및 명시적 모델 선택 기능을 유지한다.

## 2. 구현 전 필수 작업

먼저 저장소 전체를 분석하고 다음 파일 및 실제 코드 구현을 확인한다.

- `PROJECT-HARNESS.md`
- `model-architecture.md`
- `architecture-diagram.md`
- `data-architecture.md`
- `ingestion-pipeline.md`
- `orchestrator-architecture.md`
- Candidate selection 및 scoring 관련 코드
- PostgreSQL migration 및 repository 코드
- Candidate API request/response schema
- 테스트 코드 및 운영 설정

현재 [공통 하네스](PROJECT-HARNESS.md)는 manifest-fenced LLM 후보 선정을 허용한다.
외부 지식·웹 검색·TradingAgents 분석은 제외하며 추가 변경안도 이 경계를 유지한다.

하네스의 기존 불변식, 멱등성, 데이터 시점 통제, 외부 프로젝트 경계를 유지한다.

실제 코드와 문서가 다르면 코드 기준으로 구현 상태를 확인하고 차이를 보고한다. 존재하지 않는 클래스, 함수, 테이블을 가정하지 않는다.

## 3. Quant Top 20

기존 LightGBM의 scoring 결과를 재사용한다.

### 입력

- `analytics.scoring_run`
- `analytics.daily_score`
- `model_purpose`
- `execution_context_id`
- `universe_version_id`

### 처리

1. 기존 모델의 전체 universe 점수를 조회한다.
2. 기존 데이터 품질 및 eligibility 정책을 적용한다.
3. `rank_overall` 기준 상위 20개 issuer를 선정한다.
4. ticker가 아닌 `issuer_id` 기준 중복을 제거한다.
5. 예측 수익률과 순위, scoring run ID를 유지한다.

기존 LightGBM의 예측값을 확률 또는 confidence로 변환하지 않는다.

## 4. LLM Top 20

### 4.1 분석 데이터

LLM은 기존 Alpha158에 직접 사용되지 않는 기업·이벤트 정보를 분석한다.

우선순위:

1. SEC 10-K / 10-Q / 8-K
2. 정규화된 XBRL 재무 지표
3. 실적 발표 일정과 EPS estimate/reported
4. Massive News metadata
5. 기업 관련 주요 이벤트

기존 데이터베이스에서 확보 가능한 정보부터 사용한다.

공시 원문, 뉴스 본문, 실적 발표 transcript 등은 실제 접근 가능 여부와 사용 권한을 확인한 뒤 별도 확장한다.

Alpha158 특징과 LightGBM 점수는 LLM 평가 입력에 포함하지 않는다. 현재 독립 LLM은
수집된 가격 60 sessions도 cutoff-fenced evidence로 사용한다. 이를 제외하는 실험은
별도 policy version으로 관리하며 현행 구현으로 표현하지 않는다.

### 4.2 이벤트 기반 사전 선별

이 절은 후속 비용·품질 실험 제안이다. **현재 구현은 전체 적격 universe를
5개씩 배치 평가하고 60개 pool을 20개로 재정렬**한다. 아래 screening은 미구현이며
승인·비교 검증 전 현행 전체 universe 경로를 대체하지 않는다.

먼저 규칙 기반 screening을 수행한다.

- 최근 신규 SEC filing
- 실적 발표 또는 실적 정보 변경
- 중요한 기업 이벤트
- 최근 기업 뉴스
- 재무 지표의 유의미한 변화

기본 평가 대상은 100개 issuer로 설정하되 설정 가능하게 구현한다.

이벤트 점수와 선별 사유를 저장하고, 섹터 편향을 확인한다. 이벤트가 없는 기업에 대한 대조 표본 평가도 지원한다.

이벤트가 적거나 데이터가 부족할 경우 100개를 강제로 채우지 않는다.

### 4.3 LLM 평가

기존 프로젝트의 Azure OpenAI 연결 설정과 인증 방식을 우선 재사용한다. 실제 지원되는 API, 모델 배포명, structured output 기능을 확인한다.

평가 기준:

| 항목 | 가중치 |
|---|---:|
| 실적 개선 | 25% |
| 사업 모멘텀 | 25% |
| 뉴스·이벤트 영향 | 20% |
| 재무 건전성 | 15% |
| 산업 환경 | 15% |

각 항목은 0~100점으로 평가한다.

가중치는 초기 실험용 설정값이며, 검증된 최적 가중치로 간주하지 않는다.

```text
llm_score =
  earnings_score * 0.25
  + business_score * 0.25
  + event_score * 0.20
  + financial_score * 0.15
  + industry_score * 0.15
```

LLM은 구조화된 JSON을 반환해야 한다.

필수 필드:

```json
{
  "issuer_id": "example-issuer-id",
  "ticker": "EXAMPLE",
  "earnings_score": 75,
  "business_score": 80,
  "event_score": 70,
  "financial_score": 65,
  "industry_score": 75,
  "risk_score": 30,
  "uncertainty_notes": ["Limited source coverage"],
  "evidence": [
    {
      "source_type": "SEC_FILING",
      "source_id": "source-reference",
      "reason": "Revenue growth"
    }
  ],
  "summary": "Company evaluation summary"
}
```

위 JSON과 rubric은 제안 schema이며 현행 transport schema와 동일하지 않다.
보정되지 않은 confidence·상승 확률을 출력하지 않는다. 근거 범위·불확실성은
명시적 설명과 품질 상태로 표시하고 versioned schema로 검증한다.

LLM이 반환한 수치와 근거는 schema validation을 통과해야 한다. 근거가 없는 주장이나 존재하지 않는 source ID는 허용하지 않는다.

### 4.4 LLM Top 20

1. 모든 평가 결과를 저장한다.
2. `llm_score` 기준으로 정렬한다.
3. 데이터 품질과 근거 충족 조건을 검사한다.
4. issuer 기준 중복 제거 후 상위 20개를 선정한다.
5. 동점일 경우 결정적인 tie-break 규칙을 적용한다.
6. LLM 분석 실패 및 평가 대상 부족을 명시적으로 기록한다.

LLM 결과는 동일한 모델, 프롬프트, 데이터 snapshot, 설정에서 재현 가능하도록 versioning한다. 모델 응답의 비결정성으로 완전한 재생성이 보장되지 않으므로 원본 평가 결과와 해시를 보존한다.

## 5. RRF 통합 엔진

### 5.1 기본 공식

```text
RRF(i) =
  1 / (k + quant_rank(i))
  + 1 / (k + llm_rank(i))
```

기본 `k = 60`.

한쪽 Top 20에 없는 종목은 해당 항의 기여도를 0으로 처리한다.

예시:

```python
def rrf_score(quant_rank=None, llm_rank=None, k=60):
    score = 0.0

    if quant_rank is not None:
        score += 1.0 / (k + quant_rank)

    if llm_rank is not None:
        score += 1.0 / (k + llm_rank)

    return score
```

### 5.2 통합 절차

1. Quant Top 20 조회
2. LLM Top 20 조회
3. issuer 기준 union
4. 각 후보의 quant/LLM 순위 유지
5. RRF 계산
6. RRF 내림차순 정렬
7. 위험 및 데이터 품질 정책 적용
8. 섹터 분산 정책 적용
9. 최종 Top 20 선정

두 모델이 모두 선정한 종목에는 양쪽 점수를 합산한다.

한쪽 모델에서만 선정된 종목도 최종 후보가 될 수 있어야 한다.

`k=60`을 기본값으로 사용하되 `k=10, 30, 60, 100`을 비교할 수 있도록 설정 가능하게 한다.

### 5.3 정책 적용

기존 selection policy를 최대한 재사용한다.

- issuer 중복 제거
- 거래 가능 여부
- 데이터 품질 검사
- 거래정지 및 중대 위험 이벤트
- 섹터 집중도 제한
- 결정적 tie-break

기존 10개 후보용 섹터 제한을 그대로 20개에 적용하지 말고 설정 가능한 정책으로 분리한다.

정책 때문에 20개를 채우지 못하면 부적격 종목을 강제로 추가하지 않는다. 부족 수량과 사유를 기록한다.

## 6. 데이터베이스 설계

기존 `analytics` 및 `selection` 스키마를 확장한다.

신규 논리 엔터티:

- `analytics.llm_evaluation_run`
- `analytics.llm_evaluation`
- `analytics.llm_evidence`
- `selection.fusion_run`

실제 테이블명과 컬럼은 기존 migration 규칙에 맞춰 확정한다.

LLM 실행에는 다음을 기록한다.

- execution context
- input manifest
- universe version
- model deployment/version
- prompt version/hash
- evaluation policy version
- token usage
- execution status
- evaluation result hash

Fusion 실행에는 다음을 기록한다.

- quantitative scoring run ID
- LLM evaluation run ID
- fusion policy version
- RRF k
- 최종 후보 수
- 실행 상태
- idempotency key

최종 후보별 저장 항목:

```text
issuer_id
instrument_id
ticker
quant_rank
quant_predicted_return
llm_rank
llm_score
rrf_score
final_rank
selected_by_quant
selected_by_llm
risk_status
selection_reason
```

기존 `selection.selection_run` 및 `selection.candidate`와의 호환성을 검토하고, 필요하다면 별도 versioned selection type을 추가한다.

모든 DB 변경은 migration으로 관리한다.

## 7. Candidate API

기존 API의 기본 동작을 변경하지 않는다.

신규 통합 결과 조회 기능을 추가한다.

요구사항:

- 날짜 기준 조회
- 모델 목적별 조회
- `QUANT`, `LLM`, `FUSION` 구분
- Top 20 조회
- 모델별 순위 및 통합 점수
- 선정 근거 및 출처
- 실행 상태와 데이터 부족 여부

Portal·TradingAgents 전달 계약은 기존 5~10개에서 **20개**로 변경한다.
최종 Top 20 전체의 `selection_run_id`를 전달하며 다시 일부만 선정하지 않는다.
`requested_count=selected_count=20`, 실제 20개 row, position 1~20과 issuer 중복을
검증한 성공 run만 전달한다. SHORT 레거시 경로는 별도 계약으로 유지한다.
외부 소비자의 20개 수용·멱등 처리 검증 전 MEDIUM 자동 전달 차단은 해제하지 않는다.

API 경로와 request/response 구조는 기존 router와 schema를 분석한 뒤 결정한다.

## 8. 일일 실행 및 장애 처리

기존 05:30 ET 정기 실행과 Durable Functions 구조를 유지한다.

권장 단계:

```text
Collect
 → Normalize
 → Shared Manifest / Cutoff / Universe
     ├─ Quant Score → Quant Top 20 → Quant Store / API
     └─ Independent LLM Evaluation → LLM Top 20 → LLM Store / API
 → [Future] Candidate Union → RRF → Risk / Sector Policy
 → [Future] Final Top 20 → Candidate API → Portal / TradingAgents 20
```

Quant와 LLM은 동일한 cutoff 및 universe version을 사용한다.

LLM 호출은 rate limit, TPM/RPM, timeout, retry, backoff를 지원해야 한다.

같은 입력과 설정의 재시도는 이미 저장된 평가 결과를 재사용한다.

### 장애 정책

- Quant 성공 / LLM 성공: FUSION 정상 생성
- Quant 성공 / LLM 실패: FUSION 성공으로 표시하지 않음. 기존 Quant 결과는 유지
- Quant 실패 / LLM 성공: LLM 결과 보존, FUSION 실패 또는 부분 실패
- 양쪽 실패: 후보 생성 실패

LLM 실패를 숨기기 위해 Quant 결과를 Fusion 결과로 자동 대체하지 않는다.

기존 운영 정량 후보가 LLM 기능 추가 때문에 중단되지 않도록 feature flag를 사용한다.

기본값:

```text
LLM_PRESELECTION_ENABLED=false
FUSION_ENABLED=false
RRF_K=60
QUANT_TOP_N=20
LLM_TOP_N=20
FUSION_TOP_N=20
LLM_SCREENING_MAX_ISSUERS=100
```

`LLM_PRESELECTION_ENABLED`만 현행 활성화 키다. 나머지 RRF·fusion·screening 키는
후속 제안이며 아직 환경변수 계약으로 구현하지 않았다. 현재 DB는 migration 022의
LLM run·evidence·assessment와 별도 candidate 저장소를 사용한다. 이 문서의
fusion 엔터티는 기존 테이블과 같다고 가정하지 말고 신규 migration 필요성을 검토한다.

기존 스케줄러의 멱등성 및 terminal 상태 처리 규칙을 유지한다.

## 9. 데이터 누수 방지

모든 평가 입력은 `execution_context`와 `input_manifest`로 고정한다.

필수 규칙:

- `source_available_at <= cutoff_at`
- 운영 재현에서는 `observed_at <= cutoff_at`
- 미래 실적 발표 결과 사용 금지
- 이후 수정된 공시·뉴스를 과거 입력으로 사용 금지
- 현재 universe를 과거 universe로 위장 금지
- reconstruction 데이터를 operational replay로 표시 금지
- 현재 날짜에 새로 수집한 과거 정보를 당시 알고 있던 정보처럼 사용 금지

백테스트에서는 실제 과거 LLM 평가 결과가 없으면 데이터 재현 가능성을 확인한다.

검증할 수 없는 과거 데이터는 연구 결과에서 별도 구분한다.

## 10. 테스트

필수 단위 테스트:

1. RRF 공식 검증
2. 한 모델에만 존재하는 종목 처리
3. 두 모델 공통 종목 처리
4. issuer 중복 제거
5. 순위 동점 처리
6. 섹터 제한
7. 데이터 품질 필터
8. LLM JSON schema 검증
9. LLM 근거 source 검증
10. cutoff 이후 데이터 차단
11. 실행 멱등성
12. LLM 장애 시 Quant 결과 보존
13. 기존 Candidate API 호환성
14. feature flag 비활성화 시 기존 동작 유지
15. 최종 20개 전량 전달, 5~10개 재축소 금지, 20개 미만 성공 전달 차단

Mock LLM을 이용해 외부 API 호출 없이 테스트할 수 있도록 구성한다.

## 11. 연구 및 백테스트

다음 네 가지 전략을 비교할 수 있도록 실행 결과를 저장한다.

- E1: Quant Top 20
- E2: LLM Top 20
- E3: RRF Fusion Top 20
- E4: 추후 학습형 Fusion 확장용 (이번 구현 범위 제외)

비교 지표:

- 5D / 20D 수익률
- SPY 대비 초과수익률
- Rank IC
- Top-20 net return
- 최대낙폭
- 후보 중복률
- 섹터 집중도
- 토큰 사용량 및 LLM 비용

기존 t+1 시가 진입, 거래비용 및 Purged Walk-Forward 검증 원칙을 유지한다.

미래 수익률을 Fusion 가중치 또는 후보 선정에 사용하지 않는다.

## 12. 구현 순서

### Phase 1 — Contract & Design

- 저장소 분석
- 하네스 변경안
- 데이터 흐름 설계
- 신규 schema 및 API 계약
- feature flag 설계

### Phase 2 — LLM Evaluation

- 이벤트 screening
- LLM 입력 구성
- Azure OpenAI 호출
- JSON validation
- 평가 결과 및 근거 저장

### Phase 3 — RRF Fusion

- Quant Top 20 추출
- LLM Top 20 추출
- RRF 계산
- 위험/섹터 정책
- Fusion 결과 저장

### Phase 4 — Integration

- Candidate API
- 일일 pipeline 연계
- Durable Functions 호환성
- 실패·재실행 처리

### Phase 5 — Validation

- 단위 및 통합 테스트
- 기존 Quant 경로 회귀 테스트
- mock 기반 E2E
- 제한된 shadow 실행
- 성능 및 비용 측정

## 13. 완료 조건

다음 조건을 충족해야 구현 완료로 간주한다.

- 기존 Quant 경로 정상 동작
- LLM Top 20 독립 생성
- RRF 기반 최종 Top 20 생성
- 후보별 모델 순위 및 근거 조회
- PostgreSQL 실행 이력과 provenance 보존
- 동일 실행 재시도 시 중복 결과 없음
- 미래 데이터 누수 방지 테스트 통과
- LLM 장애 시 기존 운영 보호
- API 하위 호환성 유지
- 테스트 및 문서 업데이트 완료

## 14. Agent 작업 지침

1. 먼저 실제 저장소를 분석하고 현재 구현 상태를 확인한다.
2. 문서와 코드의 차이를 보고한다.
3. 기존 `PROJECT-HARNESS.md`의 제약과 충돌하는 부분을 먼저 식별한다.
4. 필요한 계약 변경과 구현 계획을 작성한다.
5. 기존 정량 모델을 수정하지 않는 최소 변경 구조를 우선한다.
6. 기존 코드 패턴, DB migration, API schema 및 테스트 구조를 재사용한다.
7. 하드코딩된 모델 배포명, API 키, 프롬프트 설정을 추가하지 않는다.
8. 운영 DB migration 및 실제 외부 API 실행은 명시적인 승인 없이 수행하지 않는다.
9. 기능을 feature flag 뒤에 구현하고 기본 비활성화 상태로 유지한다.
10. 각 Phase 완료 시 변경 파일, 테스트 결과, 미해결 문제를 보고한다.

최종 산출물은 구현 코드, DB migration, 테스트, 설정 예시, 업데이트된 아키텍처 문서 및 운영 가이드를 포함한다.

**우선 Phase 1의 저장소 분석과 구현 계획부터 수행하고, 코드 변경 전 변경 범위와 하네스 충돌 사항을 보고하라.**