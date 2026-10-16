# 매일 추론·주 1회 재학습 구현 Handoff Plan

## 현재 진행 상태 (2026-10-16)

- Phase 1~10 구현, 문서 정합화, Azure 배포와 실제 canary 검증을 완료했다.
- `sql/021_weekly_retraining.sql`을 Azure PostgreSQL 16.15에 적용하고 실제 FK 기반
  generation CAS, stale write 차단, rollback history를 transaction 검증했다.
- training-only workflow, cutoff-fixed historical export, SHADOW 등록, versioned
  absolute/relative gate, immutable schema-v2 Blob artifact, active assignment CAS,
  DAILY process별 binding pinning을 연결했다.
- weekly API와 Durable parent/child, Container Apps Job start/poll, 실패 run 재시도,
  SHORT 실패와 무관한 MEDIUM 실행을 구현했다.
- Candidate 전용 Korea Central private Container Apps·ACR·Blob·VNet·private
  endpoint와 최소 권한 관리 ID를 배포했다.
- Backend P3v3/capacity 1·VNet integration, Durable weekly functions, training image,
  PostgreSQL Entra principal/grant를 배포했다.
- 전체 pytest 365건과 focused weekly/IaC/Bicep 검증을 통과했다.
- 실제 cutoff-fixed 2년 Qlib export는 251,978행을 생성했고 SHORT·MEDIUM
  Container Apps Job은 모두 성공했다. 두 challenger는 promotion gate에서
  `REJECT`되어 active assignment와 legacy fallback을 변경하지 않았다.
- Durable validation parent는 SHORT·MEDIUM의 독립 `REJECTED` 결과를 보존하면서
  `SUCCEEDED`로 완료했다. historical reconstruction context에서 잘못 생성된
  추가 MEDIUM validation run과 decision은 의존성 검증 후 제거했다.
- 최종 Backend는 P3v3/capacity 1과 VNet integration을 유지하고 live/readiness,
  execution binding route, operational manifest eligibility를 통과했다. ACR·Blob
  private access, Blob versioning, PostgreSQL ReadOnly lock도 확인했다.
- Phase 11의 전체 pytest 365건, Ruff, Bicep compile, diff/secret/IDE 문제 검증을
  통과했으며 이 변경 집합의 branch commit/push로 계획을 마감한다.

## 1. 문서 목적

이 문서는 `SHORT_5D`, `MEDIUM_20D`에 다음 운영 정책을 구현하기 위한 단일 handoff
문서다.

```text
매 거래일:
수집 -> active model pin -> 특징 -> 추론 -> 후보

주 1회:
성숙 label -> 격리 재학습 -> walk-forward 비교
-> 자동 승격 -> activation smoke -> 실패 시 즉시 rollback
```

2026-10-15 handoff 이후 `feature/weekly-retraining` branch에서 구현을 재개했고,
이 문서의 phase 순서대로 코드·schema·IaC·배포를 통합했다.

## 2. Git 기준 상태

- repository: `brjeong-private/sp500-candidate-engine`
- branch: `feature/weekly-retraining`
- 구현 시작 기준 commit: `3e35070 docs(architecture): align candidate engine scope`
- weekly retraining 구현은 현재 branch의 단일 검증·배포 변경 집합으로 관리
- ignored deployment package와 local virtual environment는 commit에서 제외

다른 PC 시작 절차:

```powershell
git pull origin main
git switch -c feature/weekly-retraining
```

그 후 루트 `PROJECT-HARNESS.md`, 로컬 하네스가 있으면
`.local/PROJECT-HARNESS.local.md`, 이 문서를 순서대로 읽는다.

## 3. 확정된 설계 결정

### 적용 모델

- `SHORT_5D`
- `MEDIUM_20D`

두 모델을 같은 주간 parent에서 순차 실행하지만 결과는 독립적으로 보존한다.
SHORT 실패가 MEDIUM 실행을 막지 않는다.

