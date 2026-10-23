# Agent Implementation Instructions — Hybrid Candidate Selection with RRF

## 변경 기록과 구현 경계

- **2026-10-23 현재 상태:** 독립 stage·event v2 한국어 평가·Fusion·설명/v2 API·회사명은
  운영 배포됐고 승인된 정규 일일은 MEDIUM_20D Fusion·전량 ACK를 사용한다.
  아래 10월16일의 "기본 비활성/배포 별도"는 도입 당시 기록과 코드 안전 기본값이다.
- 정규 정량은 RAW Alpha158·LightGBM `74c367e9-bd84-58ab-b933-19a36dae35c4`
  SHADOW를 유지한다. 연구 Ridge schema-v3·Sunday challenger의 생성은 운영 모델 승격이 아니다.
  정규 LLM은 DB-only v2·`llm-event-preselection-v3-ko`·`gpt-6.1-sol`·관리 ID이며
  timeout180초·공유3회 시도다. v6 optional 검색은 별도 승인 역사 연구 정책이다.
- 신규 주말은 MEDIUM만 `weekly-v2-20d-performance-suspended`로 예약한다.
  성능 임계값만 비강제하며 coverage·finite·시점/artifact·CAS·smoke·rollback은 유지한다.
- 최신 D cutoff는 D+1 달력일 NY05:30이며 원래 context를 재시도에도 유지한다.
  공유 universe selector·Quant 성공 cache fence와 DB 근거의 서로 다른 이유 결합을
  운영 반영했다. 모델 점수/weight·원본 LLM assessment·실패 history는 바꾸지 않았다.
  22일 Fusion 복구20개·설명20개·ACK20은 외부 보고서 완료와 다르다.
- 2026-10-16: TradingAgents 전달 후보를 **기존 5~10개에서 20개로 변경**한다.
  최종 Top 20 전체를 전달하며 별도의 5~10개 축소 정책은 폐기한다.
- 공통 수집 → 고정 cutoff/manifest → 독립 Quant Top 20·LLM Top 20 병렬 생성은
  구현된 구조다. LLM은 `LLM_PRESELECTION_ENABLED=false`가 기본값이다.
- 이 문서는 승인된 RRF 계약과 구현 지침이다. 신규 이벤트 정책·Fusion·조회 API·
  전달 어댑터는 기본 비활성으로 구현했으며 운영 migration·배포·실제 외부 수신 검증은
  별도 작업이다. Fusion 비활성 MEDIUM은 `parallel_preselection`에서 제출 0개로 종료한다.
- SHORT_5D·명시적 API 모델 선택의 레거시 계약과 기존 모델 평가 지표는 유지한다.
- 2026-10-16 사용자 정의: Fusion은 앞으로도 `MEDIUM_20D` 전용이며 기본 `k=10`이다.
  두 Top 20 밖으로 후보를 확장하지 않고 부족하면 `SHORTFALL`로 종료한다.
- 신규 이벤트 LLM 정책은 기존 정책을 덮어쓰지 않는 별도 버전이다. 운영 평가 예산은
  이벤트 issuer 최대 90개와 무이벤트 대조 issuer 최대 10개다.
- 동일 `instrument_id`에만 두 RRF 기여도를 합산한다. 같은 issuer의 다른 share class는
  합산하지 않고 적격 종목 중 RRF가 높은 하나만 남긴다. 동점은 `instrument_id ASC`다.
- 아래 계약은 승인된 계약이며 현행 배포 상태는 위 10월23일 요약을 우선한다. 독립 파이프라인과 정책·Fusion·전달 기능의
  구현 완료 여부를 구분하며, 문서 변경만으로 운영 플래그를 활성화하지 않는다.

## 1. 목표

2026-10-17 후속 실행 구조 변경은
[전체 통합 아키텍처](./.github/modernize/assessment/engines/facts/architecture-diagram.md)와
[정량](./.github/modernize/assessment/engines/facts/quantitative-pipeline-architecture.md)·
[LLM](./.github/modernize/assessment/engines/facts/llm-pipeline-architecture.md)·
[Fusion](./.github/modernize/assessment/engines/facts/fusion-pipeline-architecture.md) 상세 설계를 따른다.
기존 일일 DAG·선정 정책은 유지하고 독립 실행·상태·재시도 API/CLI만 추가한다.
현행 점검·문서 작성 후 구현·검증·배포 순서를 지키며 외부 분석·UI는 변경하지 않는다.

기존 독립 정량·LLM 경로를 보존하면서 별도 versioned 이벤트 LLM 정책을 추가한다.
MEDIUM_20D 정량 Top 20과 신규 정책의 LLM Top 20을 RRF로 통합하고, 정책을 통과한
최종 20개 전체를 기존 오케스트레이터를 통해 외부 소비자에게 전달한다.

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
           → Event Screening (up to 90) + Controls (up to 10)
           → LLM Evaluation
           → LLM Top 20
                    |
             Instrument Union (only the two Top 20 lists)
                    |
             RRF Rank Fusion (k=10)
                    |
             Hard Gates / Issuer Dedup / Sector Policy
                    |
             Final Top 20 or SHORTFALL
                    |
             PostgreSQL
                    |
             Candidate API
                    |
             Existing Orchestrator
                    |
             External Consumer (20; versioned handoff)
