# 현재 종목 후보 결과 스키마와 선정 근거 샘플

- 작성일: 2026-10-17
- 기준: 현재 로컬 작업 트리의 API schema·조회 repository·결과 저장 코드.
- 목적: 종목별 정량 점수 → LLM 평가 근거 → Fusion 산식과 고정 run별 설명 계약을 정리한다.
- 문서 구분: 1~7절은 기존 v1 계약, 8~12절은 구현된 선정 근거 snapshot·v2 조회와
  포털의 별도 연동 메모다. 기존 v1 계약은 변경하지 않는다.
- 작업 분리: 선정 근거 작업은 파이프라인 분리 작업과 별도로 구현한다.
  기존 실행 구조에서 적용 가능해야 하며, 독립 Job·신규 orchestrator·실행 API 전환을
  선행 조건으로 요구하지 않는다.
- 독립 stage API/CLI·상태·재시도는 구현·배포돼 있다. 신규 explanation snapshot·
  과거일 LLM 강제 하네스·v2 설명 조회는 로컬 구현·검증 대상이며 아직 운영에 배포하지 않았다.
- 모든 UUID·종목·점수·문장은 설명용 가상 값이다. 운영 DB를 조회한 샘플이 아니다.
- 범위는 Candidate Engine의 후보 선정 결과다. 외부 종목 분석 보고서·매매 판단의
  응답 스키마는 다루지 않는다. 포털에는 후보 근거 표시를 위한 연동 메모만 남기며
  포털의 실제 변경은 별도 작업이다.

## 1. 먼저 알아둘 현재 구조

현재는 종목 하나에 모든 설명이 들어 있는 통합 결과가 아니라 세 결과를 연결하는 구조다.

```text
Quant 후보
  selection_run_id + instrument_id
           │
           ├── Fusion.quant_selection_run_id
           │
LLM 후보   │
  run_id + instrument_id
           │
           └── Fusion.llm_preselection_run_id
                         │
                         ▼
                 Fusion 최종 후보
                 fusion_run_id + instrument_id
```

| 결과 | 조회 API | 응답 형태 |
|---|---|---|
| 정량 후보 | `GET /api/v1/candidates?selection_run_id={quant_run_id}&instrument_id={instrument_id}` | `Page[Candidate]`: `items`, `next_cursor` |
| LLM 원천 run | `GET /api/v1/llm-preselections/{run_id}` | `LLMPreselection`: run 정보와 `candidates` |
| Fusion 최종 run | `GET /api/v1/fusion-selections/{run_id}` | `FusionRun`: 원천 run 참조와 `candidates` |
| Fusion 외부 전달 | `GET /api/v1/fusion-selections/{run_id}/handoff` | `fusion-top20-v1` envelope |
| 독립 실행 상태 | `GET /api/v1/candidate-stage-runs/{stage_run_id}` | 실행 제어 상태·고정 계약 hash·사업 결과 ID |

정량 조회는 종목 row마다 run 메타데이터를 반복해서 반환한다. LLM·Fusion 조회는
run 메타데이터 아래 후보 배열을 반환한다.

**아래 JSON은 각각 후보 한 건의 완전한 객체다.** 성공 run 전체 응답은 아니다.
실제 성공 MEDIUM run에는 후보 20개가 필요하며, 아래 한 건만 넣고
`selected_count=20`인 성공 run으로 제출하면 안 된다.

## 2. 정량 모델 후보: 현재 API 후보 한 건

```json
{
  "selection_run_id": "10000000-0000-4000-8000-000000000001",
  "selection_type": "QUANTITATIVE",
  "price_session_date": "2026-10-15",
  "cutoff_at": "2026-10-16T09:30:00Z",
  "generated_at": "2026-10-16T09:40:00Z",
  "valid_until": null,
  "scoring_run_id": "20000000-0000-4000-8000-000000000001",
  "model_version_id": "30000000-0000-4000-8000-000000000001",
  "model_name": "example-lightgbm-medium",
  "model_version": "example-v1",
  "model_purpose": "MEDIUM_20D",
  "prediction_horizon_sessions": 20,
  "return_policy": "PRICE_RETURN",
  "promotion_status": "CHAMPION",
  "score_semantics": "PREDICTED_20D_RETURN",
  "policy_version": "medium-20d-top20-v1",
  "status": "SUCCEEDED",
  "selected_count": 20,
  "requested_count": 20,
  "instrument_id": "40000000-0000-4000-8000-000000000001",
  "issuer_id": "50000000-0000-4000-8000-000000000001",
  "ticker": "EXAMPLE",
  "company_name": "Example Issuer",
  "sector": "Industrials",
  "position": 3,
  "score": 0.0432,
  "predicted_return": 0.0432,
  "rank_overall": 8,
  "score_percentile": 0.986,
  "rank_sector": 2,
  "quality_status": "OK",
  "latest_data_at": "2026-10-16T09:30:00Z",
  "reasons": [
    {
      "reason_code": "MODEL_TOP_RANK",
      "priority": 1,
      "event_revision_id": null
    },
    {
      "reason_code": "MODEL_TOP_PERCENTILE",
      "priority": 2,
      "event_revision_id": null
    }
  ]
}
```

### 점수·순위 설명

| 필드 | 의미 |
|---|---|
| `score`, `predicted_return` | 현재 정량 저장 경로에서는 같은 예측 수익률 값. `0.0432`는 모델 label 정의 기준 약 `+4.32%` 예상 수익률이지 상승 확률 4.32%가 아니다. |
| `score_semantics` | 이 값이 `PREDICTED_20D_RETURN`이라는 의미. SHORT 결과와 혼동하지 않는다. |
| `prediction_horizon_sessions` | 예측 horizon. 정확한 진입·청산 시점은 고정된 model/label 계약을 따른다. |
| `rank_overall` | scoring run의 전체 유효 점수 순위. 예시는 8위. |
| `score_percentile` | `0~1` 단위 상대 위치. 현재 계산은 `(N - rank + 1) / N`; 예시는 N=500일 때 `493/500=0.986`. 확률·confidence가 아니다. |
| `rank_sector` | 해당 섹터 안의 점수 순위. 예시는 2위. |
| `position` | issuer 중복·섹터 제약을 적용한 원천 정량 후보 목록 내 위치. 예시는 3위이며 전체 점수 8위와 다를 수 있다. |
| `promotion_status` | 조회되는 모델 registry의 승격 상태. 후보에 대한 확신이나 매수 등급이 아니다. |
| `latest_data_at` | 현재 선정 저장 코드에서는 `cutoff_at`으로 채운다. 개별 원천 데이터의 실제 마지막 업데이트 시각이라고 확대 해석하지 않는다. |

### 현재 선정 사유

정량 policy는 유효 후보를 점수 내림차순·instrument ID 동점 순으로 순회하면서
issuer 중복과 섹터 제한을 적용한다. MEDIUM 기본 후보는 정확히 20개이며, 양의 예측만을
요구하지 않는다.

| reason code | 현재 의미와 주의점 |
|---|---|
| `MODEL_TOP_RANK` | 순위 기반 정량 선정 경로로 선택됐다. 전체 점수 순위가 반드시 20위 이내라는 뜻은 아니다. |
| `MODEL_TOP_PERCENTILE` | percentile을 가진 상위 후보라는 일반 코드. 이 코드 자체에 별도 percentile 임계값은 없다. |
| `NON_POSITIVE_PREDICTION` | 선정됐지만 예측 수익률이 0 이하이다. 이 policy는 상대 순위 기준이므로 가능하다. |
| `SECTOR_CAP_RELAXED` | 기본 섹터 한도로 부족해 완화 단계에서 추가됐다. |

