# Change Log

- 2026-10-13 | Dual-Model Orchestrator | 정기 실행을 SHORT_5D 완료 후 MEDIUM_20D를 순차 실행하는 parent orchestration으로 확장했다.
- 2026-10-13 | Duplicate Guard | 동일 날짜·동일 모델의 유효한 성공 selection이 있으면 Candidate·Portal·TradingAgents를 재실행하지 않고 SKIPPED_EXISTING으로 종료하도록 추가했다.
- 2026-10-13 | Resource Guardian | 15분마다 운영 리소스 상태를 점검·안전 복구하고 실패를 경고 메일과 telemetry로 기록하도록 추가했다.
- 2026-10-13 | Orchestrator Email | 모델·대상일·상태를 포함한 메일 제목, skip 단일 메일과 safe failure code 계약을 적용했다.
- 2026-10-13 | Pipeline Telemetry | parent/model/guardian correlation telemetry와 Log Analytics KQL 운영 runbook을 추가했다.
- 2026-10-13 | Documentation | dual-model parent, guardian, private Storage와 중복 skip 기준으로 README·아키텍처·수집·모델 문서를 갱신했다.

- 2026-10-13 | Orchestrator Secrets | private-only Key Vault reference drift를 제거하고 secure Bicep parameter로 encrypted Function App Settings를 배포하도록 정합화했다.

- 2026-10-13 | Orchestrator Deployment | FC1 Function, private Storage networking, managed identity RBAC, ACS Email과 수동 SHORT_5D trigger를 Azure에 배포했다.
- 2026-10-13 | End-to-End Verification | 2026-10-09 기존 데이터 재사용, SHORT_5D 후보 10개, Portal DailyAnalysis와 TradingAgents 분석 10건, 시작·종료 메일을 검증했다.
- 2026-10-13 | Resource Remediation | 실행 전 App·PostgreSQL·MySQL·TradingAgents·Storage 상태를 제한적으로 복구하고 lock을 원상 복원하는 운영 계약을 배포했다.

- 2026-10-13 | Portal Integration | 후보 5~10개 job의 최초 dispatch를 기다릴 수 있도록 Portal batch 제출 timeout을 5분으로 분리했다.

- 2026-10-13 | Pipeline API | static eligibility route를 UUID 동적 route보다 먼저 등록해 `/pipeline-runs/eligibility`의 422 충돌을 제거했다.

- 2026-10-13 | Pipeline API | 저장된 calendar row와 분리된 XNYS 거래일·cutoff eligibility endpoint를 추가해 오케스트레이터 gate가 실제 운영 규칙을 사용하도록 수정했다.

- 2026-10-13 | Orchestrator Runtime | 비실행 Durable instance 상태를 active로 오인하지 않고 동일 deterministic ID로 재시작하도록 수동 trigger를 수정했다.

- 2026-10-13 | Orchestrator Runtime | Azure Functions Python activity binding이 인식하도록 Candidate activity 입력 annotation을 plain dict로 교정했다.

- 2026-10-13 | Orchestrator Deployment | FC1 deployment content traffic이 Storage private endpoint를 사용하도록 vnetContentShareEnabled를 활성화했다.

- 2026-10-13 | Orchestrator Preflight | STARTED 알림 전에 App Service·PostgreSQL·MySQL·TradingAgents·Storage를 제한적으로 복구하고 lock을 원상 복원한 뒤 ARM·data plane·HTTP readiness를 재검증하도록 강화했다.

- 2026-10-13 | Orchestrator Infrastructure | Durable Functions backend를 관리 ID 기반 표준 Azure Storage로 되돌리고 DTS 리소스·설정·RBAC를 템플릿에서 제거했으며 Storage endpoint 정책 점검 절차를 문서화했다.

사용자 요청에 따른 변경을 한 항목당 한 줄로 기록한다.

형식:

```text
- YYYY-MM-DD | 영역 | 변경 요약
```

## 2026-10-12