```

기존 정량 모델의 학습, 예측 수익률, 데이터 전처리 및 평가 방식을 변경하지 않는다.

Fusion은 현재와 향후 모두 `MEDIUM_20D`만 지원한다. `SHORT_5D` Fusion은 구현하지 않는다.
기존 `SHORT_5D` 정량 경로와 명시적 모델 선택은 유지하며 다른 모델로 fallback하지 않는다.
외부 전달 이후 TradingAgents 실행·분석·리포트·비용·재평가 기능은 이 저장소에 추가하지 않는다.

## 2. 구현 전 필수 작업

먼저 저장소 전체를 분석하고 다음 파일 및 실제 코드 구현을 확인한다.

- [PROJECT-HARNESS.md](./PROJECT-HARNESS.md)
- [model-architecture.md](./.github/modernize/assessment/engines/facts/model-architecture.md)
- [architecture-diagram.md](./.github/modernize/assessment/engines/facts/architecture-diagram.md)
- [data-architecture.md](./.github/modernize/assessment/engines/facts/data-architecture.md)
- [ingestion-pipeline.md](./.github/modernize/assessment/engines/facts/ingestion-pipeline.md)
- [orchestrator-architecture.md](./.github/modernize/assessment/engines/facts/orchestrator-architecture.md)
- Candidate selection 및 scoring 관련 코드
- PostgreSQL migration 및 repository 코드
- Candidate API request/response schema
- 테스트 코드 및 운영 설정

현재 [공통 하네스](PROJECT-HARNESS.md)는 manifest-fenced LLM 후보 선정을 허용한다.
외부 지식·웹 검색·TradingAgents 분석은 제외하며 추가 변경안도 이 경계를 유지한다.

현재 구현의 기준점은 다음과 같다.

- [일일 실행](./src/sp500_candidate_engine/daily_preselection.py)은 공통 context 이후
  Quant와 LLM을 병렬 실행하고 한쪽 실패 시 다른 결과를 보존한다.
- [기존 LLM 정책](./config/llm_preselection/policy_v1.yaml)은 전체 적격 universe의
  5개 단위 배치 평가, 상위 60개 pool, 최종 20개 재정렬과 가격 context를 사용한다.
- [migration 022](./sql/022_llm_preselection.sql)에 LLM ranking·evidence·assessment와
  별도 preselection run·candidate가 이미 있다. 같은 역할의 테이블을 다시 만들지 않는다.
- [LLM API](./backend/app/routers/llm_preselections.py)는 독립 Top 20을 조회한다.
- [MEDIUM 오케스트레이터](./orchestrator/workflow.py)는 Fusion 비활성 시 중간 후보에서 종료하며
  [외부 응답 검증](./orchestrator/clients.py)은 여전히 레거시 5~10개 job 계약을 사용한다.
  신규 20개는 별도 Fusion envelope·ACK 경로를 사용한다. 레거시 검증을 무조건 20개로
  넓히지 않고 외부 수신처의 신규 계약 검증 후에만 전달을 활성화한다.

기존 LLM 재사용, 신규 이벤트 LLM 정책, Fusion, 외부 전달 어댑터를 구분해 구현한다.
신규 정책은 별도 policy·prompt·evidence schema version으로 관리하고 기존 run을 변경하지 않는다.

하네스의 기존 불변식, 멱등성, 데이터 시점 통제, 외부 프로젝트 경계를 유지한다.

실제 코드와 문서가 다르면 코드 기준으로 구현 상태를 확인하고 차이를 보고한다. 존재하지 않는 클래스, 함수, 테이블을 가정하지 않는다.

## 3. Quant Top 20

기존 LightGBM의 scoring 결과를 재사용한다.

### 입력

- `analytics.scoring_run`
- `analytics.daily_score`
- `selection.selection_run` 및 `selection.candidate`
- `model_purpose`
- `execution_context_id`
- `universe_version_id`

### 처리

1. 기존 MEDIUM_20D 선정 경로를 재사용한다. 전체 적격 점수를 순회하며 hard gate,
   issuer 중복 제거, 섹터당 2개·부족 시 4개 정책을 적용한다.
2. 정확히 20개인 `SUCCEEDED` Quant selection run을 Fusion 입력으로 고정한다.
   상위 20개 점수를 먼저 잘라 기존 정책을 우회하는 새 Quant 목록을 만들지 않는다.
3. 후보의 `position` 1~20을 `quant_rank`로 사용한다.
4. 원래 `rank_overall`, 예측 수익률, instrument·issuer, scoring run ID,
   selection run ID, policy version을 별도로 보존한다.
5. Quant 완료·재사용 판정은 LLM이나 Fusion 성공 여부에 의존하지 않는다.

기존 LightGBM의 예측값을 확률 또는 confidence로 변환하지 않는다.

## 4. LLM Top 20

### 4.1 분석 데이터

이 절은 신규 이벤트 LLM 정책의 계약이다. 기존 전체 universe 정책을 묵시적으로
대체하지 않으며 새 정책을 명시적으로 선택한 실행에만 적용한다.
LLM은 수집된 기업·이벤트 evidence만 분석하고 외부 지식·웹 검색·투자 의견을 사용하지 않는다.

우선순위:

1. SEC 10-K / 10-Q / 8-K
2. 정규화된 XBRL 재무 지표
3. 실적 발표 일정과 EPS estimate/reported
4. Massive News metadata
5. 기업 관련 주요 이벤트

기존 데이터베이스에서 확보 가능한 정보부터 사용한다.

공시 원문, 뉴스 본문, 실적 발표 transcript 등은 실제 접근 가능 여부와 사용 권한을 확인한 뒤 별도 확장한다.

신규 정책의 LLM 평가 입력에는 OHLCV, `price_context`, Alpha158, LightGBM 점수·순위,
Quant 선정 여부를 포함하지 않는다. 가격·거래 가능 여부는 별도의 hard gate에서만 검사한다.
instrument·issuer·당시 symbol·분류·cutoff 등 식별과 시점 확인에 필요한 메타데이터는 허용한다.

선별 기간과 평가 evidence의 이력 기간을 구분한다. 선별은 아래 7일 규칙을 사용하지만
평가 packet은 기존 비가격 이력 한도인 뉴스 30일, 실적 이벤트 2개, 공시 365일,
재무 8개 분기, 기업행위 365일을 기본값으로 재사용한다. 이력 한도·잘림·결측을 기록한다.
당시 알려진 실적 예정 정보와 실제 발표 결과는 구분하며 미래 발표 결과는 포함하지 않는다.

### 4.2 이벤트 기반 사전 선별

대상 session의 적격 universe에서 issuer 단위로 규칙 기반 screening을 수행한다.
모든 조회는 동일 `execution_context_id`의 manifest 안에서 수행한다.

기본 평가 한도는 100개 issuer이며 이벤트 최대 90개와 무이벤트 대조 최대 10개로 나눈다.
한도와 대조 예약 수는 versioned 설정으로 관리한다. 기본 quota 간 빈자리를 임의로
전환하거나 데이터가 부족한 회사를 넣어 100개를 강제로 채우지 않는다.

달력일 기준 `(cutoff_at - 7일, cutoff_at]`에 새로 이용 가능해진 다음 유형에 각 1점을 준다.

| 유형 | 1점 부여 조건 |
|---|---|
| SEC filing | 신규 또는 정정 공시 revision |
| 재무 | 새로 이용 가능해진 정규화 XBRL fact revision |
| 실적 | 신규·변경 실적 정보 또는 아래 기간의 알려진 실적 일정 |
| 뉴스 | 새로 이용 가능해진 기업 뉴스 metadata |
| 기업 이벤트 | 위 유형과 구분되는 수집된 기업 이벤트 |

실적 일정은 `[cutoff_at - 7일, cutoff_at + 7일]`에 예정된 이벤트도 인정하되,
일정 자체가 cutoff까지 이용 가능해야 한다. 운영 재현에서는 관찰 시각도 cutoff 이하여야 한다.
실적은 두 조건을 동시에 충족해도 한 유형으로만 가산한다.

유형마다 최대 1점이므로 뉴스 개수·재수집 횟수로 점수를 부풀리지 않는다. 동일 payload의
재관찰은 신규 revision으로 간주하지 않으며 새로 생성한 snapshot 시각을 이용 가능 시각으로
대체하지 않는다. 모호한 '중요 이벤트'나 '유의미한 재무 변화' 임계값을 임의로 추가하지 않는다.

선별 점수는 LLM의 이벤트 평가 항목과 구분해 `screening_event_score`로 저장한다.
선별 점수가 양수인 issuer는 `screening_event_score DESC, latest_qualifying_available_at DESC,
issuer_id ASC`로 정렬해 최대 90개를 고른다. 유형별 점수와 선별 evidence를 저장한다.

이벤트 점수가 0인 적격 issuer 중 최대 10개를 대조 표본으로 선택한다. 표본 순서는
`SHA256(canonical(execution_context_id, screening_policy_version, issuer_id)) ASC,
issuer_id ASC`로 고정한다. 같은 입력의 재실행에 새 무작위 표본을 뽑지 않는다.
`screening_group=EVENT|CONTROL`을 기록하며 대조 회사도 운영 LLM Top 20에 들어갈 수 있다.
실제 두 그룹 수량, 부족 사유와 섹터 분포를 저장한다.

issuer별 평가 대상 instrument는 hard gate를 통과한 해당 issuer의 instrument 중
`instrument_id ASC`의 첫 종목으로 고정한다. Quant 점수로 LLM 대표 종목을 선택하지 않는다.
다른 share class는 metadata로 보존하고 issuer를 반복 평가해 예산을 소모하지 않는다.

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

근거가 있는 항목만 0~100점으로 평가한다. 항목마다 해당 issuer packet 안의 실제
evidence link ID와 평가 이유를 요구하며, source ID가 존재한다는 사실만으로
그 source가 주장을 뒷받침한다고 간주하지 않는다.

가중치는 초기 실험용 설정값이며, 검증된 최적 가중치로 간주하지 않는다.

5개 중 최소 3개 항목에 근거가 있어야 순위에 포함한다. 근거 없는 항목은 `null`과
명시적 결측 사유로 저장한다. 0점·중립값을 자동 입력하거나 외부 지식으로 채우지 않는다.

```text
supported = evidence-backed criteria
llm_score = sum(score[c] * weight[c] for c in supported)
            / sum(weight[c] for c in supported)