현재 데이터로 만들 수 있는 설명 예:

> MEDIUM_20D 모델의 예측 수익률은 +4.32%, 전체 점수 순위는 8위입니다.
> issuer·섹터 제약을 반영한 정량 후보 목록에서는 3위로 선정됐습니다.

**현재 이 설명 문장 자체를 반환하는 필드는 없다.** 점수·순위와 코드를 이용해
설명 계층에서 구성해야 한다. 또한 “어떤 Alpha158 특징이 예측을 올렸는지”를 나타내는
종목별 SHAP/feature contribution은 이 후보 결과에 없다. 선정 규칙 설명과 모델의
특징별 예측 기여 설명을 구분해야 한다.

## 3. LLM 후보: 현재 이벤트 v2 API 후보 한 건

아래는 `LLMPreselection.candidates`의 한 원소다. 예시의
`run_id=6000...0001`은 LLM 선정 run ID이며, 상위의 `llm_ranking_run_id`와 다르다.

```json
{
  "run_id": "60000000-0000-4000-8000-000000000001",
  "instrument_id": "40000000-0000-4000-8000-000000000001",
  "position": 2,
  "score": 80.0,
  "first_stage_rank": 2,
  "final_rank": 2,
  "evidence_quality": "HIGH",
  "reason_codes": ["EVIDENCE_BACKED"],
  "symbol": "EXAMPLE",
  "company_name": "Example Issuer",
  "sector": "Industrials",
  "evidence": [
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000001",
      "source_snapshot_id": "80000000-0000-4000-8000-000000000001",
      "source_kind": "EARNINGS",
      "entity_key": "example-earnings-2026q3",
      "source_available_at": "2026-10-14T12:00:00Z",
      "observed_at": "2026-10-14T12:05:00Z",
      "event_at": "2026-10-15T12:00:00Z",
      "priority": 1
    },
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000002",
      "source_snapshot_id": "80000000-0000-4000-8000-000000000002",
      "source_kind": "NEWS",
      "entity_key": "example-business-update",
      "source_available_at": "2026-10-14T13:00:00Z",
      "observed_at": "2026-10-14T13:05:00Z",
      "event_at": "2026-10-14T13:00:00Z",
      "priority": 2
    },
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000003",
      "source_snapshot_id": "80000000-0000-4000-8000-000000000003",
      "source_kind": "NEWS",
      "entity_key": "example-contract-update",
      "source_available_at": "2026-10-14T14:00:00Z",
      "observed_at": "2026-10-14T14:05:00Z",
      "event_at": "2026-10-14T14:00:00Z",
      "priority": 3
    }
  ],
  "screening_group": "EVENT",
  "screening_event_score": 2,
  "supported_count": 3,
  "weight_denominator": 70,
  "sub_scores": {
    "earnings": 80.0,
    "business": 72.0,
    "event": 90.0,
    "financial": null,
    "industry": null
  },
  "missing_reasons": {
    "financial": "입력 packet에 재무 평가를 뒷받침할 충분한 수치 근거가 없음",
    "industry": "입력 packet에 산업 비교 근거가 없음"
  },
  "criterion_evidence": [
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000001",
      "criterion": "earnings",
      "reason": "제공된 실적 자료에 평가 가능한 실적 변화 근거가 있음"
    },
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000002",
      "criterion": "business",
      "reason": "제공된 사업 업데이트에 사업 진행을 평가할 근거가 있음"
    },
    {
      "evidence_link_id": "70000000-0000-4000-8000-000000000003",
      "criterion": "event",
      "reason": "제공된 계약 관련 이벤트에 사업 영향 평가 근거가 있음"
    }
  ]
}
```

### 두 종류의 LLM 점수를 구분

**1. 평가 대상 screening 점수**

- `screening_group=EVENT`: 최근 이벤트가 있어 LLM 평가 pool에 들어간 그룹.
- `screening_event_score=2`: 예시에서는 실적 일정과 뉴스, 두 이벤트 유형에 각 1점.
  뉴스가 두 건이라고 뉴스 점수를 2점으로 세지 않는다.
- 최근 7일 공개 정보 또는 cutoff까지 알려진 실적 일정의 전후 7일 조건을 사용한다.
  EVENT/CORPORATE_ACTION은 같은 한 유형으로 묶는다.
- 운영 policy는 이벤트 issuer 최대 90개와 결정적 무이벤트 대조 issuer 최대 10개다.
  이 점수는 pool 선별용이며 **LLM 최종 평가 점수에 가산하지 않는다.**
- 상위 run의 `screening_summary`에서 `issuer_id`·`instrument_id`를 연결하면
  qualifying evidence의 종류·entity key·snapshot·공개 시각·평가 pool 선택 여부를 확인할 수 있다.
  여기의 `selected`는 최종 Top 20 선정 여부가 아니다.

**2. 근거 기반 LLM 평가 점수**

| 항목 | policy 가중치 | 가상 점수 | 계산 반영 |
|---|---:|---:|---|
| `earnings` | 25 | 80 | 반영 |
| `business` | 25 | 72 | 반영 |
| `event` | 20 | 90 | 반영 |
| `financial` | 15 | null | 결측, 분모에서도 제외 |
| `industry` | 15 | null | 결측, 분모에서도 제외 |

```text
supported_count = 3
weight_denominator = 25 + 25 + 20 = 70
LLM score = (80×25 + 72×25 + 90×20) / 70
          = 5600 / 70
          = 80.0000
```

최소 3개 항목에 유효한 동일 종목 evidence가 있어야 총점을 계산한다. 없는 항목을 0점으로
처리하거나 가격·정량 점수·외부 지식으로 보완하지 않는다. 서버가 가중 합을 계산하고
소수점 4자리 half-even으로 반올림한다. LLM이 총점을 직접 정하는 구조가 아니다.
`score=80`은 rubric 평가 점수이며 예상 수익률·상승 확률·confidence가 아니다.

이벤트 v2는 평가 점수 내림차순·instrument ID로 정렬해 유효한 상위 20개를 고른다.
`first_stage_rank`는 평가 단계 순위, `position/final_rank`는 선정 목록 순위다.
기존 v1과 이벤트 v2는 의미·가용 필드가 다를 수 있으므로 상위 `policy_version`과
`evidence_schema_version`을 반드시 함께 확인한다.

### 현재 API에서 설명할 수 있는 내용

> 실적·뉴스 두 이벤트 유형으로 평가 대상에 포함됐고, 실적·사업·이벤트 3개 항목의
> 근거가 확인됐습니다. 재무·산업 항목은 근거 부족으로 제외한 뒤 가중치를 재정규화해
> 80점으로 평가됐으며 LLM 후보 2위입니다.

이 설명에 필요한 항목별 이유는 이미 `criterion_evidence[].reason`에 있다.
다만 이 문장 자체를 API가 반환하지는 않는다.

### DB에는 있지만 현재 후보 API에는 없는 필드