- 2026-10-12 | Orchestrator Deployment | 현재 구독에 존재하지 않는 Email Sender role 대신 제공되는 Communication and Email Service Owner role을 사용하도록 교정했다.
- 2026-10-12 | Orchestrator Deployment | Flex Consumption runtime과 충돌하는 중복 FUNCTIONS_WORKER_RUNTIME 앱 설정을 제거했다.
- 2026-10-12 | Orchestrator Infrastructure | Durable Functions 상태 backend를 Consumption Durable Task Scheduler와 task hub, system-assigned identity RBAC로 전환하고 FC1 Storage는 runtime·배포 용도로 분리했다.
- 2026-10-12 | Orchestrator Manual Trigger | Function 인증 수동 HTTP starter에 날짜·모델 목적 검증, 목적별 Durable ID·Candidate 멱등 key와 secret 없는 관리 응답을 추가했다.
- 2026-10-12 | Orchestrator Model Purpose | 모델 목적을 orchestration 입력에서 후보 조회와 포털 batch까지 전달하고 타이머 기본값을 MEDIUM_20D로 고정했다.
- 2026-10-12 | Orchestrator Verification | SHORT_5D 충돌 방지·입력 검증·기존 인스턴스 재사용·Candidate/Portal 전달을 회귀 테스트와 운영 문서에 추가했다.
- 2026-10-12 | Orchestrator Architecture | Durable 제어 흐름·상태 전이·멱등성·외부 계약·RBAC·관측성을 독립 기준 문서로 작성했다.
- 2026-10-12 | Overall Architecture | 전체 Azure 아키텍처에 오케스트레이터 control plane의 저장 경계와 terminal 상태 흐름을 보강했다.
- 2026-10-12 | Architecture Status | 전체 아키텍처의 데이터 완전성 표를 Massive·SEC·Alpha Vantage 실제 적재량과 현재 SHADOW 모델 상태로 교정했다.
- 2026-10-12 | README Architecture | 메인 README의 전체 아키텍처 아래에 구현 기준 오케스트레이터 아키텍처와 상세 문서 링크를 추가했다.
- 2026-10-12 | Architecture Documentation | Candidate Engine, FC1 Durable Functions, Portal service API, TradingAgents Container App, PostgreSQL·MySQL과 ACS Email의 전체 Azure 경계와 데이터 흐름을 문서화했다.
- 2026-10-12 | Pipeline Documentation | 05:30 ET 거래일 trigger, Candidate API 멱등 계약과 MEDIUM_20D 기본·SHORT_5D one-off 실행 정책을 수집·모델·오케스트레이터 문서에 반영했다.
- 2026-10-12 | Orchestrator Infrastructure | 운영 FC1 배포에서 TradingAgents URL을 필수 파라미터로 강제해 readiness 사전 점검이 생략되지 않도록 수정했다.
- 2026-10-12 | Orchestrator Portal Contract | 포털 연동을 Bearer 인증 기반 후보 분석 일괄 제출·집계 조회로 수정하고 5~10개 작업의 부분 실패 요약을 보존했다.
- 2026-10-12 | Orchestrator Readiness | 포털 readiness를 `/readyz`로 수정하고 설정된 경우 TradingAgents `/readyz`도 배포 전 점검하도록 추가했다.
- 2026-10-12 | Durable Orchestrator | 05:30 ET 거래일 게이트부터 Candidate 멱등 실행·후보 검증·포털 부분 실패 처리·ACS Email까지 replay-safe activity와 durable timer로 구현했다.
- 2026-10-12 | Orchestrator Infrastructure | Linux FC1, 관리 ID 기반 Storage·Key Vault·Application Insights·ACS Email과 운영 알림을 구성하는 독립 Bicep을 추가했다.
- 2026-10-12 | Orchestrator Verification | DST·HTTPS 제한·응답 크기·5~10개 후보 검증·종목별 무재시도 부분 실패를 격리 단위 테스트로 추가했다.
- 2026-10-13 | Orchestrator Private Network | FC1 VNet 통합, Blob·Queue·Table private endpoint와 private DNS를 추가하고 Storage를 관리 ID 기반 private-only 계약으로 전환했다.
- 2026-10-12 | Pipeline Planning | Candidate 일일 실행과 외부 포털·TradingAgents 분석을 Durable Function, 멱등 API, readiness, ACS Email로 연결하는 자동화 계획을 구체화했다.
- 2026-10-12 | Candidate API | expand-compatible nullable pair로 파이프라인 Idempotency-Key와 canonical 요청 hash를 영속화하고 동일 요청 재사용·payload 충돌 검증을 추가했다.

## 2026-10-11

