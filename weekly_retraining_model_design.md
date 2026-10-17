# 주간 재학습 모델 설계

갱신일: 2026-10-16

## 1. 목적과 범위

이 문서는 `SHORT_5D`와 `MEDIUM_20D`의 주간 training-only 실행, 승격 gate,
immutable model artifact, PostgreSQL active assignment와 DAILY pinning 계약을
정의한다.

Candidate Engine의 범위는 다음으로 제한한다.

```text
수집 -> 전처리 -> 모델 점수 -> 후보 선정
```

외부 LLM 분석, 리포트, 비용, 매매와 재평가는 포함하지 않는다. 주간 학습은 모델을
평가·등록할 수 있지만 production score나 candidate selection을 만들지 않는다.

## 2. 상태 용어

이 문서에서는 다음 상태를 구분한다.

- **IMPLEMENTED**: 저장소에 실행 코드·schema·설정이 존재한다.
- **VALIDATED**: 해당 계약을 대상으로 한 자동 테스트 또는 명시된 PostgreSQL
  integration 검증을 통과했다.
- **DEPLOYED**: 운영 Azure resource에 적용했고 해당 runtime 경로의 실행을 확인했다.
- **PARTIAL**: 구성 요소는 있으나 end-to-end 연결이나 운영 검증이 남았다.

문서 작성 시점의 상태:

| 구성 요소 | 구현 | 검증 | 배포 |
|---|---|---|---|
| training-only workflow | IMPLEMENTED | 단위 테스트 | 운영 Container Job 실행 미검증 |
| weekly run 상태·멱등 repository | IMPLEMENTED | 단위 테스트와 PostgreSQL 16.15 검증 | DB schema 적용 |
| promotion policy/evaluator | IMPLEMENTED | focused 단위 테스트 | weekly job과 미통합 |
| schema-v2 packaging | IMPLEMENTED | focused 단위 테스트 | private Blob upload E2E 미검증 |
| Blob/file loader와 local cache | IMPLEMENTED | focused 단위 테스트 | 운영 managed identity E2E 미검증 |
| active assignment CAS/history | IMPLEMENTED | PostgreSQL 16.15 integration 검증 | DB schema 적용 |
| DAILY binding pinning | IMPLEMENTED | pointer 변경·fallback 단위 테스트 | 운영 backend 배포 미검증 |
| 자동 승격·activation smoke·rollback | PARTIAL | E2E 미검증 | 미배포 |

이 상태표는 승격된 모델이 있다는 뜻이 아니다. 이 문서에서 새 `CHAMPION`을 선언하지
않으며, 기존 문서에 기록된 `SHORT_5D` v2와 `MEDIUM_20D` v1은 `SHADOW`다.

## 3. 모델 목적 계약

| 목적 | Label | Prediction | Horizon | Return policy |
|---|---|---|---:|---|
| `SHORT_5D` | `RAW_STOCK_5D_RETURN` | `PREDICTED_5D_RETURN` | 5 sessions | `PRICE_RETURN` |
| `MEDIUM_20D` | `RAW_STOCK_20D_RETURN` | `PREDICTED_20D_RETURN` | 20 sessions | `PRICE_RETURN` |

두 목적은 같은 parent orchestration에서 순차 실행할 수 있지만 run, artifact,
assignment, score와 selection identity를 공유하지 않는다. 한 목적의 실패나 artifact
부재를 다른 목적의 모델로 대체하지 않는다.

## 4. Training-only workflow

### 구현 경계

`run_training_only_workflow()`는 공용 `_run_phase45_workflow()`에 다음 계약으로
진입한다.

```text
selection_config = None
persist_selection = false
```

따라서 다음은 재사용한다.

- manifest-scoped export와 cutoff
- Alpha158 생성과 feature dimension 검증
- 성숙 label과 label-exit purge
- expanding purged walk-forward
- Momentum/Ridge/LightGBM 평가
- model artifact 생성
- `analytics.model_version`의 `SHADOW` 등록