`analytics.llm_instrument_assessment`는 `rationale`, `uncertainty`, `output_hash`도 저장한다.
현재 `LLMPreselectionCandidate`와 조회 SQL은 이 세 필드를 응답에 포함하지 않는다.

- 전체 LLM 종합 설명을 UI에 그대로 노출하려면 `rationale`의 API 노출을 별도로 설계해야 한다.
- `criterion_evidence`의 이유와 모델 종합 `rationale`는 같은 필드가 아니다.
- `evidence`에는 원천 ID·시각 등 lineage가 있지만 원문 내용·기사 제목·외부 URL 필드는 없다.
  현재 응답만으로 “클릭 가능한 원문 기사”가 이미 제공된다고 가정하면 안 된다.
- 근거 없는 항목의 `criterion_evidence`가 있더라도 해당 항목이 null이면 점수 기여는 없다.
  설명용 한계 인용과 실제 scored criterion을 구분한다.

## 4. Fusion 최종 후보: 현재 API 후보 한 건

아래는 `FusionRun.candidates`의 한 원소다. 앞의 같은 instrument가
Quant 목록 3위·LLM 목록 2위로 들어간 예시다.

```json
{
  "instrument_id": "40000000-0000-4000-8000-000000000001",
  "issuer_id": "50000000-0000-4000-8000-000000000001",
  "ticker": "EXAMPLE",
  "sector": "Industrials",
  "position": 1,
  "quant_rank": 3,
  "quant_rank_overall": 8,
  "quant_predicted_return": 0.0432,
  "llm_rank": 2,
  "llm_assessment_rank": 2,
  "llm_score": 80.0,
  "rrf_score": 0.16025641025641027,
  "rrf_numerator": 25,
  "rrf_denominator": 156,
  "selected_by_quant": true,
  "selected_by_llm": true,
  "quality_status": "OK",
  "risk_status": "PASSED",
  "reason_codes": ["RRF_BOTH"],
  "source_evidence_refs": [
    "70000000-0000-4000-8000-000000000001",
    "70000000-0000-4000-8000-000000000002",
    "70000000-0000-4000-8000-000000000003"
  ]
}
```

### Fusion 계산

```text
상위 run의 rrf_k = 10
정량 기여 = 1 / (10 + quant_rank) = 1/13
LLM 기여  = 1 / (10 + llm_rank)   = 1/12
RRF       = 1/13 + 1/12
          = 25/156
          ≈ 0.16025641025641027
```

**RRF에 들어가는 것은 원천 후보 목록 순위 `3`과 `2`다.**
정량 전체 점수 순위 `8`이나 예측 수익률 `0.0432`, LLM 점수 `80`을 직접 합산하지 않는다.
`rrf_numerator/rrf_denominator`는 정확한 유리수 값이고 `rrf_score`는 조회용 실수 값이다.

| 필드 | 현재 의미 |
|---|---|
| `position` | Fusion 결과의 최종 위치. 예시 1위는 전체 가상 후보 집합에서 그렇게 선정됐다고 가정한 값이며 이 한 건만으로 1위를 증명할 수는 없다. |
| `quant_rank`, `llm_rank` | 각 원천 Top 20 안의 position. RRF의 직접 입력. |
| `quant_rank_overall` | 원천 정량 점수 전체 순위. 참고용이며 RRF 직접 입력 아님. |
| `llm_assessment_rank` | 현재 저장 시 LLM 후보의 `first_stage_rank`에서 복사한 값. |
| `selected_by_quant`, `selected_by_llm` | 동일 instrument가 해당 원천 Top 20에 있는지 여부. 각각 독립적인 매수 추천 플래그가 아니다. |
| `quality_status=OK`, `risk_status=PASSED` | 현재 Fusion 저장 코드가 선정된 후보에 넣는 gate 통과 표시. 별도 위험 점수·손실 확률·투자 안전 보증이 아니다. |
| `reason_codes` | `RRF_BOTH`, `RRF_SINGLE`, 필요 시 `SECTOR_CAP_RELAXED`. |
| `source_evidence_refs` | LLM 원천 후보의 선택 evidence link ID. 원문·항목별 이유를 담는 객체가 아니다. |

한쪽 원천에만 있는 종목도 union에서 선정될 수 있다. 예를 들어 Quant에만 있으면
`selected_by_llm=false`, `llm_rank/llm_assessment_rank/llm_score=null`,
`source_evidence_refs=[]`, `reason_codes=["RRF_SINGLE"]`이고 RRF는 정량 기여 하나다.
이 null은 “LLM 0점”이나 “LLM이 부정 평가”를 뜻하지 않는다.

현재 데이터로 만들 수 있는 설명 예:

> 정량 후보 3위와 LLM 후보 2위에 동시에 포함됐습니다.
> k=10인 RRF에서 정량 1/13, LLM 1/12를 더한 25/156으로 병합됐고,
> 적격성·issuer 중복·섹터 제약을 적용한 최종 후보 목록의 1위입니다.

## 5. 후보 바깥의 run 스키마

### LLMPreselection 상위 객체

| 필드 | 설명 |
|---|---|
| `run_id`, `llm_ranking_run_id` | 선정 run과 평가 run의 구분 |
| `execution_context_id` | 고정 입력 context |
| `price_session_date`, `cutoff_at`, `generated_at`, `valid_until`, `created_at` | 대상 session·정보 cutoff·생성/유효/저장 시각 |
| `policy_version`, `policy_hash` | rubric·screening·선정 정책 identity |
| `prompt_version`, `deployment`, `evidence_schema_version` | 평가 prompt·모델 deployment·근거 계약 version |
| `requested_count`, `selected_count` | 목표 개수와 실제 선정 개수 |
| `status`, `ranking_status`, `failure_code` | 선정과 평가의 성공·실패 구분 |
| `screening_summary` | issuer별 평가 pool 진입 결정·이벤트 근거 audit |
| `candidates` | 위 LLM 후보 객체 배열 |

### FusionRun 상위 객체

| 필드 | 설명 |
|---|---|
| `fusion_run_id`, `execution_context_id` | 최종 실행과 고정 입력 identity |
| `quant_selection_run_id`, `llm_preselection_run_id` | 실제 사용한 두 원천 선정 run ID |
| `price_session_date`, `cutoff_at`, `generated_at`, `created_at` | 대상 session·정보 cutoff·생성/저장 시각 |
| `model_purpose`, `selection_type` | 각각 `MEDIUM_20D`, `FUSION` |
| `policy_version`, `config_hash`, `rrf_k` | Fusion 정책 identity와 RRF 상수 |
| `requested_count`, `selected_count`, `union_count` | 목표 20개·실제 개수·원천 union 개수 |
| `status`, `failure_code` | `SUCCEEDED/SHORTFALL/FAILED`와 실패 이유 |
| `sector_cap_relaxed` | 결과 전체에서 섹터 완화를 사용했는지 여부 |
| `provenance` | context/manifest·source hash·정량/LLM lineage·정책 검증 정보 |
| `payload_hash` | Fusion 저장 입력·provenance·policy를 고정한 hash |
| `candidates` | 위 Fusion 후보 객체 배열 |

`provenance`는 현재 `dict[str, object]`인 유연한 필드이지 강한 nested Pydantic 계약은 아니다.
그 안의 `quant_lineage`에는 모델·processor·feature·export·정량 policy 정보,
`llm_lineage`에는 ranking·policy·prompt·deployment·evidence schema 등이 저장된다.
따라서 사용자 표시 계약으로 그대로 노출·의존하기보다는 필요한 필드의 versioned
조회 계약을 별도로 정의하는 것이 적절하다.