- 2026-10-11 | Presentation | 최신 MEDIUM_20D 모델·하네스·Backend API·TradingAgents 외부 경계를 반영한 8장 중간발표 v4를 작성했다.
- 2026-10-11 | MEDIUM_20D Model | 20거래일 label·purged walk-forward·scorecard 모델 선택과 다중 모델 저장/API를 구현하고 2026-10-09 SHADOW 후보 10개를 저장했다.
- 2026-10-11 | Advanced Features | 장기 가격·SEC 가용성·총수익 label·optional Azure OpenAI 뉴스 분류와 E2~E6 readiness 계층을 추가했다.
- 2026-10-11 | Temporal Safety | 과거 후보 export의 명시적 cutoff 선택, label 성숙 경계와 historical reconstruction 제한을 검증했다.
- 2026-10-11 | Model Documentation | README·모델 아키텍처·모델 변경 이력과 ignored 후보 결과 파일을 MEDIUM_20D 실제 실행 결과로 갱신했다.
- 2026-10-11 | Backend Deployment | 기본 후보 API가 MEDIUM_20D를 반환하도록 기존 App Service에 배포하고 SHORT_5D 명시 조회·포털 CORS·readiness를 운영 검증했다.
- 2026-10-11 | API Documentation | 후보 API의 MEDIUM_20D 기본값, SHORT_5D 명시 조회, 모델 간 자동 fallback 금지와 응답 의미를 README에 명시했다.
- 2026-10-11 | Model Architecture Documentation | 하단에 추가된 Alpha158·LightGBM·scoring·결과 계약 정보를 기존 모델 흐름에 맞춰 재배치하고 다중 기간 확장을 독립 절로 정리했다.
- 2026-10-11 | Backend Verification Tests | 기존 실행 재검증의 중복 POST 방지, gateway 재시도 상한과 실패·성공 poll 증거의 영속화를 회귀 테스트로 검증했다.
- 2026-10-11 | Backend DAILY Deployment | cutoff 수정본 재배포 후 운영 DAILY의 scoring·selection 성공과 고정 SHADOW 모델 기반 신규 후보 10개, 실제 포털 CORS를 확인하고 임시 배포 파일을 정리했다.
- 2026-10-11 | Backend Gateway Diagnostics | 502.0 플랫폼 gateway 오류와 container recycle 부재를 확인하고 미확정 세부 원인·재발 대응 및 완료된 배포 검증을 운영 문서에 기록했다.

- 2026-10-11 | Model Plan | 63거래일 계획을 20거래일 중기 수익률 모델로 개정하고 다중 모델 API, 검증 scorecard, E1~E6 및 Azure OpenAI 특징 계약을 확정했다.
- 2026-10-11 | Model Plan | Azure OpenAI 뉴스 특징을 optional로 전환하고 실패 시 상태를 기록하되 미래 정보 없이 non-LLM 모델 분석을 계속하도록 정책을 수정했다.
- 2026-10-11 | Configuration Example | Azure OpenAI endpoint·deployment·API version과 Entra service-principal 환경변수 예시를 추가했다.
- 2026-10-11 | Backend Verification | 실행 검증의 대기 시간을 설정 가능하게 하고 run ID·응답 시각·상태·request ID를 영속 기록하며 후보 조회의 미지원 process 필터를 제거했다.
- 2026-10-11 | Backend Artifact Deployment | 명시적 모델·manifest의 원격 checksum 검증과 Bicep checksum 설정을 추가하고 로컬 추론 검증 산출물을 Git 제외했다.

- 2026-10-11 | Backend Inference Cutoff | API 추론 export에 요청 session의 결정 cutoff를 명시해 재수집 관찰 시각이 상속되어 과거 후보 생성이 차단되는 오류를 수정하고 CLI export 기본 동작을 보존했다.

- 2026-10-11 | Backend Live | 전용 B3 App Service에 API를 배포하고 Managed Identity PostgreSQL 조회, 인증된 RANGE 완료와 실제 종목토론방 브라우저 CORS 호출을 검증했다.