다음은 실행하지 않는다.

- production scoring run 저장
- production selection run 저장
- candidate JSON 생성
- active assignment 변경

반환값 `TrainingWorkflowSummary`는 다음 identity와 평가 결과를 제공한다.

```text
experiment_key
experiment_dir
export_run_id
model_version_id
selected_shadow_model
metrics
model_purpose
prediction_horizon_sessions
return_policy
scorecard_quality_gate_passed
```

### Weekly job lifecycle

`WeeklyTrainingJob`은 PostgreSQL run을 읽고 purpose를 확인한 뒤 다음 전이를 사용한다.

```text
PENDING -> RUNNING -> EVALUATED
                   -> FAILED
```

성공 시 `export_run_id`와 `challenger_model_version_id`를 weekly run에 기록한다.
실패 시 secret이나 raw payload를 포함하지 않는 고정 error code/message를 기록한다.

현재 job은 `anchor_session`과 `training_cutoff`에 맞는 export를 선택해 training-only
workflow를 호출한다. 다음 단계는 아직 job에 연결되지 않았다.

1. weekly run의 `input_manifest_id`와 선택한 export manifest의 명시적 동일성 fence
2. schema-v2 packaging과 private Blob upload
3. incumbent metric 조회와 promotion evaluator 호출
4. `model_promotion_decision` 저장
5. pre-activation smoke와 assignment CAS
6. activation smoke 및 실패 시 rollback

## 5. Promotion policy

정책 파일은 `config/analytics/weekly_retraining_v1.yaml`이며 version은 `1`이다.
각 gate 값은 finite number여야 한다. runtime metric이 없거나 bool/non-numeric,
NaN 또는 Infinity이면 해당 gate는 실패한다. `test_blocks`는 정수여야 한다.

### Absolute gates

| Metric | SHORT_5D | MEDIUM_20D | 판정 |
|---|---:|---:|---|
| `coverage` | ≥ 0.80 | ≥ 0.80 | minimum |
| `test_blocks` | ≥ 3 | ≥ 3 | minimum |
| `rank_ic_mean` | ≥ 0.01 | ≥ 0.01 | minimum |
| `fold_rank_ic_median` | ≥ 0.00 | ≥ 0.00 | minimum |
| `net_top_10_return` | ≥ 0.00 | ≥ 0.00 | minimum |
| `max_drawdown_top_10` | ≥ -0.25 | ≥ -0.35 | minimum |

max drawdown은 더 큰 값, 즉 0에 가까운 값이 더 낫다.

### Incumbent-relative gates

다음 metric은 모두 `challenger - incumbent >= 0.00`이어야 한다.

- `rank_ic_mean`
- `fold_rank_ic_median`
- `net_top_10_return`
- `max_drawdown_top_10`

incumbent metric이 없거나 non-finite이면 fail closed한다. active incumbent 자체가 없는
최초 bootstrap에서는 absolute gate를 통과해야 하고 relative result는
`no_incumbent`로 남긴다.

`evaluate_promotion()`의 결과는 `PROMOTE` 또는 `REJECT`와 gate별 actual,
threshold, incumbent, reason을 포함한다. evaluator가 `PROMOTE`를 반환하는 것만으로
registry status나 active assignment는 바뀌지 않는다. 현재 weekly job에는 이
evaluator와 decision persistence가 연결되지 않았다.

## 6. Immutable schema-v2 artifact

### Packaging 입력 검증

`package_model_artifact()`는 선택된 registry row와 다음을 대조한다.

- LightGBM model name/version
- model weight SHA-256
- model+label effective config hash
- processor 부재 계약
- model purpose와 label semantics
- `PRICE_RETURN`
- prediction semantics와 horizon
- Alpha158 feature dimension과 feature 이름 순서

불일치하면 artifact를 만들지 않는다. 기존 output manifest/model이 다른 내용이면
덮어쓰지 않고 실패한다.

### Manifest fields

schema-v2 manifest는 다음 필드를 고정한다.