탈락 후보별 `exclusion_reasons`, RRF 분자/분모, 선택 여부 등은
`selection.fusion_audit`에 저장된다. 현재 Fusion API는 이 audit 배열을 직접 반환하지 않는다.
최종 후보 배열만으로 “다른 종목 대신 왜 이 종목을 골랐는가” 전체를 복원할 수는 없다.

### 외부 전달 envelope와의 차이

handoff는 `contract_version=fusion-top20-v1`과 `selection_run_id`라는 이름으로
Fusion run ID를 전달한다. 원천 두 run ID·context·cutoff·policy/config·`rrf_k`·개수·상태와
동일한 Fusion 후보 배열을 포함하지만 전체 `provenance`와 LLM 상세 객체는 포함하지 않는다.

handoff의 `payload_hash`는 **envelope 자체의 canonical hash**다. 위 FusionRun의
저장 입력 `payload_hash`와 계산 대상이 다르므로 같은 값이라고 가정하면 안 된다.
LLM 항목별 이유를 외부 전달에 추가하려면 이 문서 작성과 별도로 계약 version·hash·
수신처 수용 검증을 설계해야 한다.

### 독립 stage 실행 상태와 사업 결과 ID

`POST /api/v1/candidate-stage-runs`는 Quant·LLM·Fusion 중 한 단계를 실행하며,
`GET /{stage_run_id}`와 `POST /{stage_run_id}/retry`는 해당 prefix에서 상태·재시도를 제공한다.
세 API 모두 서버 인증, 쓰기 API는 Idempotency-Key를 요구한다.

다음은 후보 배열이 아니라 **독립 Fusion stage 상태의 완전한 가상 응답**이다.
`stage_run_id`는 제어 이력이고 `result.selection_run_id/fusion_run_id`가 실제 최종 결과다.
stage 결과가 원천 결과를 재사용해도 stage ID와 원천 선정 ID를 합치지 않는다.

```json
{
  "stage_run_id": "b0000000-0000-4000-8000-000000000001",
  "stage": "FUSION",
  "target_session": "2026-10-15",
  "execution_context_id": "90000000-0000-4000-8000-000000000001",
  "model_purpose": "MEDIUM_20D",
  "retry_of_run_id": null,
  "status": "SUCCEEDED",
  "contract_hash": "1111111111111111111111111111111111111111111111111111111111111111",
  "input_hash": "2222222222222222222222222222222222222222222222222222222222222222",
  "created_at": "2026-10-16T09:40:00Z",
  "started_at": "2026-10-16T09:41:00Z",
  "finished_at": "2026-10-16T09:42:00Z",
  "failure_code": null,
  "result": {
    "selection_run_id": "a0000000-0000-4000-8000-000000000001",
    "scoring_run_id": null,
    "model_version_id": null,
    "llm_ranking_run_id": null,
    "fusion_run_id": "a0000000-0000-4000-8000-000000000001",
    "candidate_count": 20,
    "reused": true
  }
}
```

- 상태는 PENDING·RUNNING·SUCCEEDED·SHORTFALL·FAILED다. 실패·SHORTFALL만 새 stage ID로 retry한다.
- 같은 key·요청은 원래 stage를 반환한다. 다른 payload 또는 바뀐 retry 계약은 충돌이다.
- API 재시작으로 잃은 API 소유 stage는 `FAILED/INTERRUPTED`로 기록한다.
- 독립 stage는 수집·학습·다른 분기·외부 분석을 자동 시작하지 않는다.
- 조회 응답은 contract/input **hash**와 결과 ID만 제공하며 artifact 위치를 담은 내부 계약은 노출하지 않는다.
- 포털의 진행·결과 연결은 stage ID나 같은 날짜의 Quant ID가 아니라 **해당 분석에 전달한 실제 Fusion ID**다.

독립 실행의 상세 계약은
[정량](.github/modernize/assessment/engines/facts/quantitative-pipeline-architecture.md)·
[LLM](.github/modernize/assessment/engines/facts/llm-pipeline-architecture.md)·
[Fusion](.github/modernize/assessment/engines/facts/fusion-pipeline-architecture.md) 설계와
[오케스트레이터 실행·재시도 가이드](orchestrator/README.md)를 따른다.

## 6. 선정 근거 표시를 위한 현재 가용성 정리

| 원하는 설명 | 현재 가용성 | 필요한 연결/추가 작업 |
|---|---|---|
| 정량 모델·예측값·전체/섹터 순위 | API에 있음 | Fusion의 고정 Quant run + instrument로 조회 |
| 정량 후보 목록 순위·선정 reason code | API에 있음 | 코드 의미를 과장하지 않는 문장 템플릿 |
| 정량 모델의 개별 특징별 기여 | 현재 후보 결과에 없음 | 별도 설명 산출물·저장/조회 설계 필요 |
| LLM 평가 대상에 들어간 이벤트 조건 | API에 있음 | run의 screening summary와 후보 연결 |
| LLM 항목별 점수·결측·근거 이유 | API에 있음 | 고정 LLM run + instrument + evidence link로 연결 |
| LLM 종합 rationale·uncertainty | DB에만 있음 | API schema·조회 SQL 확장 필요 |
| 클릭 가능한 기사 제목/원문 URL | 현재 후보 evidence 응답에는 없음 | 승인된 snapshot lineage 기반 추가 조회 계약 필요 |
| RRF 원천 순위·정확한 산식 | Fusion API에 있음 | 상위 `rrf_k`와 후보의 분자/분모로 설명 |
| 섹터 완화·양쪽/한쪽 원천 반영 | Fusion API에 있음 | run/후보 reason code를 함께 표시 |
| 탈락 종목 대비 선택 이유 | DB audit에 있으나 API 미노출 | audit 조회·명확한 reason 계약 필요 |
| 종목 한 건의 Quant+LLM+Fusion 통합 설명 | 현재 없음 | 고정 source run을 연결한 설명용 read model 설계 필요 |

후속 설계의 핵심은 새로운 분석을 지어내는 것이 아니라 **이미 고정·저장된 결과와 근거를
같은 instrument 기준으로 묶어 설명하는 것**이다. 동일 issuer의 다른 share class에
원천 점수·이유를 복사하거나, 한쪽 Top 20에 없는 값을 0점으로 채우면 안 된다.

## 7. 확인한 구현 근거