- 2026-10-11 | Backend Plan | PostgreSQL 단일 원본, 비동기 실행·후보·실행 이력·8개 데이터셋 API, 10일 조회 제한과 App Service 배포·검증 계획을 작성했다.
- 2026-10-11 | Backend Foundation | FastAPI application factory, 정확한 포털 Origin CORS, 실행 API Key 인증, 표준 오류·request ID·상태 확인 API와 backend 의존성을 추가했다.
- 2026-10-11 | Backend Read APIs | 날짜별 최신 성공 후보, 필터 결합 서명 커서, 8개 정규화 데이터셋의 10일 조회 및 provenance와 API 실행 상태·날짜별 attempt 조회를 typed 모델과 SQL/API 테스트로 추가했다.
- 2026-10-11 | Backend Status | API 후보 생성이 진행 중이면 수집 완료 시각을 상속하지 않고 API 소유 finished_at의 null 상태를 유지하도록 조회와 회귀 테스트를 보강했다.
- 2026-10-11 | Backend Execution | 거래일·완료 cutoff·provider 범위를 검증한 API 접수를 원자적으로 영속화하고 동일 run ID, RANGE child ID, 전역 활성 작업 제한, API 소유 중단 복구와 후보 추론 warm-up export를 기존 배치 함수에 연결했다.
- 2026-10-11 | Backend Operations Docs | API 소유 상태·중단 복구, inference-only DAILY의 고정 model/manifest hash·설정 기반 61-session 이력·영속 출력 경로와 공유 B1의 미검증 용량 제한을 문서화했다.
- 2026-10-11 | Backend Workspace | BACKEND_WORKSPACE_DIR와 명시적 model manifest·checksum 환경 설정을 기존 service 생성자에 연결하고 Qlib·후보 출력을 영속 workspace에 저장하면서 배포된 config·SQL 경로와 분리했다.
- 2026-10-11 | Model Core | 기존 5일 경로를 보존하면서 versioned 20-session label·LightGBM config와 horizon별 학습·평가·scoring 전파를 추가했다.
- 2026-10-11 | Model Safety | 20일 E1 scoring의 LLM 비의존성을 명시하고 historical cutoff 선택과 fit 시점 label 성숙도 검사를 fail-closed로 강화했다.
- 2026-10-11 | Backend Model Provisioning | 명시적으로 선택한 registry LightGBM과 parquet feature 순서를 검증해 weights 및 checksum manifest만 배치하는 artifact 준비 도구를 추가했다.
- 2026-10-11 | Backend Least Privilege | API 소유 DAILY·BACKFILL은 runtime migration을 생략하고 일별 수집의 DDL을 명시적으로 비활성화하면서 CLI의 자동 migration 기본 동작을 보존했다.
- 2026-10-11 | Backend Deployment | 포털을 변경하지 않는 별도 App Service Bicep, 비밀값 제외 source ZIP, Entra DB 권한 부여 도구와 운영 문서를 추가했다.

- 2026-10-11 | Backfill | Massive Basic 허용 범위 내 추가 1년 248 sessions를 실패·재처리 없이 적재해 전체 500 sessions를 확보했다.
- 2026-10-11 | Data Quality | 2년 범위 미래 데이터 위반 0, semantic duplicate 0, SPY 500/500, blocking issue 0을 검증했다.
- 2026-10-11 | Model Retraining | 2년 Qlib export 251,471행으로 Model v2를 재학습하고 LightGBM SHADOW 후보 10개를 갱신했다.
- 2026-10-11 | Fix | Momentum·Ridge는 평가 baseline으로만 유지하고 `PREDICTED_5D_RETURN` 후보 scoring은 Qlib LightGBM artifact로 고정했다.
- 2026-10-11 | Architecture | 전처리·Alpha158·raw-return label·walk-forward·평가·scoring·selection 계약과 다이어그램을 모델 아키텍처 문서 및 README에 추가했다.
- 2026-10-11 | Model v2 | 학습 label을 SPY 초과수익에서 개별 종목 D+1 조정 시가~D+5 조정 종가 raw 수익률로 변경하고 v1 artifact를 보존했다.
- 2026-10-11 | Evaluation | Top-5/10 raw·cost-adjusted return, 양의 수익률 비율과 5개 중첩 cohort max drawdown metric을 추가했다.
- 2026-10-11 | Selection | Score를 `PREDICTED_5D_RETURN`으로 저장하고 음수 예측 후보 허용 및 `NON_POSITIVE_PREDICTION` reason을 추가했다.
- 2026-10-11 | Notebook | Label·model·selection config를 수정하며 재실행할 수 있는 v2 학습 notebook과 model change log를 갱신했다.
- 2026-10-11 | Phase 6 | 명시적 date 기반 candidate pipeline과 CLI, daily opt-in 연결, backfill 분리, challenger gate와 drift metric을 구현했다.
- 2026-10-11 | Shadow Replay | 최근 out-of-sample 20 sessions에서 매일 후보 10개, shortfall 0, sector cap 완화 0을 검증했다.
- 2026-10-11 | Documentation | README와 아키텍처·수집·데이터 문서를 현재 Qlib·scoring·selection 구현 상태로 갱신했다.
- 2026-10-11 | Maintenance | plan·phase result·candidate 임시 파일, notebook output, logs와 작업 환경을 Git 제외 대상으로 정리했다.
- 2026-10-11 | Notebook | Python 3.11 `.venv-alpha158` 기반 재현 환경, versioned config, 비대화형 Phase 4~5 notebook과 실행 가이드를 추가했다.
- 2026-10-11 | Schema | Model registry·scoring·daily score와 selection run·candidate·reason migration 014~015를 적용했다.
- 2026-10-11 | Training | Momentum·Ridge·Qlib LightGBM과 purged walk-forward 평가를 구현하고 2026-10-09 데이터에서 shadow 모델을 등록했다.
- 2026-10-11 | Selection | 503개 종목 점수와 rank·percentile을 저장하고 sector·issuer 제약을 적용한 10개 shadow 후보를 생성했다.
- 2026-10-11 | Data | 2026-10-09 production 수집을 완료하고 252-session Qlib export를 생성했다.
- 2026-10-11 | Documentation | Phase 4·5 결과를 ignored `phase-result/` 하위에 기록하고 계획의 완료 상태와 실제 metric을 갱신했다.
- 2026-10-11 | Migration | Azure PostgreSQL에 analytics migration 011~013을 적용하고 schema ledger와 신규 테이블을 검증했다.
- 2026-10-11 | Benchmark | 보존된 Massive raw snapshot에서 2025-11-24 SPY benchmark를 복구하고 재실행 변경 0건을 확인했다.
- 2026-10-11 | Qlib Export | 251 sessions·540 instruments·126,233 rows의 split-adjusted historical export를 생성·영속화하고 동일 hash 재실행을 검증했다.
- 2026-10-11 | Qlib Validation | 실제 1년 artifact에서 Alpha158 126,236행·158차원·Infinity 0을 검증했다.
- 2026-10-11 | Fix | 다중 FULL partition과 cross-dataset DELTA lineage 및 psycopg cursor executemany를 실제 historical export에 맞게 수정했다.
- 2026-10-11 | Documentation | Phase 3 뒤에 Phase 4 진입 전 migration·benchmark·historical export gate와 실행 결과를 추가했다.

