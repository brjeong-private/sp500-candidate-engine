# 일일 수집·후보 파이프라인 오류 점검서

기준일: 2026-10-17. [공통 하네스](PROJECT-HARNESS.md)가 우선한다.
이 파일은 원격에 보존하는 운영 문서이며 로컬 전용 plan 파일이 아니다.
오류가 나면 **실패 단계·고정 run·context를 먼저 식별하고 필요한 단계만 재시도**한다.
이 문서를 실행 승인이나 예정 실행의 성공 증거로 해석하지 않는다.

## 1. 오늘 실행에서 기대할 흐름

| 항목 | 2026-10-17 확인 기준 |
|---|---|
| 정기 gate | 05:30 America/New_York, UTC 매시30분 timer에서 현지 시각 검증 |
| 오늘 한국 시각 | 2026-10-17 18:30 KST = 09:30 UTC = 05:30 EDT |
| 대상일 | 직전 달력 날짜 2026-10-16, XNYS 거래일 여부를 먼저 확인 |
| Durable ID | `candidate-daily-2026-10-16-medium_20d` |
| 정량 | MEDIUM_20D 고정 모델 추론·정확히20개, 학습·processor refit 없음 |
| LLM | 명시 선택한 event v2, 비가격 evidence, EVENT최대90 + CONTROL최대10 |
| 통합 | 두 성공 run의 같은 context에서 k=10 RRF, 성공20개 또는 SHORTFALL |
| 전달 | 성공 Fusion20 전량, `fusion-top20-v1`·정확한 identity/hash ACK |

수집·정규화 → 공통 cutoff/manifest → Quant와 LLM 병렬 → Fusion → 외부 접수 순서다.
독립 stage API는 이 자동 DAG를 대체한 scheduler가 아니라 한 단계 실행·재시도 진입점이다.
겨울에는 뉴욕05:30이 KST19:30이므로 한국 시각을 연중18:30으로 고정하지 않는다.
비거래일 skip과 cutoff 이전의 `data_complete=false`는 그 자체로 오류가 아니다.

## 2. 확인한 운영 구성과 안전 경계

확인값은 아래와 같다. 향후 변경 시 실제 App Settings와 배포 증거를 다시 대조한다.

| 위치 | 설정 | 확인값 |
|---|---|---|
| Candidate | LLM_PRESELECTION_ENABLED | true |
| Candidate | LLM_PRESELECTION_POLICY_PATH | config/llm_preselection/policy_event_v2.yaml |
| Candidate | FUSION_ENABLED / RRF_K | true / 10 |
| Durable | FUSION_ENABLED | true |
| Durable | FUSION_EXTERNAL_DELIVERY_ENABLED | true |
| Durable | FUSION_EXTERNAL_CONTRACT_VERSION | fusion-top20-v1 |
| Durable | AzureWebJobs.hourly_timer.Disabled | 미설정, 명시 비활성 아님 |
| DB | schema migration | 024_candidate_stage_runs까지 적용 |

코드·예제의 기본 OFF와 승인된 운영 ON을 구분한다.
App Settings를 바꾼 직후에는 worker 재시작·반영을 확인한 다음 수동 실행한다.
Durable의 **실제 고정 input**에 `fusion_enabled=true`, 전달 flag와 policy/hash가
들어갔는지 확인한다. 현재 설정이 ON이라는 사실만으로 과거 input도 ON이라고 추정하지 않는다.

- root `.env`·backend `.env`·App Settings·Function key·token·raw payload를 출력하지 않는다.
- DB·앱·orchestrator·외부 worker는 운영 리소스다. 임의 중지·SKU/replica 축소를 하지 않는다.
- private Storage 공개화·광범위 DB 방화벽·shared key 활성화로 접근 실패를 우회하지 않는다.
- 원천 snapshot·모델·점수·후보·terminal stage는 덮어쓰거나 삭제하지 않는다.
- 실행 중 외부 분석은 Candidate Backend 배포·상태 점검과 별개다.