- [정량 schema](backend/app/schemas/candidates.py): Candidate·CandidateReason.
- [정량 조회](backend/app/repositories/candidates.py): run 고정·이유 코드 응답.
- [점수 순위](src/sp500_candidate_engine/analytics/scoring.py): percentile 계산.
- [선정 정책](src/sp500_candidate_engine/selection/policy.py): 순서·제약·reason code.
- [정량 저장](src/sp500_candidate_engine/selection/repository.py): 수익률·cutoff·reason detail.
- [LLM schema](backend/app/schemas/llm_preselections.py): run·후보·evidence 공개 계약.
- [LLM 조회](backend/app/repositories/llm_preselections.py): 공개·미공개 필드 경계.
- [screening](src/sp500_candidate_engine/llm_preselection/screening.py): pool·유형별 이벤트 점수.
- [LLM 평가](src/sp500_candidate_engine/llm_preselection/event_ranker.py): 근거 검증·총점·반올림.
- [LLM 저장](src/sp500_candidate_engine/llm_preselection/repository.py): rationale·uncertainty.
- [event v2 설정](config/llm_preselection/policy_event_v2.yaml): rubric·screening.
- [Fusion schema](backend/app/schemas/fusions.py): 후보/run·정확한 RRF 검증.
- [Fusion 정책](src/sp500_candidate_engine/fusion/policy.py): issuer/sector·union 제한.
- [Fusion 저장](src/sp500_candidate_engine/fusion/repository.py): projection·audit.
- [Fusion 조회](backend/app/repositories/fusions.py): run·handoff 생성·hash 경계.
- [독립 stage schema](backend/app/schemas/candidate_stages.py): 제어 상태·결과 ID.

## 8. 구현: DB 구조 변경 없이 선정 근거 보존

### 8.1 목표와 제외 범위

최종 종목을 조회할 때 다음 세 설명을 함께 제공한다.

1. **정량 선정 기준**: 모델 예측 수익률·전체 순위·원천 후보 위치·선정 코드.
   현재 설명 수준을 유지하고 SHAP·개별 특징 기여도는 이번 작업에서 추가하지 않는다.
2. **LLM 선정 근거**: 실제 평가에 사용한 뉴스·공시·재무 수치 중 어떤 정보가 어떤
   rubric 항목 평가에 반영됐는지 요약해 해당 분석일의 run과 함께 저장한다.
3. **Fusion 선정 근거**: 원천 정량 점수·LLM 점수와 요약·양쪽 목록 순위·각 RRF
   기여·최종 순위·제약 완화 여부를 하나의 종목 설명으로 보존한다.

“반영됐다”는 저장된 rubric 평가에 해당 근거가 인용됐다는 뜻이다. 모델 내부의 인과적
기여나 기사별 정량 기여 비율을 증명하는 표현으로 사용하지 않는다.
LLM 점수와 정량 예측값을 합산하는 새 알고리즘을 만들지 않는다.

### 8.2 최소 변경 저장 결정

**신규 테이블·컬럼·인덱스·DDL migration은 0개다.** 기존 저장 공간을 사용하고,
Python의 저장 projection·검증·조회 schema만 확장한다.

| 보존할 내용 | 사용할 기존 저장 공간 | 변경 방식 |
|---|---|---|
| 정량 수치·선정 기준 | `selection.candidate`, `selection.candidate_reason` | 기존 저장 유지. 문장은 수치·코드의 결정적 템플릿으로 구성 |
| LLM 종목별 종합 근거 요약 | `analytics.llm_instrument_assessment.rationale` | 신규 평가 저장 시 bounded 요약을 기록 |
| 항목별 근거와 반영 이유 | 같은 테이블의 `criterion_evidence`, `sub_scores`, `missing_reasons` | 기존 형식 유지. citation의 `reason`을 근거별 짧은 요약으로 활용 |
| 당시 모델에 제공한 기사·공시·재무 정보 | `analytics.llm_evidence_packet`와 `analytics.llm_evidence_link` | 기존 immutable packet·lineage 재사용 |
| 최종 종목별 통합 설명 snapshot | `selection.fusion_candidate.candidate` JSONB의 신규 `explanation` 객체 | 신규 Fusion insert 때 함께 저장 |
| 설명 계약·source identity·검증 hash | `selection.fusion_run.provenance` JSONB | 설명 version과 source/explanation hash 추가 |

LLM 근거 JSON을 정량 테이블로 복사하거나 날짜별 별도 설명 테이블을 만들지 않는다.
Fusion JSONB에는 사용자에게 필요한 bounded 요약과 식별 정보만 snapshot하고,
원문 기사·전체 재무제표·전체 prompt/응답·evidence packet은 복제하지 않는다.
기존 rubric·후보 개수·순위·RRF policy는 유지한다.

### 8.3 “분석일에 함께 저장”의 정확한 키

- 업무 날짜는 기존 `price_session_date`를 사용한다. API에 같은 의미의 `analysis_date`
  DB 컬럼을 새로 만들지 않는다.
- 분석 시점은 기존 `execution_context_id`, `cutoff_at`으로 고정한다.
- 날짜 하나만으로 설명을 덮어쓰지 않고 `(llm_ranking_run_id, instrument_id)` 및
  `(fusion_run_id, instrument_id)`에 연결한다.
- 같은 날짜에 재실행이 있어도 각 run의 설명을 구분한다. 조회 시 최신 뉴스·최신
  재무제표·다른 LLM run을 가져와 과거 설명에 섞지 않는다.
- LLM 설명은 LLM 평가 결과 저장 transaction에, 최종 설명은 Fusion 후보·audit
  저장 transaction에 포함한다. 조회 시점에 다시 LLM을 호출하지 않는다.
- LLM 저장은 Fusion 성공 여부와 독립적이다. Fusion이 실패해도 LLM의 당일 평가 근거는 남는다.

## 9. 구현: LLM 뉴스·재무 근거 요약

### 9.1 기존 평가 결과를 활용하는 생성 방식

추가 요약 전용 LLM 호출 없이 기존 항목별 평가·인용 결과를 활용한다.

1. 평가에서 `score != null`인 항목과 그 항목의 유효 citation만 “점수 반영 근거”로 분류한다.
2. `evidence_link_id`를 같은 instrument·ranking run의 **실제 제공 packet**에 연결한다.
   screening에는 있었지만 packet 잘림으로 모델에 제공되지 않은 자료를 추가하지 않는다.
3. citation의 `reason`에는 제공 정보 중 평가에 반영된 사실과 항목의 연결을 짧게 기록한다.
   “뉴스가 있음”, “10-Q가 있음” 같은 존재 확인만으로 점수 근거를 만들지 않는다.
4. 신규 이벤트 평가의 `rationale`에는 검증된 scored citation의 `한글 항목명: reason`을
   실제 인용 순서로 묶어 policy 한도 이내의 결정적 요약을 저장한다.
   임의 자유 문장이 사실을 보장한다고 추정하지 않는다. 기존 원천 평가를 읽을 때도
   동일 결정적 요약과 정확히 일치하는 기존 문장만 `VALIDATED_ASSESSMENT`로 재사용하고,
   그 외에는 `DETERMINISTIC_CITATIONS`로 구분한다.
   새 평가에서 결정적으로 생성한 요약도 `DETERMINISTIC_CITATIONS`다.
   `scored-citations-ko-v1`을 LLM input identity·window config와 Fusion provenance에 고정하며
   기존 `criterion_evidence`는 변형하지 않는다.
5. null 항목은 `missing_reasons`로 구분한다. 근거 부족을 설명하는 인용을 긍정 평가
   또는 점수 반영 근거처럼 소개하지 않는다.

평가 prompt·응답 검증 요구를 강화해야 한다면 prompt version을 별도로 올리고,
기존 cache/input identity가 구 설명과 신 설명을 섞지 않도록 한다.
저장된 예전 `rationale`를 새 문장으로 UPDATE하지 않는다.