### 승격 정책

- promotion gate 통과 시 자동 승격
- Candidate activation smoke 실패 시 즉시 이전 pointer로 rollback
- rollback 실패는 CRITICAL alert
- 주간 학습 실패 시 기존 모델과 DAILY inference 유지

### active artifact

- PostgreSQL `analytics.active_model_assignment`가 authoritative pointer
- artifact는 private Azure Blob의 immutable version
- assignment는 manifest URI, manifest SHA256, Blob ETag/version, generation 보존
- App Settings manifest는 migration 기간 fallback으로만 유지

### 학습 인프라

- Candidate 전용 Korea Central Container Apps 환경
- Candidate 전용 manual Container Apps Job
- private ACR
- private Blob Storage
- Candidate 전용 VNet/subnet/private endpoint/private DNS
- TradingAgents Container Apps 환경과 공유 금지

### 운영 시간

- hourly Durable timer
- `America/New_York` 기준 주말 첫 tick
- 직전 XNYS 주의 마지막 성공 session과 manifest를 기준
- deterministic ID:
  `candidate-weekly-{ISO_WEEK}-{MODEL_PURPOSE}`

## 4. 공통 불변식

1. 프로젝트 범위는 수집 → 전처리 → 모델 점수 → 후보 선정까지다.
2. TradingAgents 실행·분석·비용 관리는 구현하지 않는다.
3. 모든 학습·평가 조회는 `execution_context_id`와 manifest fence를 사용한다.
4. random split 금지.
5. processor는 train에서만 fit.
6. label exit가 split/cutoff를 넘는 표본은 purge.
7. SHORT/MEDIUM artifact 교차 fallback 금지.
8. 실패를 성공 모양으로 반환하지 않는다.
9. secret·token·raw payload를 로그·문서·Git에 기록하지 않는다.
10. 코드·schema·IaC·문서 변경마다 `CHANGELOG.md` 한 줄 추가.

## 5. 세션에서 작성했으나 commit하지 않은 partial 구현

아래 파일은 원래 PC working tree에 존재하지만 이번 handoff commit에는 포함하지 않는다.
다른 PC에서는 이 목록과 아래 상세 계약을 기준으로 구현한다.

### 5.1 주간 정책·promotion

- `config/analytics/weekly_retraining_v1.yaml`
- `src/sp500_candidate_engine/analytics/promotion.py`
- `tests/analytics/test_promotion.py`

구현된 내용:

- `SHORT_5D`, `MEDIUM_20D`
- expanding window
- sequential independent compute
- automatic gated CAS activation
- automatic rollback
- absolute gate:
  - coverage
  - test blocks
  - rank IC mean
  - fold Rank IC median
  - net Top-10 return
  - Top-10 max drawdown
- incumbent 대비 relative delta gate
- 결측·NaN·무한 metric fail closed

### 5.2 weekly schema·CAS repository

- `sql/021_weekly_retraining.sql`
- `src/sp500_candidate_engine/analytics/weekly_training.py`
- `tests/analytics/test_weekly_training_repository.py`

partial 구현 내용:

- `analytics.weekly_training_run`
- `analytics.model_promotion_decision`
- `analytics.active_model_assignment`
- `analytics.active_model_assignment_history`
- weekly idempotency:
  `(iso_week, model_purpose, policy_version, input_manifest_id)`
- `anchor_session`
- `container_job_execution_name`
- guarded state transition
- `SELECT ... FOR UPDATE`
- expected-generation CAS
- activation·rollback history
- model purpose별 champion uniqueness
- manifest URI/hash를 assignment에 저장
- `get_run()`, `get_active_assignment()`, job execution name 저장

필수 재검토:

- migration을 실제 PostgreSQL 16에서 적용·rollback 검증
- champion partial unique index와 상태 transition trigger 상호작용
- initial assignment generation 0 → 1
- rollback 시 ARCHIVED → CHAMPION 허용
- manifest hash와 model weight hash 의미가 섞이지 않는지 확인