```

모든 항목이 있으면 원래 가중합과 같다. 3개 미만이면 `INSUFFICIENT_EVIDENCE`로 저장하고
순위에서 제외한다. 애플리케이션이 근거·범위·유한값을 검증하고 총점을 계산하며,
소수점 4자리 `ROUND_HALF_EVEN` 결과를 저장·정렬에 동일하게 사용한다.
평가 항목별 coverage, 적용 가중치 분모, 결측 사유와 품질 상태를 함께 공개한다.

LLM은 strict structured JSON을 반환한다. 신규 schema의 예시는 다음과 같으며,
기존 transport schema를 덮어쓰지 않는다.

```json
{
  "issuer_id": "example-issuer-id",
  "scores": {
    "earnings": 75,
    "business": 80,
    "event": 70,
    "financial": null,
    "industry": null
  },
  "evidence_quality": "MEDIUM",
  "uncertainty": "HIGH",
  "missing_reasons": {
    "financial": "Insufficient supplied evidence",
    "industry": "Insufficient supplied evidence"
  },
  "evidence": [
    {
      "evidence_link_id": "supplied-earnings-evidence-id",
      "criterion": "earnings",
      "reason": "Reported earnings change in supplied evidence"
    },
    {
      "evidence_link_id": "supplied-business-evidence-id",
      "criterion": "business",
      "reason": "Business update in supplied evidence"
    },
    {
      "evidence_link_id": "supplied-event-evidence-id",
      "criterion": "event",
      "reason": "Material event described in supplied evidence"
    }
  ],
  "summary": "Company evaluation summary"
}
```

`evidence_quality`는 `HIGH|MEDIUM|LOW`, `uncertainty`는 `LOW|MEDIUM|HIGH`다.
issuer·instrument·symbol의 매핑은 애플리케이션이 manifest metadata와 대조한다.
범위를 벗어난 점수, 임의 issuer, 타 issuer의 evidence, 미제공 source ID, 근거 없는
비결측 항목, 지원하지 않는 필드는 schema·의미 검증 실패다.

보정되지 않은 confidence·상승 확률과 새 `risk_score` 임계값은 도입하지 않는다.
부정적 뉴스는 해당 항목 평가·reason code에 반영하되 주관적 위험 점수만으로 강제 제외하지 않는다.
reason code·설명 길이·packet·token·재시도 한도는 versioned 설정으로 제한한다.

### 4.4 LLM Top 20

1. screening 결과, packet, 평가, 결측과 제외 사유를 저장한다.
2. hard gate와 최소 3개 항목 근거 요건을 통과한 issuer만 순위에 포함한다.
3. 애플리케이션이 계산한 `llm_score DESC, instrument_id ASC`로 정렬한다.
4. issuer별 대표 종목 하나씩 상위 20개를 선정하고 `position=llm_rank=1..20`을 저장한다.
5. 신규 정책은 기존 60개 pool의 LLM 재정렬을 사용하지 않는다. 전체 평가 순위는
   `assessment_rank`로 별도 보존하고 RRF에는 최종 목록의 순위만 전달한다.
6. 적격 평가가 20개 미만이면 `SHORTFALL`이며 부족 수량·사유를 기록한다.
   LLM 호출·출력 검증 실패는 `FAILED`이며 일부 배치만 성공했다고 성공으로 바꾸지 않는다.

policy·prompt·deployment·API·evidence schema·packet hash를 저장한다. 모델 응답의
비결정성 때문에 완전한 재생성을 주장하지 않는다. 허용된 저장소에 응답·해시를 보존하고
로그에는 원문을 출력하지 않는다. 동일 입력의 저장된 성공 결과를 재사용한다.

## 5. RRF 통합 엔진

### 5.1 기본 공식

```text
RRF(i) =
  1 / (k + quant_rank(i))
  + 1 / (k + llm_rank(i))