현재 이벤트 prompt는 `llm-event-preselection-v3-ko`다. 평가·재질의 지시는 한국어이며
`summary`, citation `reason`, null이 아닌 `missing_reasons`는 한국어 문장으로 작성한다.
한글이 없는 자연어 필드는 의미 검증 실패로 처리하고 기존 한도 내에서 재질의한다.
JSON key·criterion·enum·UUID와 제공 자료 원문은 번역하지 않는다.
prompt/policy hash·요약 version이 달라져 예전 영문 응답 cache와 섞이지 않는다.
이 언어 변경은 로컬 구현이며 운영 배포와 구분한다.

### 9.2 사용자에게 제공할 근거 식별 정보

Fusion의 `explanation.llm.evidence`에 다음 값들을 작은 snapshot으로 저장한다.
LLM 원천 조회에도 같은 projection을 사용할 수 있지만 별도 중복 테이블은 만들지 않는다.

| 필드 | 의미 / 생성 규칙 |
|---|---|
| `evidence_link_id`, `source_snapshot_id`, `source_kind` | 기존 검증된 원천 식별자 |
| `criterion` | `earnings/business/event/financial/industry` 중 실제 평가 항목 |
| `source_label` | 뉴스는 실제 제공 제목, 공시는 form·기간, 재무는 concept·기간·unit·제공 수치로 만든 짧은 식별 문구 |
| `source_available_at` | cutoff까지 이용 가능했던 원천 공개 시각 |
| `period_end` | 공시·재무 대상 기간. 원천에 없거나 해당 없으면 null |
| `summary` | 해당 자료가 해당 항목 평가에 반영된 이유. 기존 citation reason 기반 |
| `source_url` | 보존된 승인 원천에 실제 URL이 있고 안전한 HTTPS 링크로 검증된 경우만 사용. 없으면 null |
| `metadata_status` | `AVAILABLE/PARTIAL`로 표시 정보 누락 여부 구분 |

`source_label`과 URL은 LLM이 자유 생성하지 않고 서버가 packet·고정 lineage에서 해석한다.
현 packet에는 뉴스 제목과 SEC filing/fact 식별·수치가 있으나 URL 존재는 보장되지 않는다.
URL을 알아내려고 현재 웹을 재검색하거나 accession만으로 확인하지 않은 링크를 만들지 않는다.
공시 목록만 있는 경우 원문 재무제표를 분석했다고 표현하지 않는다.

재무 예시:

> 제공된 2026년 3분기 매출·영업이익 fact가 financial 항목 평가에 인용됨.

이 문장은 해당 기간·concept·값이 실제 packet에 있을 때만 가능하다. 전년 동기 값이
제공되지 않았다면 “전년 대비 증가”를 만들어내지 않는다. 기존 예시처럼
`financial=null`이면 “재무 근거 부족으로 평가 제외”로만 표시한다.

### 9.3 길이·검증·실패 정책

- 종합 `rationale`와 각 citation reason은 현재 policy의 rationale 문자 한도를 지킨다.
  종합 요약에 못 담은 사실은 기존 항목별 citation으로 유지한다.
- Fusion snapshot의 표시 근거는 실제 인용 순서로 최대 10개, `source_label`은 최대 256자,
  각 summary는 해당 policy 한도 이내로 제한한다. 원천 ID를 제거한 채 자르지 않는다.
- 원천 metadata 누락은 `source_label/source_url/period_end=null` 및
  `metadata_status=PARTIAL`로 드러낸다. 사실 요약 자체는 유효한 citation이 있어야 한다.
- 잘못된 instrument·snapshot·cutoff·점수 항목 연결은 검증 실패로 기록한다.
  의미 없는 일반 설명을 대신 저장하고 설명 생성 성공으로 표시하지 않는다.
- 설명 생성을 위해 기존의 지원 항목 개수·가중치·점수·최종 선정 여부를 변경하지 않는다.

### 9.4 과거일 분석의 필수 시점 검증

- 사용자가 확정한 정보 경계는 거래일 자정이 아니라 **해당 run의 `cutoff_at`**이다.
- 새 packet과 재사용 packet 모두 hash·context·session·모든 source link를 검증하고,
  모델 호출·응답 캐시 조회 전에 다시 검사한다. 실패 시 LLM 호출이나 성공 run 재사용으로
  우회하지 않는다. screening에만 남은 lineage도 공개·관찰 시점을 검증한다.
- 양쪽 재현 모드 모두 cutoff 후 공개 정보는 금지한다. 재구성 모드의 늦은 수집만
  허용하며 운영 replay에서는 관찰 시각도 cutoff 이하여야 한다.
- cutoff 전에 알려진 향후 실적 일정은 허용하지만 이후 발표된 실적 결과는 금지한다.
  동일 자료가 여러 rubric 항목에 인용돼도 시점 gate는 완화되지 않는다.
- Fusion은 기존 LLM packet 전체와 실제 제공된 인용의 instrument·snapshot·manifest·
  ranking identity를 다시 검증한다. invalid 근거는 신계약 성공에서 제외하는 대신
  `FUSION_EXPLANATION_VALIDATION_FAILED`를 기록하고 후보를 저장하지 않는다.

## 10. 구현: 최종 Fusion 설명 snapshot

### 10.1 저장 객체 샘플

아래 JSON은 **저장되는 `explanation` 객체 한 개**의 가상 예시다.
v2 조회에서는 후보의 `explanation`으로 반환하며 v1 응답·handoff에는 포함하지 않는다.
4절 Fusion 후보 JSONB의 기존 점수·순위 필드는 그대로 둔다.
가상 예시는 앞 절과 동일하게 재무·산업 점수는 null인 경우다.