## 3. 최초 점검: 읽기 전용 확인

### 3.1 리소스·함수·readiness

```powershell
az webapp show -g rg-ai-project -n web-sp500-candidate-8d0218f4 --query state -o tsv
az postgres flexible-server show -g rg-ai-project -n pg-jongmok-candidate-8d0218f4 --query state -o tsv
az functionapp function list -g rg-ai-project -n sp500-orch-f4djpkceudqgy --query "[].name" -o json
Invoke-RestMethod https://web-sp500-candidate-8d0218f4.azurewebsites.net/health/ready
```

핵심 함수는 hourly_timer·daily_orchestrator·submit_candidate_daily·fetch_fusion_handoff·
submit_fusion_handoff·resource_guardian_timer다. 함수 수만으로 코드 반영을 증명하지 않는다.
ARM Running만으로 DB·앱 readiness를 대신하지 않는다.
DB가 중지됐으면 승인된 start 경로를 사용한다. resource-level ReadOnly lock이 막으면
기존 guardian 절차처럼 해당 lock만 일시 해제하고 같은 level·notes·owners로 반드시 복구한다.
가디언 계약은 [오케스트레이터 가이드](orchestrator/README.md)를 따른다.

### 3.2 요청·단계별 run 조회

아래는 읽기 요청이다. API key는 이미 승인된 환경에서 주입하고 출력하지 않는다.

```powershell
if (-not $env:BACKEND_API_KEY) { throw "BACKEND_API_KEY must be securely provided" }
$base = "https://web-sp500-candidate-8d0218f4.azurewebsites.net"
$headers = @{ "X-API-Key" = $env:BACKEND_API_KEY }
$target = "2026-10-16"

# 오늘 대상일의 세션/cutoff 준비 여부
Invoke-RestMethod "$base/api/v1/pipeline-runs/eligibility?date=$target" -Headers $headers

# 일일 실행 이력과 특정 실행: 식별자는 실제 응답 값으로 채운다.
Invoke-RestMethod "$base/api/v1/pipeline-runs?date=$target&limit=10" -Headers $headers
# Invoke-RestMethod "$base/api/v1/pipeline-runs/$processRunId" -Headers $headers
# Invoke-RestMethod "$base/api/v1/pipeline-runs/$processRunId/dates" -Headers $headers
# Invoke-RestMethod "$base/api/v1/candidate-stage-runs/$stageRunId" -Headers $headers
```

`process_run_id`는 일일 control plane, `stage_run_id`는 독립 실행 제어다.
정량 selection_run_id·LLM run_id·Fusion fusion_run_id와 섞지 않는다.
일일 상태의 `candidate_selection_run_id`, `llm_preselection_run_id`, `fusion_run_id`를
기준으로 결과를 조회한다. 날짜별 최신 원천을 각각 가져와 임의 결합하지 않는다.

## 4. 실패 단계별 확인표