```text
schema_version = 2
model_purpose
label_semantics
prediction_semantics
horizon_sessions
model_version_id
model_file
model_sha256
feature_names
feature_config_hash
model_config_hash
```

`model_sha256`은 model weight bytes의 hash다. manifest bytes의 SHA-256은 manifest
자체에 넣지 않고 packaging 결과와 active assignment의 `artifact_hash`로 관리한다.
두 hash는 의미와 검증 위치가 다르며 서로 대신 사용할 수 없다.

### Loader

loader는 다음 source만 허용한다.

- private Azure Blob의 `https://<account>.blob.core.windows.net/...`
- local validation/migration fallback의 local `file://`

Blob URI에는 SAS나 임의 query를 허용하지 않는다. managed identity credential로
Storage scope token을 얻고 assignment의 `If-Match` ETag와/or version ID를 요청과
응답에서 확인한다. 그 후 manifest SHA-256, schema/purpose 계약, model weight
SHA-256을 모두 검증한다.

local cache key는 manifest SHA-256이다.

```text
<cache>/<manifest_sha256>/
├── manifest.json
└── lightgbm.txt
```

cache publish는 temporary directory에서 검증을 마친 뒤 atomic rename한다.
hash별 file lock은 process 간 동시 materialization을 직렬화한다. cache hit도
manifest와 model hash를 다시 검증한다.

## 7. Active assignment contract

authoritative pointer는 PostgreSQL의 purpose별
`analytics.active_model_assignment`다.

```text
model_purpose
model_version_id
artifact_uri                 # manifest URI
artifact_hash                # manifest SHA-256
blob_etag
blob_version_id
generation
weekly_run_id
activated_at
```

운영 Blob assignment에는 ETag 또는 version ID가 반드시 있어야 한다. model purpose는
weekly run과 model registry row의 purpose에 composite FK로 연결된다.

activation/rollback은 다음 순서를 사용한다.

1. purpose assignment row를 `FOR UPDATE`로 읽는다.
2. 현재 generation이 caller의 `expected_generation`과 같은지 확인한다.
3. generation을 1 증가시켜 pointer를 insert/update한다.
4. stale concurrent update이면 변경 없이 실패한다.
5. `active_model_assignment_history`에 `ACTIVATE` 또는 `ROLLBACK`을 append한다.

최초 assignment는 expected generation 0에서 generation 1이 된다. history는
replaced model identity를 보존한다. 이 repository 기반은 구현·검증됐지만 promotion
service가 이를 호출하는 end-to-end activation/rollback은 아직 구현되지 않았다.

## 8. DAILY pinning

### Pin 시점과 저장

`PipelineExecutionService`는 DAILY inference 전에 `process_run_id`와 purpose로
`ops.process_run`을 `FOR UPDATE`한다. metadata에 해당 purpose의 binding이 없을 때만
active assignment를 읽고 다음 전체 값을
`metadata.model_bindings[model_purpose]`에 저장한다.

```text
model_purpose
model_version_id
artifact_uri
artifact_hash
blob_etag
blob_version_id
generation
weekly_run_id
```

같은 process retry에서는 active pointer를 다시 읽지 않고 저장된 binding을
재사용한다. 실행 도중 새 generation이 승격되어도 이미 시작된 DAILY run의 model은
바뀌지 않는다.

### Materialization과 inference gate

저장된 binding으로 `ModelArtifactLoader.load()`를 호출한다. 반환값은 다음과 같다.

```text
manifest
manifest_path
model_path
manifest_sha256
model_sha256
```

backend는 manifest의 purpose/semantics/horizon, manifest SHA-256, model SHA-256과
`model_version_id`를 pin과 다시 대조한 뒤 scoring을 시작한다. 하나라도 다르면 score와
selection을 쓰기 전에 실패한다.

active assignment가 없을 때만 purpose별 App Settings manifest fallback을 사용할 수
있다. fallback도 manifest path와 SHA-256이 모두 있어야 한다. 다른 model purpose의
manifest는 fallback으로 사용할 수 없다.