```json
{
  "schema_version": "candidate-explanation-v1",
  "status": "RECORDED",
  "price_session_date": "2026-10-15",
  "cutoff_at": "2026-10-16T09:30:00Z",
  "execution_context_id": "90000000-0000-4000-8000-000000000001",
  "summary": "MEDIUM_20D predicted return +4.32%; overall rank 8; Quant Top20 position 3. DETERMINISTIC_CITATIONS: LLM score 80.0, position 2. RRF k=10: 25/156; Fusion position 1.",
  "quant": {
    "selected_in_source": true,
    "selection_run_id": "10000000-0000-4000-8000-000000000001",
    "score_semantics": "PREDICTED_20D_RETURN",
    "score": 0.0432,
    "rank_overall": 8,
    "position": 3,
    "reason_codes": ["MODEL_TOP_RANK", "MODEL_TOP_PERCENTILE"],
    "summary": "MEDIUM_20D predicted return +4.32%; overall rank 8; Quant Top20 position 3."
  },
  "llm": {
    "selected_in_source": true,
    "selection_run_id": "60000000-0000-4000-8000-000000000001",
    "score": 80.0,
    "position": 2,
    "supported_count": 3,
    "weight_denominator": 70,
    "summary_method": "DETERMINISTIC_CITATIONS",
    "summary": "실적: 제공된 실적 자료의 실적 변화 근거를 earnings 80점 평가에 반영했다. | 사업: 제공된 사업 진행 사실을 business 72점 평가에 반영했다. | 이벤트: 제공된 계약 이벤트를 event 90점 평가에 반영했다.",
    "sub_scores": {
      "earnings": 80.0,
      "business": 72.0,
      "event": 90.0,
      "financial": null,
      "industry": null
    },
    "missing_reasons": {
      "financial": "입력 packet에 재무 평가를 뒷받침할 충분한 수치 근거가 없음",
      "industry": "입력 packet에 산업 비교 근거가 없음"
    },
    "evidence": [
      {
        "evidence_link_id": "70000000-0000-4000-8000-000000000001",
        "source_snapshot_id": "80000000-0000-4000-8000-000000000001",
        "source_kind": "EARNINGS",
        "criterion": "earnings",
        "source_label": "2026년 3분기 실적 관련 제공 자료",
        "source_available_at": "2026-10-14T12:00:00Z",
        "period_end": null,
        "summary": "제공된 실적 자료의 실적 변화 근거를 earnings 80점 평가에 반영했다.",
        "source_url": null,
        "metadata_status": "PARTIAL"
      },
      {
        "evidence_link_id": "70000000-0000-4000-8000-000000000002",
        "source_snapshot_id": "80000000-0000-4000-8000-000000000002",
        "source_kind": "NEWS",
        "criterion": "business",
        "source_label": "Example Issuer 사업 진행 업데이트",
        "source_available_at": "2026-10-14T13:00:00Z",
        "period_end": null,
        "summary": "제공된 사업 진행 사실을 business 72점 평가에 반영했다.",
        "source_url": null,
        "metadata_status": "PARTIAL"
      },
      {
        "evidence_link_id": "70000000-0000-4000-8000-000000000003",
        "source_snapshot_id": "80000000-0000-4000-8000-000000000003",
        "source_kind": "NEWS",
        "criterion": "event",
        "source_label": "Example Issuer 계약 관련 업데이트",
        "source_available_at": "2026-10-14T14:00:00Z",
        "period_end": null,
        "summary": "제공된 계약 이벤트를 event 90점 평가에 반영했다.",
        "source_url": null,
        "metadata_status": "PARTIAL"
      }
    ]
  },
  "fusion": {
    "rrf_k": 10,
    "quant_contribution": {"numerator": 1, "denominator": 13},
    "llm_contribution": {"numerator": 1, "denominator": 12},
    "rrf_numerator": 25,
    "rrf_denominator": 156,
    "position": 1,
    "reason_codes": ["RRF_BOTH"],
    "sector_cap_relaxed_for_candidate": false
  }
}
```

### 10.2 생성·저장 경계

- Fusion 저장 시 **실제 사용한** Quant/LLM source run과 동일 instrument만 읽어
  explanation을 구성한다. 전체 날짜의 최신 결과를 조회해 결합하지 않는다.
- Quant·Fusion 설명은 결정적 템플릿으로 생성한다. 추가 LLM 호출로 정량 수치·RRF
  산식을 설명하게 만들지 않는다. LLM 요약은 앞 단계에서 저장한 값을 가져온다.
- 동일 source score·rank·reason code와 설명 내 수치가 일치하는지 검증한다.
  중복 필드가 달라지면 저장을 거부하며 JSONB 안의 문장을 수치의 source of truth로 삼지 않는다.
- 근거 한 건이 여러 항목에 인용되면 `(evidence_link_id, criterion)`별로 보존한다.
  기사 한 건의 등장 횟수를 독립 이벤트 수나 별도 RRF 가산점으로 세지 않는다.
- 한쪽 Top 20에만 선정된 종목은 해당 분기의 `selected_in_source=false`,
  점수·position·기여 값은 null로 표현하고 “원천 Top 20 미포함”이라고 설명한다.
  해당 분기가 평가하지 않았는지·낮게 평가했는지는 이 사실만으로 추정하지 않는다.
  참여하지 않은 분기의 요약·근거를 RRF 반영 근거처럼 표시하지 않는다.
- run 전체의 섹터 완화와 후보 자체 완화를 구분한다. 후보 자체는 기존
  `SECTOR_CAP_RELAXED` reason code에서 산출한다.

### 10.3 immutable 결과·hash·구버전 호환

- 기존 Fusion table에는 UPDATE/DELETE 방지 trigger가 있다. 과거 후보 JSONB에
  explanation을 덧붙이기 위해 trigger를 해제하거나 기존 run을 덮어쓰지 않는다.
- 신규 explanation 계약을 적용한 **새 run의 최초 insert**에서만 snapshot을 저장한다.
  기존 run에는 `NOT_RECORDED` 상태의 조회 응답으로 “당시 근거 요약 미저장”을 알린다.
  레거시 점수와 연결 가능한 원천은 그대로 조회하되 새로 생성한 문장을 과거 snapshot처럼 표시하지 않는다.
- `FusionRepository.read_sources()`는 명시 원천 run의 Quant reason code·LLM rationale·
  상세 citation·immutable packet·manifest 소속 lineage를 읽고 작은 표시 snapshot으로 투영한다.
- provenance에 `explanation_schema_version`, `explanation_config`,
  `explanation_config_hash`, `explanation_input_hash`, `explanation_output_hash`를 고정한다.
  이 값들을 Fusion payload hash와 idempotency에
  포함해 설명 계약이 바뀌었는데 예전 run이 그대로 재사용되는 것을 방지한다.
- 설명 출력 hash는 JSONB 왕복에서 `80.0`과 `80`이 같게 처리되도록 정수값 float를
  정규화한 canonical JSON으로 계산한다. 기존 v1/handoff의 canonical hash 함수는 바꾸지 않는다.
- 원천 prompt를 바꾸면 LLM prompt/cache identity도 별도로 갱신한다.
  표시 schema 변경만으로 선정 algorithm policy가 바뀌었다고 표현하지 않는다.
- 설명 요구가 활성화된 신규 Fusion 실행에서 invalid explanation은 명시적으로 실패시킨다.
  source 결과는 보존하며 설명을 빼고 신계약 성공으로 반환하지 않는다.
  없는 원천 metadata를 null로 명시한 정상적인 `PARTIAL` 표시 정보와 구분한다.
- 과거 run 설명의 소급 생성·이관은 이번 기본 범위가 아니다. 필요하면 별도 append-only
  보존·비용 계획을 세우고 분석일 당시 저장한 요약과 구분한다.

## 11. 조회 API와 포털 변경 메모

### Native LLM 검색 v4의 설명 계약

별도 `daily-llm-search-preselection:4`는 evidence schema 4와
`llm-event-preselection-v7-ko-search`를 사용한다.
서버 원문 다운로드는 제거하고 LLM native web_search와 과거 원문 admission gate를 사용한다.
새 자료의 점수 반영은 승인된 정책 변경이며 기존 v2 결과를 덮어쓰지 않는다.

- `criterion_evidence`에 `source_layer=DB_PACKET/LLM_SEARCH_VERIFIED`를 남긴다.
  검색 인용은 같은 공시의 `search_evidence_hash`를 정확히 연결한다.
  원본 structured response의 `information_gaps`에는 여전히 없는 정보를 한국어로 기록한다.
- 검색 발췌는 모델의 인용 요약이지 원문 자체/사실성 보증은 아니다.
  본문을 얻지 못한 응답은 보강 성공으로 표시하지 않으며 일반 뉴스의 과거 날짜만으로
  revision을 입증했다고 처리하지 않는다.
- 검색 run의 Fusion 설명은 `candidate-explanation-v3`다. 검색 인용에만
  `external_source`가 추가되며 tool 응답 hash·evidence hash·artifact key·source URL·
  고정 공개 시각·관찰 시각·모델 snapshot·검증 방식을 보존한다.