### 5.3 artifact packaging·Blob loader

- `src/sp500_candidate_engine/analytics/artifacts.py`
- `backend/prepare_candidate_artifact.py`
- `backend/app/services/model_artifacts.py`
- `tests/analytics/test_artifacts.py`
- `tests/backend/test_model_artifacts.py`

partial 구현 내용:

- CLI artifact 생성 로직을 재사용 가능한 library로 추출
- schema v2 manifest 생성
- model/config/label/feature dimension 검증
- private Blob HTTPS URI와 `file://` fallback
- managed identity download
- manifest SHA256
- model SHA256
- ETag/version 검증
- hash-keyed local cache
- temp directory → atomic rename
- model purpose/version 교차 검증

필수 재검토:

- multi-process App Service worker 간 cache race
- Windows/Linux `file://` 처리
- Blob versioning이 IaC에서 실제 enabled인지 확인
- assignment의 `artifact_hash`는 manifest hash이고,
  `model_version.artifact_hash`는 weight hash임을 유지
- cache cleanup/retention

### 5.4 weekly backend/API/job·DAILY pinning

중단 직전 background worker가 다음 파일을 수정했다.

- `backend/app/schemas/weekly_training.py`
- `backend/app/services/weekly_training.py`
- `backend/app/routers/weekly_training.py`
- `backend/app/main.py`
- `backend/app/services/pipeline_execution.py`
- `backend/app/services/model_artifacts.py`
- `src/sp500_candidate_engine/analytics/weekly_job.py`
- `pyproject.toml`
- `tests/backend/test_weekly_training_api.py`
- `tests/backend/test_daily_artifact_binding.py`

worker 보고:

- weekly API 계약 구현
- protected activation smoke
- weekly job service seam
- phase45/export/package/Blob/promotion/CAS flow
- DAILY assignment pinning
- App Settings fallback
- immutable model-version Blob path
- focused 93 tests 통과
- targeted Ruff 통과

이 보고는 parent가 전체 diff를 재검토하기 전에 작업이 중단된 상태다. 다음 세션에서
반드시 코드 리뷰와 전체 회귀를 먼저 수행한다.

orchestrator가 기대하는 정확한 endpoint:

```text
GET  /api/v1/pipeline-runs/weekly/eligibility
POST /api/v1/pipeline-runs/weekly
GET  /api/v1/pipeline-runs/weekly/{weekly_run_id}
POST /api/v1/pipeline-runs/weekly/{weekly_run_id}/activation-smoke
```

필수 동작:

- POST는 `Idempotency-Key` 요구
- safe response만 반환
- weekly run DB row가 durable acceptance owner
- Container Job 입력은 weekly_run_id/model_purpose만 전달
- activation smoke는 selection을 저장하지 않는 dry-run
- DAILY 시작 시 assignment binding을 process metadata에 저장
- pointer가 중간 변경돼도 현재 run은 pinned binding 유지
- assignment가 없을 때만 기존 App Settings fallback

### 5.5 Durable weekly orchestration

- `orchestrator/scheduler.py`
- `orchestrator/function_app.py`
- `orchestrator/workflow.py`
- `orchestrator/clients.py`
- `orchestrator/telemetry.py`
- `orchestrator/README.md`
- `tests/orchestrator/test_weekly_orchestration.py`

구현된 내용:

- New York/XNYS weekend gate
- deterministic weekly parent/model IDs
- SHORT 후 MEDIUM 순차 실행
- SHORT failure 후 MEDIUM 계속 실행
- Candidate weekly API clients
- Container Apps Job ARM start/status
- activation smoke
- timeout/error handling
- weekly summary email
- safe telemetry fields

검증 보고:

- 전체 `tests/orchestrator` 통과
- Ruff 통과
- Python compile 통과