| 관찰 | 먼저 확인 | 금지하는 대응 |
|---|---|---|
| 정기 실행 자체가 없음 | ET gate·거래일·disabled flag·활성 Durable 중복·배포 indexing | 같은 날짜 실행을 무작정 여러 개 제출 |
| eligibility 불충족 | 대상 거래 세션·cutoff와 provider history | 아직 끝나지 않은 session의 데이터 사용 |
| preflight 실패 | Candidate/Portal/DB/worker readiness·private Storage·lock | 방화벽·스토리지 공개화나 readiness 성공 위조 |
| 수집 실패 | process dates·실패 dataset·quota·timeout·checkpoint | 원본 삭제·checkpoint 수동 전진·값 채우기 |
| 정량 실패 | 명시 purpose·manifest/model SHA·학습 종료일·Alpha158 순서·차원·warm-up | LLM 실패로 표시하거나 다른 모델로 fallback |
| LLM 대상0개 | universe/state의 manifest 포함·ACTIVE/LISTED·cutoff·blocking quality | 상태 gate 제거·현재 universe의 과거 적용 |
| packet 예산 초과 | truncation·missing·제공 link·전체 token 예산 | 원문 로그 출력·잘린 자료를 인용 목록에 남기기 |
| LLM 호출 실패 | endpoint/deployment/API·관리 ID role·HTTP status·RPM/TPM·retry 예산 | 다른 모델로 조용히 전환·무제한 재시도 |
| OUTPUT_VALIDATION_FAILED | 동일 instrument citation·null/결측 사유·3개 근거·수치 범위 | 근거를 만들어 넣거나 0/중립 점수로 성공 처리 |
| Fusion FAILED | 두 성공 source20·context/manifest/universe/cutoff·정책·artifact 일치 | 서로 다른 날짜·최신 run을 조합 |
| Fusion SHORTFALL | union/issuer/sector/hard gate audit·선정 수 | 21위 이하·과거 결과로 수량 보충 |
| 전달이 SKIPPED_EXISTING | Durable 고정 input의 Fusion flag, 단순 Quant 완료와 Fusion 완료 구분 | 정량20개를 최종 Fusion으로 재표시 |
| 외부 전송 실패 | 수신 계약/version·정확한20개 identity·payload hash·timeout | 일부 수락을 전량 성공으로 간주 |
| API stage INTERRUPTED | Backend 재시작·원래 contract·retry_of_run_id | terminal row를 PENDING으로 UPDATE |
| 포털 버튼만 없음 | 화면이 Quant ID인지, 분석은 Fusion ID인지·사용자 권한 | DB의 실제 Fusion ID를 Quant ID로 덮어쓰기 |

정량 성공·LLM 실패이면 기존 정량 결과를 보존한다. 반대도 동일하다.
`PARTIAL_SUCCESS`는 성공한 최종20개 전달 허가가 아니다.

## 5. 로그·DB·telemetry에서 찾을 증거

- 수집: `logs/<서울 실행일>.log`, `logs/processes/<process_run_id>.jsonl`.
  서울 실행일과 미국 price session을 혼동하지 않는다.
- API: request ID·HTTP status·failure code와 stage_run_id. full 환경이나 본문은 수집하지 않는다.
- source: `ops.execution_context`·`ops.input_manifest_member`, 정량 scoring/selection,
  LLM ranking/preselection, `selection.fusion_run`과 `fusion_audit`.
- 독립 실행: `ops.candidate_stage_run`의 status·contract_hash·input_hash·retry_of_run_id·
  started/finished와 결과 ID. request/contract 원문 대신 필요한 식별자·오류 코드만 보존한다.
- LLM: call attempt의 status·http_status·error_code·input/output hash·tokens와
  cache_source_attempt_id. raw response는 승인된 DB 안에서만 의미 검증한다.
- Durable: 고정 input·activity history·terminal output의 stage·reason·submitted_candidates.
- KQL은 [telemetry runbook](.github/modernize/assessment/engines/facts/orchestrator-telemetry-runbook.md)을 따른다.
  로그가 없다는 사실만으로 성공·실패·미실행을 단정하지 않는다.

읽기 전용 DB 조회 예:

```sql
SELECT stage_run_id, stage, target_session, status, retry_of_run_id,
       started_at, finished_at, failure_code, contract_hash
FROM ops.candidate_stage_run
WHERE target_session = DATE '2026-10-16'
ORDER BY created_at DESC;

SELECT fusion_run_id, price_session_date, status, requested_count,
       selected_count, union_count, failure_code, sector_cap_relaxed
FROM selection.fusion_run
WHERE price_session_date = DATE '2026-10-16'
ORDER BY generated_at DESC;
```

## 6. 오류 확인 후 재시도

### 수집·일일

실패 source·활성 실행·이전 idempotency key를 확인하고 승인된 일일 API로 다시 제출한다.
같은 key는 원래 실패 run을 반환할 수 있으므로 새 실행이 필요한지 구분한다.
source 성공·revision·observation은 재사용하고 원본을 삭제하지 않는다.
LLM/Fusion만 실패했다면 같은 context의 독립 stage를 사용해 수집 전체를 다시 하지 않는다.