```

기본 `k = 10`이며 양의 정수만 허용한다. rank는 각 입력 목록의 연속 순위 1~20이다.
Quant의 `rank_overall`이나 LLM의 평가 전체 순위를 대신 넣지 않는다.

한쪽 Top 20에 없는 종목은 해당 항의 기여도를 0으로 처리한다.

예시:

```python
from fractions import Fraction


def rrf_score(quant_rank=None, llm_rank=None, k=10):
    score = Fraction(0)

    if quant_rank is not None:
        score += Fraction(1, k + quant_rank)

    if llm_rank is not None:
        score += Fraction(1, k + llm_rank)

    return score
```

위 예시는 유효한 입력에 대한 산식만 보여준다. 구현에서는 rank 누락은 `None`으로만
표현하고 0·음수·중복 순위·범위 밖 rank·양쪽 모두 누락은 오류로 처리한다.

`k=10`이면 한쪽 1위의 `1/11`이 양쪽 20위의 `2/30`보다 높다.
교집합이 항상 단독 후보보다 우선하는 정책이 아니다. 연구에서는 `k=10,30,60,100`을
비교할 수 있지만 운영 기본값을 사후 수익률로 자동 변경하지 않는다.

### 5.2 통합 절차

1. 명시적으로 고정한 Quant selection run과 신규 정책의 LLM preselection run을 읽는다.
2. 양쪽 `SUCCEEDED`, 요청·선정 수·실제 row 수 20개, position 1~20과 입력 identity를 검증한다.
3. `instrument_id` 기준 union을 만들고 원천별 instrument·issuer·목록 순위를 유지한다.
4. 동일 instrument가 양쪽에 있을 때만 두 RRF 기여도를 합산한다.
5. union의 모든 instrument에 cutoff 기준 hard gate를 적용하고 제외 사유를 기록한다.
6. 동일 issuer의 서로 다른 적격 instrument는 `rrf_score DESC, instrument_id ASC`로
   하나만 남긴다. 서로 다른 share class의 점수는 합산하지 않는다.
7. 남은 전체 union을 같은 순서로 순회하며 섹터 제한을 적용한다.
8. 선정 집합을 `rrf_score DESC, instrument_id ASC`로 다시 정렬해 최종 position을 부여한다.
9. 정확히 20개이면 `SUCCEEDED`, 아니면 `SHORTFALL`을 저장한다.

예를 들어 같은 회사의 주식 A가 Quant 3위, 주식 B가 LLM 5위이면 A는 `1/13`,
B는 `1/15`이며 둘을 더하지 않는다. 둘 다 적격이면 A만 남는다. 동일 주식 A가
두 목록에 있으면 그 주식에 한해 합산한다. 동점에서는 어느 모델도 우대하지 않는다.

Quant에 선정되지 않은 instrument의 `quant_rank`와 `quant_predicted_return`은 `null`이다.
같은 issuer의 다른 종목 예측 수익률을 복사하지 않는다. 반대쪽 LLM 필드에도 같은 원칙을
적용한다. issuer별 대안 종목과 탈락 사유는 감사 기록에 남기며 원천 목록의 순위를
다시 매겨 RRF를 재계산하지 않는다.

### 5.3 정책 적용

기존 cutoff·manifest 기반 membership, 식별자, 가격·기업행위 품질, 거래 가능 여부와
blocking 품질 gate를 재사용한다. 미래에 알려진 거래정지나 현재 상태로 과거 후보를
제외하지 않는다. Quant artifact 조합은 Quant run에서 검증하며 LLM 단독 후보에
Quant 선정·예측값 존재를 추가 자격으로 요구하지 않는다.

주관적 LLM `risk_score` 기준은 추가하지 않는다. 섹터 제한은 기존 MEDIUM_20D와 같은
기본 2개, 부족 시 4개까지 한 번 완화하며 hard gate와 issuer 중복은 완화하지 않는다.
결측 섹터는 `UNCLASSIFIED` 한 그룹으로 계산한다. 완화 여부와 이유를 기록한다.

**승인된 후보 풀 예외:** Fusion은 두 성공 Top 20의 union만 사용한다. 이는 원천 Quant
선정의 전체 적격 universe 순회 규칙을 바꾸는 것이 아니다. 교집합·issuer 중복·위험·섹터
제약으로 최종 수가 부족해도 Quant 21위 이하나 LLM 후순위를 추가하지 않는다.
비교 가능한 두 Top 20의 합의·보완 효과를 평가하기 위한 의도적 제한이며,
최종 20개 생성이 매일 보장되는 것은 아니다.

20개를 만들 수 없으면 적격 부분 결과와 부족 사유를 `SHORTFALL`로 저장한다.
hard gate·섹터 완화·union 경계 테스트로 예외를 검증하고 외부 전달은 금지한다.

### 5.4 실행 identity와 멱등성

- Quant selection run ID와 LLM preselection run ID를 반드시 직접 고정한다.
  날짜별 최신 scoring·evaluation run을 각각 조회해 임의로 결합하지 않는다.
- 두 run의 `execution_context_id`, manifest ID/hash, universe version, target session,
  cutoff, 재현 모드가 같아야 한다. 각 branch가 실제 사용한 evidence subset은 달라도 된다.
- Quant는 `MEDIUM_20D`와 승인된 Top 20 policy, LLM은 이 문서의 신규 event policy여야 한다.
  기존 전체 universe LLM 결과를 신규 정책 결과로 대체하거나 재표시하지 않는다.
- 원천별 scoring·ranking run, model/processor/feature artifact, policy·prompt·evidence
  schema hash와 snapshot lineage를 추적할 수 있어야 한다.
- 입력 불일치·변조·미성공 run은 fail closed한다. 같은 날짜·cutoff라는 이유로 허용하지 않는다.
- source selection IDs와 원천 payload hash, context/manifest identity, Fusion 설정 hash를
  canonical payload로 고정한다. 같은 idempotency key·같은 payload는 기존 run을 반환하고
  다른 payload는 충돌로 실패한다. 동시 요청도 중복 성공 run을 만들지 않는다.

## 6. 데이터베이스 설계

기존 `analytics` 및 `selection` 스키마를 확장한다.

기존 `analytics.llm_ranking_run`, `analytics.llm_evidence_packet`,
`analytics.llm_evidence_link`, `analytics.llm_call_attempt`,
`analytics.llm_instrument_assessment`, `selection.llm_preselection_run` 및 관련 candidate·evidence
구조를 우선 재사용한다. 신규 정책에 필요한 nullable 항목·coverage·screening audit는
명시적 migration으로 확장하고 기존 policy와 기존 성공 run의 의미를 보존한다.

새 논리 엔터티는 Fusion run·candidate·입력/제외 audit다. 예를 들어
`selection.fusion_run`, `selection.fusion_candidate`를 사용할 수 있으나 실제 이름·FK·제약은
기존 migration과 검토 후 확정한다. 별도 `analytics.llm_evaluation*` 체계를 중복 생성하지 않는다.

LLM 실행에는 다음을 기록한다.

- execution context
- input manifest
- universe version
- model deployment/version
- prompt version/hash
- evaluation policy version
- screening 설정·그룹·그룹별 실제 평가 수와 선택 hash
- 평가 항목별 evidence·결측·coverage·가중치 분모
- token usage
- execution status
- evaluation result hash

Fusion 실행에는 다음을 기록한다.

- quantitative scoring run ID
- quantitative selection run ID와 policy version/hash
- LLM ranking run ID, preselection run ID와 policy version/hash
- execution context·manifest ID/hash·universe version·target session·cutoff·재현 모드
- `model_purpose=MEDIUM_20D`, `selection_type=FUSION`
- fusion policy version/hash와 hard/soft constraint 설정
- RRF k
- `requested_count=20`, 실제 selected count·union count·제외/완화 사유
- `SUCCEEDED|SHORTFALL|FAILED`와 failure code
- idempotency key·canonical payload hash·generated/started/finished 시각

최종 후보별 저장 항목:

```text
issuer_id
instrument_id
ticker
quant_rank (nullable; source list position)
quant_rank_overall (nullable; audit only)
quant_predicted_return (nullable; this instrument only)
llm_rank (nullable; source list position)
llm_assessment_rank (nullable; audit only)
llm_score (nullable)
rrf_score
final_rank
selected_by_quant
selected_by_llm
risk_status
sector
quality_status
reason_codes
source_evidence_refs
```

RRF 비교는 유효한 정수 rank와 k에서 얻은 정확한 유리수 값으로 수행하고, 근사 표시값의
반올림으로 가짜 동점을 만들지 않는다. 원천 rank·k를 보존해 저장·API에서 검산할 수 있게 한다.
근사 점수만 저장할 경우에도 순위 결정에 쓴 원천값과 산식 version을 함께 보존한다.

Fusion run·candidate·필수 audit는 단일 transaction으로 저장한다.
중복 issuer·instrument·position, 원천 순위 불일치, RRF 불일치, 누락 lineage가 있으면 rollback한다.
`SUCCEEDED`는 정확히 20개와 position 1~20을 요구한다.
기존 `QUANTITATIVE` selection type·API의 의미를 `FUSION`으로 바꾸지 않는다.

모든 DB 변경은 migration으로 관리한다.

## 7. Candidate API

기존 API의 기본 동작을 변경하지 않는다.

기존 Quant·LLM endpoint와 기본 조회 의미를 유지하며 별도 Fusion 조회 기능을 추가한다.

요구사항:

- 날짜 기준 조회
- `model_purpose=MEDIUM_20D`만 허용하고 SHORT Fusion 요청은 명시적 오류로 처리
- 기존 `QUANTITATIVE`, `LLM_PRESELECTION`과 신규 `FUSION`을 구분
- Top 20 조회
- 모델별 순위 및 통합 점수
- 선정 근거 및 출처
- 실행 상태와 데이터 부족 여부
- 원천 두 selection run ID·context·manifest·policy hash
- LLM의 지원 항목·결측·적용 가중치·EVENT/CONTROL 그룹
- run ID 직접 조회 시 실패·SHORTFALL과 적격 부분 결과도 확인 가능

### 외부 Top 20 전달 계약

기존 오케스트레이터가 Portal 등 현재 외부 수신처로 최종 20개 전체를 전송한다.
새 계약 이름은 `fusion-top20-v1`이며 기존 SHORT_5D 5~10개 계약과 분리한다.
5~10개로 재축소하거나 중간 Quant·LLM 목록을 대신 전달하지 않는다.

전달 envelope는 contract version, `selection_type=FUSION`, `model_purpose=MEDIUM_20D`,
`selection_run_id`로 표현한 Fusion run ID, target session, cutoff, execution context,
원천 두 selection run ID, payload hash, requested/selected count와 후보 20개를 포함한다.
후보에는 instrument·issuer·당시 ticker·position·원천 순위·RRF 점수·reason/evidence 참조를
포함하며 source 원문·secret은 포함하지 않는다. 수신처가 run ID로 상세를 조회한다면
`selection_type`에 맞는 Fusion API를 사용해야 하며 레거시 Quant-only 조회로 해석하지 않는다.

다음 조건을 모두 충족한 결과만 전달한다.

- 대상 날짜·context에 고정된 `SUCCEEDED` Fusion run이며 원천 run도 모두 성공
- `requested_count=selected_count=20`, 실제 row 수 20, position 1~20
- instrument·issuer 중복 없음, source run·manifest·점수·정렬 검증 통과
- 수신처가 신규 계약과 20개 전량 수용을 명시적으로 지원

수신 확인은 contract version·Fusion run ID·payload hash와 정확한 20개 후보 identity를
대조한다. 단순 HTTP 성공이나 '일부 수락'을 전량 전달 성공으로 간주하지 않는다.
계약 불일치·SHORTFALL·FAILED이면 제출하지 않고 명시적 실패/차단 사유를 남긴다.

전달 idempotency key는 계약 version·Fusion run ID·수신처를 구분하고 payload hash에
결합한다. timeout 재시도는 같은 key·payload를 사용한다. 수신처의 동일 요청 재사용과
다른 payload 충돌을 확인하기 전 자동 전달을 활성화하지 않는다.
전달 실패가 이미 저장된 Fusion 성공 결과를 실패로 덮어쓰지는 않는다.

외부 I/O·수신 확인·전달 재시도 상태는 기존 오케스트레이터 control plane에서 관리한다.
Candidate schema에 외부 분석 job·report·비용·재평가 상태를 추가하지 않는다.
Fusion 전달 경로는 수신 확인까지이며 외부 분석 완료 여부를 후보 선정 성공 조건으로 삼지 않는다.
기존 SHORT 경로의 외부 연계 동작은 이 변경으로 수정하지 않는다.

API 경로와 request/response 구조는 기존 router와 schema를 분석한 뒤 결정한다.

## 8. 일일 실행 및 장애 처리

기존 05:30 ET 정기 실행과 Durable Functions 구조를 유지한다.

권장 단계:

```text
Collect
 → Normalize
 → Shared Manifest / Cutoff / Universe
     ├─ Quant Score → Quant Top 20 → Quant Store / API
     └─ Event/Control Screening → Independent LLM Evaluation → LLM Top 20 → LLM Store / API
 → Join successful, identity-matched runs
 → Instrument Union → RRF → Hard Gates / Issuer / Sector Policy
 → Fusion Store / API
 → Successful Top 20 only → Existing Orchestrator → External Consumer ACK