필수 통합 검토:

- backend endpoint/response와 정확히 일치
- `CANDIDATE_TRAINING_JOB_RESOURCE_ID` App Setting
- Container Job execution override env contract
- timeout 후 기존 model 유지
- Completed Durable instance 중복 재시작 금지

### 5.6 Candidate 전용 IaC

- `infra/candidate-training.bicep`
- `infra/modules/candidate-network.bicep`
- `infra/modules/candidate-artifacts.bicep`
- `infra/modules/candidate-observability.bicep`
- `infra/modules/candidate-training-job.bicep`
- `infra/backend-appservice.bicep`
- `tests/infra/test_candidate_training_iac.py`
- `.gitignore`의 infra allowlist 변경

구현·교정 내용:

- Korea Central internal Container Apps Environment
- manual Job
- Premium private ACR
- private ZRS Blob container
- private endpoints/DNS
- Log Analytics
- training/reader managed identities
- Blob Data Contributor/Reader, AcrPull
- Candidate App VNet integration
- backend SKU/capacity parameter화, P3v3 기본값
- PostgreSQL private endpoint/DNS
- Consumption Job 2 vCPU/4Gi
- 첫 배포 image 부재를 피하는 `deployTrainingJob=false` bootstrap

중단 전 검증:

- Bicep compile 통과
- focused IaC tests 통과

남은 필수 검토:

- PostgreSQL Entra DB principal bootstrap
- ACR bootstrap 2단계:
  1. infra with `deployTrainingJob=false`
  2. image build/push
  3. infra with `deployTrainingJob=true`
- orchestrator custom ARM role에 Job start/read 권한
- backend identity와 VNet integration 배포 drift
- private DNS 실제 name resolution

### 5.7 PostgreSQL bootstrap

- `backend/grant_weekly_training_access.py`

의도:

- Entra service principal 생성
- read schemas:
  `ops`, `ref`, `market`, `fundamental`, `event`, `selection`
- write schema:
  `analytics`
- 광범위한 전체 schema 쓰기 대신 최소 권한

다음 세션에서 weekly job이 selection table을 쓰지 않는지 먼저 확인한다. phase45 workflow를
그대로 호출해 selection을 쓰면 이 권한 설계와 충돌하므로 training-only workflow로
분리해야 한다.

## 6. 현재까지 검증 증거

세션 중 확인된 결과:

- schema repository focused tests: 10 passed
- merged weekly focused suite: 34 passed
- backend worker 보고 focused suite: 93 passed
- orchestrator full tests: passed
- targeted Ruff: passed
- Candidate training Bicep compile: passed
- backend App Service Bicep compile: passed
- infra focused tests: passed
- VS Code Problems: 변경 파일 오류 없음

아직 수행하지 않은 검증:

- 현재 전체 working tree 기준 focused suite 재실행
- 전체 pytest
- 전체 Ruff
- 실제 PostgreSQL migration
- Azure Bicep what-if
- 실제 deployment
- weekly manual run
- automatic promotion/rollback E2E

## 7. 다음 세션 첫 단계

partial 코드가 원래 PC에만 있으므로 다음 중 하나를 선택한다.

### A. 원래 PC working tree를 patch로 가져올 수 있는 경우

```powershell
git diff --binary > weekly-retraining-partial.patch
```

patch를 안전한 경로로 전달한 뒤 다른 PC에서:

```powershell
git apply --check weekly-retraining-partial.patch
git apply weekly-retraining-partial.patch
```

### B. plan만 사용하는 경우

아래 Phase 1부터 파일 목록에 맞춰 재구현한다.

## 8. Phase 1 — partial 구현 통합 리뷰

1. `git status`와 전체 diff 확인
2. 다른 사용자의 dirty 변경 분리
3. backend weekly API와 orchestrator contract 비교
4. weekly repository와 backend service signature 비교
5. artifact hash 의미 검증
6. training job이 selection을 만들지 않도록 phase45 분리 여부 확인
7. IaC parameter와 App Settings 연결 확인
8. 새 코드의 broad catch·silent fallback·unsafe error 제거