- 기존 `source_snapshot_id`는 DB 공시 metadata의 parent snapshot이다.
  검색 tool 증적의 identity와 혼동하지 않는다.
- `candidate-explanation-v1`, 기존 v1 API와 `fusion-top20-v1`은 보존한다.
  같은 v2 설명 조회 endpoint가 두 snapshot version을 구분해 반환한다.
- 전체 consulted sources에 미래/현재/미확인 원문이 섞이면 검색 응답 전체를 거부한다.
  검색의 원시 대화·reasoning·response ID는 별도 평가 모델에 전달하지 않는다.
  모델 이름/버전은 기록용이며 alias나 버전 metadata 부재로 자료를 거부하지 않는다.
- 검증 실패·본문 미확보는 구 정책 성공·서버 다운로드·모델 기억으로 대체하지 않는다.
  자세한 규칙은 [LLM 하네스](src/sp500_candidate_engine/llm_preselection/LLM-HARNESS.md)를 따른다.

### Candidate Engine의 구현 계약

아래 v2 경로·신규 snapshot은 로컬 변경이며 아직 운영 배포가 아니다.
결과와 고정 원천 근거를 함께 조회하는 `/api/v2/fusion-selections`·`/{run_id}`도
로컬 개발 경로다. 과거 snapshot이 없어도 DB의 원본 근거까지 없다는 뜻은 아니며,
이 조회로 immutable snapshot을 소급 생성하지 않는다.

- 신규 versioned 설명 조회를 제공한다:
  `GET /api/v2/fusion-selections/{run_id}/explanations`.
  정확한 Fusion run ID 기준으로 `schema_version`, `fusion_run_id`,
  `price_session_date`, `cutoff_at`, 후보별 `instrument_id/issuer_id/position/explanation`을 반환한다.
- 최상위 `status`와 후보별 `status`는 `RECORDED/NOT_RECORDED`이며,
  최상위 `selection_status`와 `failure_code`는 원래 Fusion 실행 상태를 나타낸다.
  과거 run의 `NOT_RECORDED` 후보는 `explanation=null`이며 조회 중 소급 생성하지 않는다.
  알려진 신계약인데 snapshot이 누락되거나 hash·중복 수치가 다르면 HTTP 500,
  없는 run은 HTTP 404다. invalid 설명을 정상적인 미저장으로 숨기지 않는다.
- 새 JSONB는 `explanation`을 포함하므로 현재 `extra="forbid"`인 v1 `FusionCandidate`에
  그대로 넣으면 validation 오류가 난다. **v1 repository는 기존 필드 allowlist로
  projection**하고, 새 조회는 명시적인 typed explanation schema로 검증한다.
- LLM 종합 `rationale` 노출이 필요하면 동일 원천 run 기준의 versioned 설명 조회에서
  기존 저장 값을 제공한다. 현재 v1의 필드가 이미 추가된 것처럼 취급하지 않는다.
- 기존 `fusion-top20-v1` handoff에는 새 explanation을 자동 포함하지 않는다.
  `model_dump()`의 신규 필드·기본 null이 유입돼 기존 payload hash와 ACK 계약이
  달라지는 것을 막도록 v1 envelope도 기존 allowlist projection을 유지한다.
- 포털은 기존 handoff 수신 후 고정 Fusion run의 설명 조회를 사용할 수 있다.
  설명까지 한 번에 받는 신규 handoff가 필요하면 별도 version의 계약·hash·전량 ACK를
  양쪽에서 검증한 후 활성화한다. 이번 설계는 기존 전송 계약을 조용히 변경하지 않는다.

### 포털의 별도 작업

1. 기존 후보에 연결된 **정확한 Fusion run ID**로 설명을 조회한다. 날짜별 최신
   Quant/LLM을 따로 조회해 화면에서 임의 조합하지 않는다.
2. 종목 카드/상세에 `정량 선정 기준`, `LLM 반영 자료`, `Fusion 산정` 세 구역을 표시한다.
   정량 수익률은 %, LLM은 rubric 점수, RRF는 순위 결합값으로 단위를 분리한다.
3. 뉴스는 제목·공개 시각·요약, 공시/재무는 보고 기간·항목·요약을 표시하고
   검증된 `source_url`이 있을 때만 원문 링크를 만든다.
   null 항목·근거 미저장·한쪽 원천 미포함을 0점이나 부정 평가로 바꾸지 않는다.
4. 포털 DB에 보존할 필요가 있으면 기존 후보/job metadata JSON의 재사용을 먼저 검토한다.
   원천 key는 `(fusion_run_id, instrument_id, schema_version)`로 고정한다.
   포털의 실제 schema 검토·구현·migration은 별도 저장소 작업이다.
5. 초기에는 기존 handoff와 설명 조회를 분리한다. 설명 조회 장애는 포털에서
   “근거 조회 실패/재시도 필요”로 알리고 이미 접수된 20개를 중복 제출하지 않는다.

## 12. 독립 구현 순서·완료 기준

| 단계 | 작업 | 범위 |
|---|---|---|
| 1 | LLM 저장 근거 품질 검증 | 기존 rationale·citation reason 활용, 실제 packet 범위만 요약 |
| 2 | bounded 설명 projector·schema | Quant 템플릿·LLM 원천 요약·metadata·RRF 조합 |
| 3 | 신규 Fusion insert snapshot | 기존 JSONB·provenance/hash 확장, 기존 table 구조 유지 |
| 4 | versioned 설명 조회·v1 보호 | typed read model, legacy projection·hash 호환 |
| 5 | 포털 별도 연동 | 같은 run의 설명 표시·선택적 보존, 필요 시 새 전달 계약 |

이 순서는 파이프라인 분리 plan과 독립적이며 정량/LLM 실행 방식 변경을 포함하지 않는다.
공유 파일을 양쪽 작업에서 수정할 때에는 source run 입력 계약·저장 helper를 재사용하고,
실행 제어 코드와 설명 projection을 섞지 않는다.

필수 확인 항목:

- 같은 분석일·고정 run·instrument에 뉴스/재무 근거와 요약이 함께 저장되고,
  이후 뉴스·모델·정책이 바뀌어도 과거 explanation은 달라지지 않는다.
- 뉴스 제목·재무 항목·기간·시각은 실제 제공 packet에 있고, missing/null 항목을
  점수 반영 근거로 사용하지 않는다.
- 신규 summary가 기존 정량 점수·LLM 총점·후보 개수·RRF·순위·hard gate를 바꾸지 않는다.
- 설명·수치·citation 검증 실패 시 신규 Fusion은 FAILED·후보 0개로 기록되고 원천 결과는
  보존된다. 실제 후보·audit insert 중 오류는 같은 transaction의 run·설명·후보 전체를 rollback한다.
- 동일 source·설명 version·내용 재시도는 같은 결과를 재사용하고 다른 내용은 충돌로 구분한다.
- 기존 v1 조회·handoff 필드·canonical payload hash·20개 ACK는 변하지 않는다.
- 과거 explanation 없는 후보도 명시적 상태로 조회되고, 조회 때 LLM 재호출·원천 웹 검색은 없다.
- 1~4단계는 코드·회귀 및 격리 PostgreSQL로 검증한다. 포털·UI·운영 설정·실제 LLM 호출·
  배포는 이번 변경에 포함하지 않는다.