```

Quant와 LLM은 동일한 frozen context·manifest·cutoff·universe를 사용한다.
공통 manifest 준비 후 병렬로 시작하며 LLM 시작이 Qlib export·Quant 모델 검증·추론
성공을 기다리지 않게 한다. 공통 gate 실패는 양쪽을 차단하고 branch 내부 실패는 격리한다.
두 branch가 끝난 뒤 Fusion만 입력 성공 여부에 의존한다.

LLM 호출은 rate limit, TPM/RPM, timeout, retry, backoff를 지원해야 한다.

같은 입력과 설정의 재시도는 이미 저장된 평가 결과를 재사용한다.

### 장애 정책

| Quant | LLM | Fusion | 외부 전달 |
|---|---|---|---|
| 성공 20개 | 성공 20개 | identity 검증·정책 적용 후 성공 또는 SHORTFALL | Fusion 성공 20개만 가능 |
| 성공 20개 | 실패 또는 SHORTFALL | FAILED; Quant 보존 | 차단 |
| 실패 또는 SHORTFALL | 성공 20개 | FAILED; LLM 보존 | 차단 |
| 실패 또는 SHORTFALL | 실패 또는 SHORTFALL | FAILED | 차단 |
| 양쪽 성공 | identity 불일치 | FAILED | 차단 |

공통 control plane의 부분 성공과 Fusion 성공은 다르다. Fusion에 모호한 '부분 성공'을
도입하지 않는다. Fusion 또는 전달 기능이 disabled이면 해당 단계를 실행하지 않고
비활성 상태를 명시하며 기존 branch의 성공·실패 판정을 바꾸지 않는다.

LLM 실패를 숨기기 위해 Quant 결과를 Fusion 결과로 자동 대체하지 않는다.

기존 운영 정량 후보가 LLM 기능 추가 때문에 중단되지 않도록 feature flag를 사용한다.

기본값:

```text
LLM_PRESELECTION_ENABLED=false
FUSION_ENABLED=false
FUSION_EXTERNAL_DELIVERY_ENABLED=false
LLM_PRESELECTION_POLICY_PATH=config/llm_preselection/policy_v1.yaml
RRF_K=10
QUANT_TOP_N=20
LLM_TOP_N=20
FUSION_TOP_N=20
LLM_SCREENING_MAX_ISSUERS=100
LLM_SCREENING_CONTROL_ISSUERS=10
LLM_SCREENING_LOOKBACK_DAYS=7
LLM_SCREENING_EARNINGS_WINDOW_DAYS=7
FUSION_SECTOR_CAP=2
FUSION_RELAXED_SECTOR_CAP=4
```

위 플래그와 policy 선택·설정 검증은 구현 계약이다. 기존 policy 경로가 안전한 기본값이며,
screening·가중치·RPM/TPM·retry는 versioned policy 파일에서 관리한다.
환경변수와 파일의 값이 다르면 오류이며 환경변수로 정책을 몰래 바꾸지 않는다.
Fusion을 활성화하려면 LLM 활성화와 신규 이벤트 policy 경로의 명시적 선택이 필요하다.
기존 LLM policy를 읽은 상태에서 Fusion을 요청하면 호환성 오류를 명시하고 대체하지 않는다.
전달 플래그는 Fusion 활성화와 수신처 계약 검증까지 충족해야 켤 수 있다.
policy file과 환경 설정이 충돌하면 조용히 덮어쓰지 말고 오류로 처리하고 유효 설정 hash를 저장한다.
Top N 20개·MEDIUM 전용은 고정 계약이며 이를 벗어난 설정은 거부한다.
가중치는 양수·합계 100, screening 총 한도와 대조 예약 수는 유효 범위를 검증한다.

기존 스케줄러의 멱등성 및 terminal 상태 처리 규칙을 유지한다.
단, Quant·LLM이 이미 완료되어도 Fusion이나 전달이 미완료면 전체 실행을 조기 종료하지 않는다.
branch별 완료 결과는 재사용하고 누락된 Fusion·전달 단계만 수행한다. stage별 key에
source run ID·policy/contract version을 포함해 기존 중간 Top 20 완료 key와 구분한다.
Durable replay에서 외부 I/O는 activity에서만 실행하고 재전달은 동일 key를 사용한다.

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
- 당시 이용 가능했던 미래 실적 일정과 아직 발표되지 않은 실제 실적 결과 구분
- screening·대조 표본·평가·Fusion·섹터 분류 모두 같은 context의 manifest로 제한
- LLM prompt에서 외부 지식·웹 검색을 금지하고 제공 evidence로 뒷받침되는 주장만 허용

백테스트에서는 실제 과거 LLM 평가 결과가 없으면 데이터 재현 가능성을 확인한다.

검증할 수 없는 과거 데이터는 연구 결과에서 별도 구분한다.
현재 LLM로 과거 evidence를 평가한 결과는 당시 생성된 운영 평가와 구분한다.
source ID 검증만으로 의미적 근거 충족이나 모델 사전학습 지식의 영향을 완전히 증명했다고
주장하지 않으며 사용 deployment·생성 시각·재구성 한계를 metadata에 남긴다.

## 10. 테스트

필수 단위·통합 테스트:

1. 기본 `k=10` 산식, 한쪽 누락, 동일 instrument 양쪽 기여도
2. 단독 1위가 공통 20위보다 높음; `k=60` 비교 실험과 운영 기본값 구분
3. 0·음수·중복·범위 밖 rank, 양쪽 rank 누락, 잘못된 k 차단
4. Quant `rank_overall`·LLM `assessment_rank`가 아닌 목록 position을 사용
5. 같은 issuer의 다른 share class는 비합산, 높은 적격 RRF 하나만 선택
6. 같은 issuer·같은 점수는 instrument ID로 결정; 다른 share class의 예측값 복사 금지
7. RRF의 정확한 값 비교, 동점 대칭성, 저장·API·최종 position 결정성
8. 섹터당 2개·부족 시 4개 완화, 결측 섹터, 최종 RRF 재정렬
9. hard gate는 완화하지 않으며 issuer·instrument 중복 금지
10. union 밖에 적격 후순위가 있어도 추가하지 않음; 부족하면 SHORTFALL
11. 최근 7일 선별의 경계값, 동일 revision 재관찰, 유형별 최대 1점
12. cutoff 전에 알려진 전후 7일 실적 일정 허용, 미래 실적 결과 차단
13. 최대 90 EVENT·10 CONTROL, 대조 표본 재실행 결정성·운영 Top 20 포함 가능
14. 그룹 부족 시 강제 충원·quota 임의 이전 금지; 선별·제외 audit 보존
15. 신규 LLM packet에 OHLCV·가격 context·Alpha158·Quant 점수/순위가 없음
16. 근거 있는 3·4·5개 항목의 가중치 재정규화; 3개 미만은 순위 제외
17. 근거 없는 항목의 null·결측 사유, 유한 점수 범위·반올림·저장값 정렬 일치
18. strict JSON, 타 issuer·미제공 evidence·근거 없는 비결측 점수 차단
19. manifest 밖·cutoff 이후·운영 재현 observed_at 위반 차단
20. source run·context·manifest·universe·session·cutoff·재현 모드 불일치 차단
21. 기존 LLM policy·SHORT_5D run을 Fusion 입력으로 사용하지 않음
22. Quant 실패에도 LLM 완료, LLM 실패에도 Quant 완료; 공통 gate 실패는 양쪽 차단
23. 실패·SHORTFALL을 Fusion 성공이나 다른 run fallback으로 표시하지 않음
24. 동일 key·payload 재사용, 다른 payload 충돌, 동시 중복 생성 방지
25. Fusion run·candidate·audit 저장 오류 전체 rollback과 부분 성공 저장 방지
26. 기존 Quant·LLM API, 레거시 LLM policy·SHORT_5D 경로와 비활성 플래그 회귀 검증
27. 원천 branch 완료 재사용 후 미완료 Fusion·전달 재개; Durable replay 중복 I/O 방지
28. 성공한 최종 20개 전량 전달, 재축소 금지, 중간 목록·SHORTFALL·FAILED 전달 차단
29. 외부 계약 version·run·payload hash·20개 identity ACK 대조, 일부 수락은 실패
30. 외부 timeout 재시도 멱등성, 전달 실패 시 Fusion 결과 보존, SHORT 전달 계약 보존

Mock LLM을 이용해 외부 API 호출 없이 테스트할 수 있도록 구성한다.
외부 수신처의 20개 계약은 mock contract test 후 명시적 승인하의 연동 검증으로 확인한다.

## 11. 연구 및 백테스트

다음 세 가지 후보 정책을 같은 session·context·universe·비용 가정으로 비교한다.

- E1: Quant Top 20
- E2: 신규 이벤트·대조 표본 LLM Top 20
- E3: RRF Fusion Top 20, 기본 k=10과 별도 실험 version

기존 전체 universe LLM 정책과의 비교도 별도 policy ID로 구분한다.
학습형 Fusion(E4)은 이번 구현 범위에서 제외한다.

비교 지표:

- 20D raw return을 기본으로 하고 5D raw return은 보조 지표
- SPY 대비 초과수익률은 optional 비교 지표이며 필수 입력이 아님
- 동일 순위 평가 universe를 명시한 Rank IC
- Top-20 net return
- 최대낙폭
- 후보 중복률
- 섹터 집중도
- SHORTFALL 비율·선정 수·union/issuer 중복·hard gate/섹터별 제외 수
- EVENT/CONTROL별 coverage·선정 수·지원 평가 항목 수와 가중치 분모
- 토큰 사용량 및 LLM 비용

기존 t+1 시가 진입, 거래비용 및 Purged Walk-Forward 검증 원칙을 유지한다.

미래 수익률을 Fusion 가중치 또는 후보 선정에 사용하지 않는다.
최대낙폭은 versioned cohort 평가 규칙과 portfolio 평가를 구분한다.
포트폴리오 성과를 주장하려면 공통 하네스의 자금·보유·중첩·거래비용 규칙을 먼저 정의한다.
외부 TradingAgents의 분석·리포트·비용·재평가 지표는 구현하지 않는다.

## 12. 구현 순서

### Phase 1 — Contract & Design

- 저장소 분석
- 승인된 하네스 범위·union 예외와 실제 코드의 차이 확인
- 데이터 흐름 설계
- 기존 LLM schema 재사용·확장과 Fusion schema/API·source identity 계약
- 외부 수신처의 `fusion-top20-v1` 수용·ACK·멱등성 계약 합의
- feature flag 설계

### Phase 2 — LLM Evaluation

- 기존 policy 보존과 신규 event policy·prompt·evidence schema 분리
- 7일 이벤트 screening·90/10 결정적 운영 대조 표본
- 비가격 LLM packet, 최소 3개 항목 근거와 가중치 재정규화
- Azure OpenAI 호출
- JSON validation
- 평가 결과 및 근거 저장

### Phase 3 — RRF Fusion

- 기존 성공 Quant Top 20과 신규 정책 LLM Top 20 고정·identity 검증
- 목록 순위·k=10, instrument 단위 합산·issuer 대표 하나 선정
- union 한정 hard gate·섹터 2/4 정책과 SHORTFALL
- 원천 provenance·정확한 순위·원자 저장·동시 멱등성

### Phase 4 — Integration

- Candidate API
- 일일 pipeline 연계
- Durable Functions 호환성
- 실패·재실행 처리
- 수신처 변경을 외부 의존성으로 두고 기존 전달 어댑터에 versioned Top 20 제출·ACK 연결
- 원천 완료·Fusion 완료·전달 완료의 재개 단위와 key 분리
- SHORT 레거시 전달 보존과 신규 전달 기본 비활성

### Phase 5 — Validation

- 단위 및 통합 테스트
- 기존 Quant 경로 회귀 테스트
- mock 기반 E2E
- 제한된 shadow 실행
- 성능 및 비용 측정
- 수신처 20개 전량 수용·timeout 재전달·payload 충돌 검증 후에만 전달 활성화

## 13. 완료 조건

다음 조건을 충족해야 구현 완료로 간주한다.

- 기존 Quant 경로 정상 동작
- 기존 LLM policy 보존과 신규 이벤트·대조 policy의 독립 LLM Top 20 생성
- Fusion은 MEDIUM_20D 전용이며 SHORT_5D 정량·기존 전달 경로 보존
- k=10·목록 순위·동일 instrument 합산·issuer 하나·섹터 2/4 계약 준수
- union 안에서 최종 20개 성공 또는 명시적 SHORTFALL; 후순위 강제 추가 없음
- 최소 3개 근거 항목과 가중치 재정규화·결측 metadata 검증
- 후보별 모델 순위 및 근거 조회
- PostgreSQL 실행 이력과 provenance 보존
- 동일 실행 재시도 시 중복 결과 없음
- 미래 데이터 누수 방지 테스트 통과
- LLM 장애 시 기존 운영 보호
- Quant 장애 시 LLM 독립 실행·결과 보존
- API 하위 호환성 유지
- 성공 Fusion 20개 전체의 versioned 외부 전달·ACK·재시도 멱등성 검증
- 외부 전달 실패와 후보 선정 성공의 상태 분리; 외부 분석 기능 확장 없음
- 테스트 및 문서 업데이트 완료

## 14. Agent 작업 지침

1. 먼저 실제 저장소를 분석하고 현재 구현 상태를 확인한다.
2. 문서와 코드의 차이를 보고한다.
3. [PROJECT-HARNESS.md](./PROJECT-HARNESS.md)의 승인된 Fusion 범위·예외를 확인하고
   다른 충돌은 구현 전에 보고한다. 이 문서가 hard gate를 완화한다고 해석하지 않는다.
4. 필요한 계약 변경과 구현 계획을 작성한다.
5. 기존 정량 모델을 수정하지 않는 최소 변경 구조를 우선한다.
6. 기존 코드 패턴, DB migration, API schema 및 테스트 구조를 재사용한다.
7. 하드코딩된 모델 배포명, API 키, 프롬프트 설정을 추가하지 않는다.
8. 운영 DB migration 및 실제 외부 API 실행은 명시적인 승인 없이 수행하지 않는다.
9. 기능을 feature flag 뒤에 구현하고 기본 비활성화 상태로 유지한다.
10. 각 Phase 완료 시 변경 파일, 테스트 결과, 미해결 문제를 보고한다.
11. 기존 run·policy·외부 SHORT 계약을 덮어쓰거나 재해석하지 않는다.
12. 사용자 요청에 따른 코드·설정·스키마·문서 변경마다
    [CHANGELOG.md](./CHANGELOG.md)에 항목별 한 줄을 추가한다.

최종 산출물은 구현 코드, DB migration, 테스트, 설정 예시, 업데이트된 아키텍처 문서 및 운영 가이드를 포함한다.

**우선 Phase 1의 저장소 분석과 구현 계획부터 수행하고, 코드 변경 전 변경 범위와 하네스 충돌 사항을 보고하라.**

## 15. 구현·검증 상태

- 구현: 별도 [이벤트 정책](./config/llm_preselection/policy_event_v2.yaml),
  [정확한 Fusion](./src/sp500_candidate_engine/fusion/), migration 023,
  [Fusion API](./backend/app/routers/fusions.py), 형제 실행 이후 병합과 versioned 전달 어댑터.
- 코드 기본값: LLM v1, LLM·Fusion·외부 전달 OFF. 승인된2026-10-17 운영은 event v2·
  Fusion k=10·전량 전달 ON이며 독립 stage API/CLI·migration024까지 배포·검증했다.
- 검증: mock LLM·수신처와 실제 SQL을 실행하는 격리 PostgreSQL-WASM으로 선정·저장·
  실패 격리·재사용·API·20개 envelope/ACK를 검증한다. 운영 PostgreSQL 16과 실제
  Azure OpenAI·수신처의 연동·처리량·비용 검증을 대신한 것으로 표현하지 않는다.
- 로컬 결과: 전체 테스트 492건, Ruff, 신규 경로 22개 모듈의 Python 3.11 대상 타입 검사,
  23개 migration 구문·실행·재적용, 실제 transaction rollback·멱등 충돌·배치 재사용,
  MEDIUM 20개와 레거시 5~10개 수량 계약을 검증했다. Backend·Durable Bicep은
  로컬 컴파일을 통과했으며 기존 App Service API 타입 경고 2건이 남아 있다.
- 활성화 선행 조건: 승인 후 migration·코드 배포, 신규 LLM policy 선택과 shadow 비교,
  Backend/Durable 정책 hash 일치, 수신처 신규 endpoint의 전량 ACK·멱등성 검증.
  실제 외부 서비스가 준비되지 않았다면 전달은 계속 차단한다.
- 현재 구현·운영 증거와 일일 실패 점검은 [운영 점검서](DAILY-PIPELINE-RUNBOOK.md)를 따른다.
  [결과 스키마 샘플](RESULT-SCHEMA.sample.md)의8~12절 explanation 확장은
  별도 미구현 설계다. 독립 실행 구현·배포와 같은 완료 상태로 취급하지 않는다.