## 9. Phase 2 — schema 확정

최종 schema:

```text
analytics.weekly_training_run
analytics.model_promotion_decision
analytics.active_model_assignment
analytics.active_model_assignment_history
```

weekly run 필수 필드:

```text
weekly_run_id
iso_week
anchor_session
model_purpose
policy_version
input_manifest_id
training_cutoff
label_maturity_cutoff
container_job_execution_name
status
export_run_id
challenger_model_version_id
champion_model_version_id
safe error
timestamps
```

assignment 필수 필드:

```text
model_purpose PK
model_version_id
manifest artifact_uri
manifest SHA256
Blob ETag/version
generation
weekly_run_id
activated_at
```

CAS와 rollback을 실제 PostgreSQL integration test로 검증한다.

## 10. Phase 3 — training-only workflow

현재 `run_phase45_workflow()`는 학습 후 latest score/selection까지 저장한다. 주간 학습 job은
불필요한 production selection을 만들면 안 된다.

다음 중 하나로 분리한다.

- `train_evaluate_register_model()` 추출
- 또는 `persist_selection=false`를 명시적으로 지원

권장: training/evaluation/registration을 독립 service로 추출하고 기존 phase45가 이를
호출하도록 한다.

job 단계:

1. weekly run claim
2. manifest fence
3. historical export
4. Alpha158
5. 성숙 label
6. purged walk-forward
7. LightGBM/baseline
8. registry SHADOW
9. incumbent 비교
10. immutable Blob upload
11. pre-activation smoke
12. decision 저장

## 11. Phase 4 — active pointer와 DAILY pinning

1. backend accept/execute에서 assignment 조회
2. process metadata에 binding pin
3. Blob loader로 manifest/model materialize
4. 기존 registry/config/feature 검증
5. 현재 run 전체에서 동일 binding 유지
6. assignment가 없을 때만 App Settings fallback
7. model purpose 간 fallback 금지

필수 테스트:

- pointer mid-run 변경 무영향
- retry도 같은 binding
- cache race
- Blob ETag/version mismatch
- hash mismatch
- cross-purpose 차단

## 12. Phase 5 — 자동 승격·rollback

1. versioned absolute gate
2. incumbent relative gate
3. pre-activation smoke
4. assignment row lock
5. expected generation CAS
6. pointer update/history
7. Candidate activation smoke
8. 성공 시 challenger CHAMPION, incumbent ARCHIVED
9. 실패 시 이전 assignment CAS rollback
10. rollback 실패 CRITICAL alert

activation smoke는 production score/selection을 저장하지 않는다.

## 13. Phase 6 — Durable orchestration 통합

weekly parent:

```text
eligibility
-> SHORT weekly run + Job + promotion
-> MEDIUM weekly run + Job + promotion
-> model별 독립 결과
-> email/telemetry
```

gate:

- America/New_York 주말 첫 hourly tick
- 직전 XNYS 주 마지막 session 성공
- core manifest/quality success
- 같은 week/purpose/policy/manifest 성공 run 없음

## 14. Phase 7 — IaC·identity

1. Candidate training infra bootstrap 배포(`deployTrainingJob=false`)
2. ACR image build/push
3. weekly DB Entra principal 생성
4. job 포함 재배포(`deployTrainingJob=true`)
5. backend VNet/reader identity 배포
6. orchestrator Job ARM 권한 배포
7. private DNS·Blob·ACR·Postgres 연결 확인
8. public network disabled 확인
9. P3v3 SKU가 하향되지 않는지 what-if 검증

## 15. Phase 8 — 테스트

실행 순서:

```powershell
.\.venv-alpha158\Scripts\python.exe -m pytest tests\analytics\test_weekly_training_repository.py -q
.\.venv-alpha158\Scripts\python.exe -m pytest tests\analytics\test_promotion.py tests\analytics\test_artifacts.py -q
.\.venv-alpha158\Scripts\python.exe -m pytest tests\backend\test_weekly_training_api.py tests\backend\test_daily_artifact_binding.py tests\backend\test_model_artifacts.py -q
.\.venv-alpha158\Scripts\python.exe -m pytest tests\orchestrator -q
.\.venv-alpha158\Scripts\python.exe -m pytest tests\infra -q
.\.venv-alpha158\Scripts\python.exe -m ruff check .
.\.venv-alpha158\Scripts\python.exe -m pytest -q
```

추가 integration:

- PostgreSQL migration/CAS/rollback
- Blob immutable version/ETag
- manual weekly Job
- gate fail retain
- gate pass activation
- activation smoke fail rollback
- weekly failure 중 DAILY success

## 16. Phase 9 — 문서

갱신 대상:

- `README.md`
- `MODEL_CHANGELOG.md`
- `.github/modernize/assessment/engines/facts/model-architecture.md`
- `.github/modernize/assessment/engines/facts/orchestrator-architecture.md`
- `.github/modernize/assessment/engines/facts/orchestrator-telemetry-runbook.md`
- `backend/README.md`
- `orchestrator/README.md`
- `weekly_retraining_model_design.md`
- 이 plan
- `CHANGELOG.md`

문서에는 “설계”, “구현됨”, “배포됨”을 구분한다.

## 17. Phase 10 — Azure 배포·검증

완료 결과:

- migration, private training infra, identity/RBAC, Backend, Durable workflow 배포 완료
- cutoff-fixed export `af270913-5d0b-5fdb-9323-a6a4e84d6d12`: 251,978행
- SHORT·MEDIUM 실제 Job 성공, 두 gate 모두 `REJECT`
- active assignment 0건 유지, legacy fallback 보존
- Durable parent `SUCCEEDED`, 모델별 `REJECTED` 결과 독립 보존
- 모든 Job execution terminal, weekly eligibility는 operational manifest
  `7236b8ac-8484-5a3b-b738-577d90736ed3` 선택
- ACR public disabled/default deny/bypass none, Blob public disabled/versioning enabled
- PostgreSQL ReadOnly lock, Backend P3v3/capacity 1/VNet/SCM basic auth disabled 확인

1. Bicep build/lint
2. resource-group what-if
3. migration
4. training infra bootstrap
5. image build/push
6. job/identity/RBAC
7. backend pointer dual-read
8. weekly API
9. orchestrator weekly workflow
10. 수동 SHADOW run
11. promotion dry-run
12. SHORT canary
13. MEDIUM canary
14. rollback drill
15. weekly timer enable

배포 전후 확인:

- Candidate `/health/ready`
- DAILY SHORT/MEDIUM
- active assignment generation
- current artifact hash
- Container Job terminal state
- private network
- PostgreSQL lock
- App Service SKU/capacity

## 18. Phase 11 — Git 완료

1. unrelated dirty 변경 보존
2. 전체 diff review
3. secret scan
4. `git diff --check`
5. tests/IaC 결과 기록
6. `CHANGELOG.md` 항목별 추가
7. commit

필수 trailer:

```text
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

8. 현재 branch push
9. 원격 commit 확인

## 19. 완료 기준

- SHORT/MEDIUM weekly run 멱등
- 미성숙 label 0
- leakage 0
- versioned promotion gate
- PostgreSQL active pointer CAS
- DAILY binding pin
- private Blob artifact 검증/cache
- activation smoke 자동 rollback
- weekly 장애 중 DAILY 정상
- Candidate 전용 Korea Central Job
- private network·최소 RBAC
- P3v3 유지
- targeted/full tests 통과
- Bicep what-if와 실제 배포 검증
- 운영 문서 완료
- commit/push 완료