### 독립 단계

`POST /api/v1/candidate-stage-runs`에 stage·target_session·execution_context_id를 명시한다.
Fusion은 quant_selection_run_id와 llm_preselection_run_id도 필수다.
상태 조회 후 실패·SHORTFALL이면 `POST /api/v1/candidate-stage-runs/{id}/retry`와
새 Idempotency-Key로 재시도한다.

```powershell
candidate-engine show-stage --stage-run-id <stage-uuid>
candidate-engine retry-stage --stage-run-id <failed-stage-uuid> --idempotency-key <new-key>
```

- 같은 key·다른 payload는409. 성공·실행 중 stage의 retry도409다.
- 원래 context·모델·policy·deployment 계약이 달라졌으면 retry에 섞지 말고 새 요청을 만든다.
- 독립 stage 성공은 외부 분석을 자동 시작하지 않는다.
- API BackgroundTasks는 영속 queue가 아니다. API 재시작은 소유 stage에 INTERRUPTED를 기록한다.
  OS에서 강제 종료된 CLI는 운영자 확인 없이 성공·재실행으로 가정하지 않는다.
- 외부 전달 재시도는 기존 수신처·Fusion ID·payload·idempotency key를 유지한다.
  ACK가 있으면 새20개 작업을 중복 생성하지 않는다.

## 7. 배포·검증 증거와 완료 판정

2026-10-17 운영 검증:

| 독립 stage | stage run ID | 결과 |
|---|---|---|
| QUANTITATIVE | 38ed1d0b-432a-4d08-9c14-1366b529bcd9 | 성공20개·기존 정량 결과 재사용 |
| LLM_PRESELECTION | 671c1f48-2a4b-4aab-8650-7f2fe9cc974a | 성공20개·기존 LLM 결과 재사용 |
| FUSION | 82fb9328-4622-44e0-b6fe-431ad6255fd7 | 성공20개·기존 Fusion 결과 재사용 |

OpenAPI·인증401·멱등 요청·성공 retry409를 확인했고 새 LLM attempt는0개였다.
이 source 결과의 mode는 HISTORICAL_RECONSTRUCTION이며 운영 재현 성과로 표현하지 않는다.
기존 미국10월15일 Fusion의 외부 접수는 분석46·20개 전량 ACK로 검증했다.
**접수 ACK와 외부 보고서20개 완료는 별개**이며 이 문서는 보고서 완료를 보증하지 않는다.

수집 완료, Quant20, LLM20, Fusion20, 외부 ACK, 외부 분석 완료를 각각 구분해 확인한다.
순위·수량·중복·context·정책 불일치는 성공으로 처리하지 않는다.

## 8. 오늘 장애를 기록할 로컬 양식

아래 내용은 ignored `logs/`에 별도 JSON으로 저장한다. 이 공유 문서에 실시간 원문을 붙이지 않는다.

```json
{
  "record_schema": "daily-pipeline-incident-v1",
  "checked_at": null,
  "target_session": "2026-10-16",
  "scheduled_at_kst": "2026-10-17T18:30:00+09:00",
  "durable_instance_id": "candidate-daily-2026-10-16-medium_20d",
  "process_run_id": null,
  "stage_run_id": null,
  "execution_context_id": null,
  "quant_selection_run_id": null,
  "llm_preselection_run_id": null,
  "fusion_run_id": null,
  "failed_stage": null,
  "status": "NOT_YET_OBSERVED",
  "failure_code": null,
  "retry_of_run_id": null,
  "action_taken": null,
  "verification": null
}
```

이 양식은 오늘 실행의 오류나 성공이 관찰됐다는 뜻이 아니다.
시간·상태는 실제 응답으로만 갱신하고 key/token·원천 payload·보고서 본문은 기록하지 않는다.