## 2026-10-10

- 2026-10-10 | Analytics Phase 1 | Versioned XNYS calendar, split·dividend adjustment, manifest-constrained daily-bar repository와 데이터 기초 테스트를 추가했다.
- 2026-10-10 | Analytics Phase 2 | Qlib export schema, CSV staging, binary provider exporter, artifact hash와 export 품질 gate를 추가했다.
- 2026-10-10 | Analytics Phase 3 | Alpha158 runtime adapter, train-only processor artifact, 5-session SPY 초과수익 label과 feature·label persistence를 추가했다.
- 2026-10-10 | Dependency | Python 3.11/3.12 analytics 환경용 pyqlib·pyarrow·PyYAML optional dependencies를 추가했다.
- 2026-10-10 | Testing | Analytics Phase 1~3 단위·회귀 테스트와 실제 Qlib Alpha158 integration smoke test를 추가했다.
- 2026-10-10 | Documentation | Phase 1~3 진행 단계와 구현·검증 결과를 각각 별도 결과 문서로 기록했다.
- 2026-10-10 | Harness | 프로젝트 범위를 수집·전처리·모델 점수·후보 선정으로 고정하고 데이터 무결성·미래 누수 방지·평가·실패 규칙을 공통 하네스로 추가했다.
- 2026-10-10 | Planning | 후보 선정 계획에 점수 해석, 전체 universe 순회, 시점 재현, 학습 라벨, 후보 평가 관련 검토 의견을 반영하고 TradingAgents 구현 범위를 제거했다.
- 2026-10-10 | Documentation | README의 전체 아키텍처와 수집 파이프라인을 정비하고 데이터 스키마 ER 다이어그램을 추가했으며 데이터 원천 미구현 사유·1년 backfill 통합 결과를 반영하고 Azure Backfill VM 내용을 제거했다.

## 2026-10-09