## 9. PostgreSQL 16 검증

2026-10-16 Azure Database for PostgreSQL Flexible Server 16.15에서 다음을 수행했다.

1. migration을 transaction 안에서 적용하고 rollback하여 원상 복구를 확인했다.
2. migration을 실제 적용하고 schema migration ledger와 생성 객체를 확인했다.
3. 실제 FK를 만족하는 weekly run/model row로 초기 generation 0→1을 검증했다.
4. expected generation이 오래된 CAS update가 차단되는지 검증했다.
5. purpose composite FK와 champion uniqueness 기반을 확인했다.
6. rollback action/history 경로를 integration transaction에서 검증하고 transaction
   자체는 rollback했다.

이 검증은 schema와 repository 동시성 계약에 대한 것이다. 다음을 증명하지 않는다.

- private Blob에 production artifact가 업로드됨
- active assignment row에 실제 운영 model이 등록됨
- promotion decision이 실행됨
- 어떤 model이 `CHAMPION`으로 승격됨
- activation smoke와 자동 rollback이 end-to-end 실행됨

## 10. 검증 seam

현재 자동 테스트 seam:

- training-only wrapper가 `persist_selection=false`와 `selection_config=None`을
  전달하는지 확인
- weekly run ID, 상태 CAS, initial/stale assignment generation 확인
- finite/missing promotion metric과 absolute/relative gate 확인
- schema-v2 manifest의 purpose와 manifest/model hash 분리 확인
- private Blob ETag/version/hash mismatch 확인
- `file://` loading과 multiprocess-safe hash cache 확인
- DAILY pointer 변경 후 기존 process binding 재사용 확인
- assignment가 없을 때만 fallback 경로로 진행하는지 확인

운영 전 추가 검증:

1. weekly job이 pinned input manifest 밖 snapshot을 읽지 않는 integration test
2. immutable Blob upload 후 managed identity download
3. gate reject 시 incumbent pointer 불변
4. gate pass 시 expected-generation CAS activation
5. activation smoke 실패 시 이전 binding rollback
6. rollback CAS 실패 시 CRITICAL alert
7. pointer가 DAILY 실행 중 바뀌어도 scoring/selection model identity가 유지되는 E2E
8. SHORT 실패와 무관한 MEDIUM 독립 실행

## 11. 배포 판정

PostgreSQL weekly migration은 Azure PostgreSQL 16.15에 적용·검증됐다. 저장소에는
weekly Job, private artifact infrastructure와 orchestration 구현도 존재하지만 이
문서 작성 시점에 해당 application/IaC 변경의 운영 배포 및 end-to-end promotion
실행 증거는 없다.

다음은 이 절 작성 당시의 검증 범위다. 최신 독립 후보 실행·Fusion 배포 여부와
혼동하지 않으며 현재 운영 증거는 [운영 점검서](DAILY-PIPELINE-RUNBOOK.md)를 따른다.

```text
DB schema: DEPLOYED and VALIDATED
training/policy/artifact/pinning code: IMPLEMENTED and TESTED
weekly promotion runtime: NOT YET INTEGRATED
application/infrastructure rollout: NOT VERIFIED
promoted model: NONE CLAIMED
```

## 일일 후보 수와 재학습 평가 구분 (2026-10-16)

일일 기본 MEDIUM_20D 정량 후보는 정확히 20개다. 별도 LLM Top 20과의 최종
통합·TradingAgents 전달 목표도 기존 5~10개에서20개로 변경했다.
이후2026-10-17 이벤트 v2·Fusion·독립 stage 실행과 전달 어댑터의 배포·계약 검증을
완료했으며, 이는 이 주간 설계에서 새로운 모델 승격이 발생했다는 뜻이 아니다.
후보 수 변경은 모델 horizon·label·weight 또는 Top-5/10 promotion 지표 변경이 아니다.
SHORT_5D 레거시 정책과 두 모델의 주간 training-only 계약은 유지한다.