- 2026-10-09 | Backfill | XNYS 세션 기반 3개월 backfill dry-run 계획과 API 호출량 계산을 추가했다.
- 2026-10-09 | Temporal | Production 수집이 operational 또는 historical reconstruction mode를 명시적으로 전달하도록 변경했다.
- 2026-10-09 | Reference | 변경 없는 ticker identifier가 날짜별로 중복 생성되지 않도록 validity interval 처리를 추가했다.
- 2026-10-09 | Reference | 변경 없는 SEC instrument state가 날짜별로 중복 생성되지 않도록 validity interval 처리를 추가했다.
- 2026-10-09 | Documentation | 3개월 backfill 위험과 실행 전 필수 수정 사항을 임시 데이터 검토 문서에 추가했다.
- 2026-10-09 | Process | 앞으로 모든 사용자 요청 변경을 이 파일에 한 줄씩 기록하도록 저장소 규칙을 추가했다.
- 2026-10-09 | Testing | 3개월 XNYS 65세션과 Massive·Alpha backfill 예산을 검증하는 테스트를 추가했다.
- 2026-10-09 | Documentation | README와 파이프라인 문서에 네트워크를 실행하지 않는 `plan-backfill` 명령을 추가했다.
- 2026-10-09 | Dependency | XNYS 공식 세션 계산을 위해 `exchange-calendars`와 잠금 의존성을 추가했다.
- 2026-10-09 | Backfill | `plan-backfill`의 날짜 필드를 ISO 문자열로 직렬화해 CLI JSON 출력을 수정했다.
- 2026-10-09 | Review | 3개월 backfill 검토 문서에 수정 완료 항목과 남은 실행 blocker를 구분해 기록했다.
- 2026-10-09 | Schema | 일·배치 process run과 날짜별 수집·재처리 상태를 저장하는 migration을 추가했다.
- 2026-10-09 | Logging | 실행 1회당 JSONL 파일 하나를 사용하는 process 진행 로그 경로를 Git 제외 대상으로 추가했다.
- 2026-10-09 | Massive | Backfill이 가격 한 번만 호출할 수 있도록 grouped daily 수집 메서드를 분리했다.
- 2026-10-09 | Backfill | 날짜별 universe·Massive 가격 snapshot과 reconstruction manifest를 멱등 저장하는 repository를 추가했다.
- 2026-10-09 | Process | 실행 상태·heartbeat·날짜별 시도·재처리 queue를 관리하는 process tracker와 실시간 JSONL writer를 추가했다.
- 2026-10-09 | Backfill | 전체 1차 수집 후 실패 날짜 확인과 자동 재처리를 수행하는 Massive 가격 backfill orchestrator를 추가했다.
- 2026-10-09 | Backfill | range action·news를 일별 05:30 ET cutoff로 필터링해 derived snapshot과 manifest에 연결했다.
- 2026-10-09 | Daily | 일일 production 수집을 process run과 실행별 JSONL 로그로 감싸는 runner를 추가했다.
- 2026-10-09 | CLI | 일일 실행, backfill, 기간 재처리, process 상태 조회 명령을 추가했다.
- 2026-10-09 | Progress | process 상태 조회에 날짜별 최신 시도·수집량·실패·재처리 상태를 포함했다.
- 2026-10-09 | Documentation | README와 파이프라인 문서에 일일·batch·기간 재처리·진행 조회 명령과 process 로그 형식을 추가했다.
- 2026-10-09 | Testing | process 실행별 단일 파일 로그와 일일·batch·재처리·상태 CLI 노출 테스트를 추가했다.
- 2026-10-09 | Quality | production과 backfill의 누락 가격 품질 이슈 dataset code를 분리했다.
- 2026-10-09 | Maintenance | batch·collector 코드의 import와 format을 프로젝트 규칙에 맞게 정리했다.
- 2026-10-09 | Fix | Massive grouped daily 메서드와 range collector의 코드 경계를 수정하고 누락된 타입 import를 보완했다.
- 2026-10-09 | Fix | Backfill repository 메서드 경계를 재구성해 price·parent range·derived supplement persistence를 복구했다.
- 2026-10-09 | Transaction | 날짜별 derived supplement와 final manifest 저장을 하나의 DB transaction으로 묶었다.
- 2026-10-09 | Fix | Backfill·수동 재처리 runner가 process 결과를 올바르게 반환하도록 수정했다.
- 2026-10-09 | Maintenance | Batch pipeline import 순서를 lint 규칙에 맞게 정리했다.
- 2026-10-09 | Harness | 일별 cutoff action·news 필터와 동일 payload revision 결정 로직을 순수 함수로 분리했다.
- 2026-10-09 | Testing | 다음 날 05:30 ET cutoff, 미래 action·news 제외, 동일 payload revision 중복 방지 테스트를 추가했다.
- 2026-10-09 | Architecture | Process·parent raw·daily derived snapshot·logical revision·manifest 관계와 중복·미래 누수 불변식을 데이터 아키텍처에 추가했다.
- 2026-10-09 | SEC | SEC filing·fact derived snapshot, logical dedupe, observation, daily manifest persistence를 추가했다.
- 2026-10-09 | Backfill | SEC bulk를 기간당 한 번 다운로드·정규화하고 accepted_at cutoff 이하 filing·fact만 날짜별 snapshot에 연결했다.
- 2026-10-09 | Maintenance | SEC 통합 후 사용하지 않는 backfill repository import를 제거했다.
- 2026-10-09 | Transaction | Parent range ingestion run과 원문 snapshot 저장을 하나의 transaction으로 묶었다.
- 2026-10-09 | Architecture | Fundamental observation과 process run·날짜별 retry 상태 테이블을 데이터 아키텍처 표에 반영했다.
- 2026-10-09 | Documentation | README에 최대 데이터 backfill 포함 범위와 Alpha historical 제외·남은 작업을 갱신했다.
- 2026-10-09 | Review | 임시 검토와 파이프라인 문서를 최대 데이터 backfill 구현 완료·Azure 실행 대기 상태로 갱신했다.
- 2026-10-09 | Architecture | 전체 아키텍처의 SEC·backfill 구현 상태와 남은 최적화 항목을 갱신했다.
- 2026-10-09 | Documentation | 남은 작업에 dataset checkpoint cursor 연결을 명시했다.
- 2026-10-09 | Recovery | 중단 후 5분 이상 RUNNING 상태인 날짜 attempt를 실패·재처리 대기로 복구하도록 추가했다.
- 2026-10-09 | CLI | 수동 재처리 결과에 parent process와 stale attempt 복구 수를 포함했다.
- 2026-10-09 | Provenance | 기간 원문 parent snapshot과 날짜별 derived snapshot의 parent-child lineage persistence를 추가했다.
- 2026-10-09 | Backfill | Parent range snapshot ID를 모든 날짜 수집과 자동 재처리 경로에 전달하도록 연결했다.
- 2026-10-09 | Temporal | News range가 마지막 세션 다음 날 05:30 ET까지 빈틈없이 chunk되도록 수정했다.
- 2026-10-09 | Review | 임시 backfill 검토 문서를 가격 batch·자동 재처리·process 로그 구현 상태로 갱신했다.
- 2026-10-09 | Policy | 미래 누수 방지형 최대 backfill 범위와 일별 05:30 ET cutoff·Alpha historical 제외 정책을 기록했다.
- 2026-10-09 | Documentation | 공식 수집 파이프라인에 range raw와 날짜별 derived snapshot 분리 원칙을 추가했다.
- 2026-10-09 | Backfill | Dry-run 계획의 남은 작업을 현재 구현 상태에 맞게 staging·checkpoint·공식 reference로 갱신했다.
- 2026-10-09 | Deduplication | 날짜별 derived snapshot을 직전 cutoff 이후 delta로 제한해 action·news·filing·fact 관찰 중복을 줄였다.
- 2026-10-09 | Testing | 이전 cutoff 이전 항목과 현재 cutoff 이후 항목이 derived snapshot에서 모두 제외되는 테스트를 추가했다.
- 2026-10-09 | Massive | Backfill용 전체 기간 dividend·split과 주 단위 news pagination collector를 추가했다.
- 2026-10-09 | Temporal | 거래 세션 다음 날 05:30 ET backfill cutoff 계산과 split 이용 가능 시각 규칙을 추가했다.
- 2026-10-09 | Backfill | 날짜별 cutoff로 필터된 Massive action·news derived snapshot과 final manifest persistence를 추가했다.
- 2026-10-09 | Azure | Ubuntu VM 배포와 3개월 backfill 실행을 위한 필수 deployment plan skeleton을 추가했다.
- 2026-10-09 | Azure | 로컬 backfill 구현 승인과 Azure 배포 대기 상태를 deployment plan에 분리해 기록했다.
- 2026-10-09 | Azure | Ubuntu VM·VNet subnet·NSG·public IP를 idempotent하게 생성하고 auto-shutdown schedule 부재를 검증하는 스크립트를 추가했다.
- 2026-10-09 | Azure | AVM 기반 NSG·subnet·Ubuntu B4ms VM·NIC·public IP Bicep 템플릿을 추가했다.
- 2026-10-09 | Azure | VM AVM output contract에 맞춰 managed identity 출력 타입과 public IP 조회 방식을 수정했다.
- 2026-10-09 | Security | VM 비밀번호와 validation parameter를 ignored 임시 파일로 생성하고 현재 사용자 전용 ACL을 적용했다.
- 2026-10-09 | Azure | Azure validation recipe의 core·Docker N/A·policy 체크리스트를 deployment plan에 추가했다.
- 2026-10-09 | Azure | Bicep build·resource-group validate·what-if와 policy 검증을 통과하고 proof를 기록했다.
- 2026-10-09 | Build | Python wheel build와 전체 35개 테스트를 배포 전 최종 검증했다.
- 2026-10-09 | Security | VM managed identity의 Azure RBAC 불필요와 PostgreSQL least-privilege role 후속 생성을 검증 계획에 기록했다.
- 2026-10-09 | Azure | 배포 전 실행한 테스트·lint·Bicep build·validate·what-if·wheel build 명령과 결과를 validation proof에 기록했다.
- 2026-10-09 | Azure | 공식 azure-validate workflow 완료 후 deployment plan 상태를 Validated로 변경했다.
- 2026-10-09 | Repository | 사용자 요청에 따라 `infra/`를 Git 추적 대상에서 제외했다.
- 2026-10-09 | Azure | Korea Central B4ms 용량 부족에 따라 사용자 승인 fallback인 Standard_D4s_v5로 계획과 배포 스크립트를 변경했다.
- 2026-10-09 | Azure | Standard_D4s_v5로 Bicep build·validate·what-if을 재통과하고 plan을 다시 Validated 상태로 변경했다.
- 2026-10-09 | Azure | D4s_v5 용량 부족 후 사용자 승인 fallback인 Standard_D4as_v5로 계획·스크립트·Bicep을 변경했다.
- 2026-10-09 | Azure | Standard_D4as_v5 validate·what-if 재검증 후 plan을 Validated로 확정했다.
- 2026-10-09 | Azure | 비밀번호 SFTP로 앱·환경설정을 전송하고 systemd backfill service를 준비하는 bootstrap 도구를 추가했다.
- 2026-10-09 | Dependency | Azure VM password SFTP 배포를 위해 Paramiko와 잠금 의존성을 추가했다.
- 2026-10-09 | Azure | 구독·Korea Central·B4ms·VNet·quota·비용·정책·인터넷 SSH 승인 내용을 반영해 deployment plan을 Ready for Validation으로 확정했다.
- 2026-10-09 | Documentation | README에 Azure backfill VM 구성과 배포 스크립트·임시 비밀 파일 정책을 추가했다.
- 2026-10-09 | Maintenance | Azure upload helper의 import와 line format을 lint 규칙에 맞게 정리했다.
- 2026-10-10 | Azure | West US 3 전용 VNet·subnet·NSG·D-series VM과 고정 공인 IP 기반 PostgreSQL 방화벽 연결로 배포 계획과 IaC를 전환했다.
- 2026-10-10 | Fix | 공동 제출 SEC 문서의 accession을 CIK와 함께 식별하도록 parser·DB unique key·persistence를 수정했다.
- 2026-10-10 | Observability | 장시간 range download·SEC parse 단계에 60초 heartbeat와 실패·완료 process 로그를 추가했다.
- 2026-10-10 | Data | 2026-07-09~2026-10-08 XNYS 65개 세션 backfill을 실패·재처리 없이 완료하고 미래 누수·중복 revision 0을 검증했다.
- 2026-10-10 | Documentation | 3개월 backfill 실측 bar·SEC 적재량과 provider 원본 결측 3건을 README·데이터 아키텍처·파이프라인 문서에 반영했다.
- 2026-10-10 | Maintenance | 실행별 JSONL process 로그 디렉터리를 Git 추적에서 제외했다.
- 2026-10-10 | Review | 3개월 실행 결과와 Yahoo prototype 대비 Massive historical sample의 분석 적합성을 ignored 임시 검토 파일로 작성했다.
- 2026-10-10 | Data | 2026-04-09~2026-07-08의 62개 XNYS 세션을 추가 적재해 총 127거래일·63,878 bars의 6개월 데이터를 확보했다.
- 2026-10-10 | Documentation | 6개월 통합 bar·action·news·SEC 적재량과 무결성 검증 결과를 README·아키텍처·임시 실행 결과에 반영했다.
- 2026-10-10 | Architecture | Qlib 분석 적합성 지표·현재 historical schema·목표 export 계약·readiness gate를 별도 문서로 작성했다.
- 2026-10-10 | Fix | 6개월 action 조회가 100페이지를 넘지 않도록 Massive dividends·splits를 비중첩 31일 chunk로 수집하게 수정했다.
- 2026-10-10 | Fix | cutoff 직전 Wikipedia revision에 constituents 표가 없으면 더 오래된 유효 revision을 선택하도록 미래 누수 없는 fallback을 추가했다.
- 2026-10-10 | Data | 1년 raw snapshot에서 Massive bar 125,730건의 VWAP·조정 상태와 SPY 250거래일 benchmark를 API 재호출 없이 revision 적재했다.
- 2026-10-10 | Pipeline | 신규 일일·backfill이 VWAP, 가격·거래량 조정 상태, Massive 요청 옵션과 `PRICE_RETURN` benchmark를 보존하도록 확장했다.
- 2026-10-10 | Documentation | 데이터 수집 보완 10개 항목의 반영 여부·제한과 1년 변경분 재처리·멱등 검증 결과를 기록했다.
- 2026-10-10 | Data | 2025-10-09~2026-04-08 parent run 123일과 manual retry 1일을 완료해 총 251거래일·126,233 logical bars를 확보했다.
- 2026-10-10 | Review | Qlib readiness 문서를 1년 실측 coverage·VWAP·adjustment·benchmark·outlier·temporal integrity 지표로 갱신했다.
