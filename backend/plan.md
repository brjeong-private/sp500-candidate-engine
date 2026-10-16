# Backend API 개발 계획

## 목표와 접근 방식

Candidate Engine의 실행 함수와 Azure PostgreSQL 스키마를 재사용하는 FastAPI 계층을
`backend/`에 추가한다. API는 파이프라인 실행 요청, 후보 조회, 실행 상태 조회, 정규화된
수집 데이터 조회를 제공하고 종목 토론방 포털에서 호출할 수 있도록 Azure App Service에
배포한다.

## 주요 설계 결정

- 데이터 원본은 Candidate Engine의 Azure PostgreSQL로 통일한다. 후보, 실행 상태, 수집
  레코드를 포털 MySQL에 복제하거나 이중 저장하지 않는다.
- 기존 `run_daily_process`, `run_backfill_process`, `ProcessTracker`를 서비스 계층에서
  호출하고 CLI 로직을 복제하지 않는다.
- 실행 요청은 `202 Accepted`와 `process_run_id`를 반환하고 FastAPI `BackgroundTasks`에서
  실행한다.
- `BackgroundTasks`는 프로세스 재시작 시 자동 재개를 보장하지 않는다. 단일 Uvicorn
  worker, App Service Always On, 중복 실행 차단, 시작 시 고아 `RUNNING` 작업 실패 처리,
  운영 제한 문서화로 위험을 제한한다.
- DAILY 후보 생성은 등록·고정된 LightGBM 모델의 추론만 수행한다. 모델 학습/processor fit은
  별도 CLI 작업이며 API 실행 중 자동 재학습하지 않는다.
- 조회 API는 포털 App Service Origin만 CORS 허용하고, 실행 API는 `X-API-Key`를 상수 시간
  비교로 검증한다.
- 정규화 수집 데이터는 최대 10일 범위와 커서 페이지네이션으로 제공한다.
- 기존 `infra/main.bicep`은 backfill VM 전용이므로 변경하지 않고 backend App Service용
  Bicep을 별도 파일로 둔다.

## 요구사항

| ID | 요구사항 |
|---|---|
| REQ-001 | FastAPI 기반 버전 API와 OpenAPI 명세를 제공한다. |
| REQ-002 | 일별, 일자 범위, 가격 backfill 실행 요청을 검증하고 `202 + process_run_id`로 비동기 접수한다. |
| REQ-003 | 일별 실행은 전체 수집과 후보 생성을 수행하고, 범위 실행은 거래일별 전체 수집만 수행하며, backfill은 기존 가격 backfill 동작을 유지한다. |
| REQ-004 | 후보 목록을 전체/특정 일자/기간 조건과 페이지네이션으로 조회한다. |
| REQ-005 | 관리자용 파이프라인 실행 목록, 기간 조회, 단건 진행 상태와 날짜별 상세 상태를 제공한다. |
| REQ-006 | 일봉, 기업행동, 뉴스/시장 이벤트, SEC 공시/재무, 실적 일정, 유니버스, 거래일 정규화 레코드를 최대 10일 범위에서 조회한다. |
| REQ-007 | 모든 조회는 기존 Azure PostgreSQL을 단일 원본으로 사용한다. |
| REQ-008 | 포털 Origin CORS와 실행 API Key 인증을 적용하고 비밀값을 소스에 저장하지 않는다. |
| REQ-009 | Linux Azure App Service에 단일 worker로 배포하고 Managed Identity로 PostgreSQL에 연결한다. |
| REQ-010 | 입력 오류, 충돌, DB/파이프라인 실패를 표준 오류 응답과 로그로 노출하고 핵심 API를 테스트한다. |

## 기술 컨텍스트

- 언어: Python 3.11+
- API: FastAPI, Pydantic v2, Uvicorn
- 저장소: Azure Database for PostgreSQL Flexible Server 16, `psycopg` 동기 연결
- 인증: 읽기 API는 CORS 제한, 쓰기 API는 `X-API-Key`
- 배포: 별도 Linux B3 App Service Plan(7GB), Always On, 단일 인스턴스/단일 Uvicorn worker
- 테스트: pytest, FastAPI TestClient, repository/service mock, 선택적 PostgreSQL 통합 테스트
- 성능/안전 제약:
  - 수집 데이터 조회 범위는 포함 기준 최대 10일
  - 기본 페이지 크기 100, 최대 500
  - 안정적인 `(date, primary key)` 정렬과 opaque cursor 사용
  - 상세 데이터는 명시한 dataset 경로에서만 조회하며 임의 테이블/컬럼 입력을 SQL에 결합하지
    않음
  - 실행 중 동일 유형·겹치는 날짜 요청은 `409 Conflict`

## API 계약

### 운영 및 명세

- `GET /health/live`: 프로세스 생존 확인
- `GET /health/ready`: PostgreSQL 연결과 필수 설정 확인
- `GET /docs`, `GET /openapi.json`: FastAPI OpenAPI

### 파이프라인 실행

- `POST /api/v1/pipeline-runs`
  - 헤더: `X-API-Key`
  - 요청:
    - `mode=DAILY`, `date`, `with_candidates=true`
    - `mode=RANGE`, `start_date`, `end_date`, `with_candidates=false`
    - `mode=BACKFILL`, `start_date`, `end_date`, `auto_retry`
  - 검증: 미국 거래일/날짜 순서, mode별 필드 조합, 미래 날짜, 후보 생성 정책, 활성 작업 충돌
  - 응답: `202`, `process_run_id`, `status=PENDING`, status URL

### 후보 조회

- `GET /api/v1/candidates`
  - `date` 또는 `start_date/end_date`는 상호 배타적
  - 날짜 조건이 없으면 최신 성공 selection run부터 반환
  - run 상태, 정책/모델 식별자, ticker, 회사명, sector, 순위, score, predicted return, 사유 포함
  - 동일 날짜의 재실행은 최신 성공 run을 기본으로 하고 선택적으로 `selection_run_id` 조회 허용

### 실행 로그/상태 조회

- `GET /api/v1/pipeline-runs`: 일자/범위, 상태, 유형 필터와 커서 페이지네이션
- `GET /api/v1/pipeline-runs/{process_run_id}`: 집계 상태, heartbeat, 로그 URI, 실패 사유
- `GET /api/v1/pipeline-runs/{process_run_id}/dates`: 날짜별 attempt, 수집 건수, retry 상태

### 정규화 수집 데이터 조회

- 공통 형식:
  `GET /api/v1/collection-data/{dataset}?start_date=...&end_date=...&cursor=...&limit=...`
- `start_date`, `end_date` 필수, 포함 기준 최대 10일
- dataset allowlist:
  - `daily-bars`
  - `corporate-actions`
  - `news`
  - `sec-filings`
  - `sec-facts`
  - `earnings`
  - `universe-members`
  - `exchange-sessions`
- ticker, instrument/issuer 식별자, provenance 필드, source/revision/관측 시각을 데이터셋에 맞게
  반환
- 일봉은 OHLCV, VWAP, 조정 상태를 포함하고 latest logical revision을 기본 반환
- 뉴스와 실적 일정은 공통 event 테이블에서 `event_type`으로 분리

## 구현 단계

### 1. 프로젝트 및 설정 기반 구성

- **Plan 1.1 / REQ-001, REQ-008**: `backend/app` 패키지, application factory, versioned router,
  공통 설정을 만든다.
- **Plan 1.2 / REQ-001, REQ-009**: `pyproject.toml`에 FastAPI/Uvicorn 의존성과 backend 실행
  스크립트를 추가한다.
- **Plan 1.3 / REQ-008**: `.env.example`에 `BACKEND_API_KEY`, `BACKEND_CORS_ORIGINS`,
  worker/페이지 제한 설정을 추가하고 실제 키는 App Settings 또는 Key Vault reference로만
  주입한다.

### 2. 공통 API 계약과 인프라

- **Plan 2.1 / REQ-001, REQ-010**: Pydantic request/response 모델, UTC datetime 직렬화,
  UUID/date 스키마, `items/next_cursor` 페이지 envelope를 정의한다.
- **Plan 2.2 / REQ-007**: 기존 `Database.connect()`를 사용하는 API repository 기반 클래스와
  transaction/read-only query 패턴을 만든다.
- **Plan 2.3 / REQ-010**: validation 422, auth 401, conflict 409, not found 404,
  DB/service 503/500을 일관된 error code와 request ID로 변환한다.
- **Plan 2.4 / REQ-008**: 명시적 Origin allowlist와 API Key dependency를 구현한다.
  wildcard Origin과 credential 조합은 금지한다.
- **Plan 2.5 / REQ-001, REQ-009**: liveness/readiness와 구조화된 access/application logging을
  추가한다.

### 3. 비동기 파이프라인 실행

- **Plan 3.1 / REQ-002, REQ-003**: mode별 요청 검증과 실행 서비스 매핑을 구현한다.
- **Plan 3.2 / REQ-002, REQ-003**: DAILY는
  `run_daily_process(..., run_candidates=True)`, RANGE는 거래일별
  `run_daily_process(..., run_candidates=False)`, BACKFILL은 `run_backfill_process`를
  재사용한다.
- **Plan 3.3 / REQ-002, REQ-010**: BackgroundTasks 래퍼가 예외를 process 상태와 로그에
  기록하고 성공 모양의 응답으로 실패를 숨기지 않게 한다.
- **Plan 3.4 / REQ-002, REQ-010**: 활성 범위 중복 검사, 단일 worker 내 task registry, 시작 시
  stale `RUNNING` 처리 정책을 추가한다.
- **Plan 3.5 / REQ-002**: API 응답에 즉시 사용할 `process_run_id`가 필요하므로 process 생성과
  실행을 분리하도록 기존 batch/process tracking 계층을 최소 리팩터링한다.

### 4. 후보 조회

- **Plan 4.1 / REQ-004, REQ-007**: `selection.selection_run`, `selection.candidate`,
  `candidate_reason`, instrument/issuer/universe 식별자를 조인하는 read repository를
  구현한다.
- **Plan 4.2 / REQ-004**: 최신 성공 run, 특정 일자, 기간, 특정 run 조회와 opaque cursor를
  구현한다.
- **Plan 4.3 / REQ-004, REQ-010**: 후보 router와 OpenAPI 예시, 빈 결과/잘못된 날짜 조합
  테스트를 추가한다.

### 5. 실행 로그 및 상태 조회

- **Plan 5.1 / REQ-005, REQ-007**: `ops.process_run` 목록/필터/단건 repository를 구현한다.
- **Plan 5.2 / REQ-005**: `ops.process_date_status` attempt 상세와 요약 카운트를 반환한다.
- **Plan 5.3 / REQ-005, REQ-010**: cursor 안정성, 상태 필터, 존재하지 않는 run 처리를
  테스트한다.

### 6. 정규화 수집 데이터 조회

- **Plan 6.1 / REQ-006, REQ-007**: dataset enum과 데이터셋별 명시적 query adapter를 만든다.
- **Plan 6.2 / REQ-006**: 일봉 latest revision, 기업행동, NEWS/EARNINGS event revision,
  SEC filing/fact, universe member, exchange session 조회를 구현한다.
- **Plan 6.3 / REQ-006, REQ-010**: 최대 10일 검증, 기본 100/최대 500 limit,
  ticker/식별자 필터, deterministic cursor를 공통 적용한다.
- **Plan 6.4 / REQ-006, REQ-010**: 모든 dataset 응답 스키마와 provenance 필드를 테스트한다.

### 7. 배포 및 운영

- **Plan 7.1 / REQ-009**: backend 전용 App Service Plan/App Service/Managed Identity/설정용
  `infra/backend-appservice.bicep`을 추가한다.
- **Plan 7.2 / REQ-008, REQ-009**: PostgreSQL Entra 접근 권한, 정확한 포털 Origin
  `https://web-jongmok-portal-8d0218f4.azurewebsites.net`, API Key secret reference를
  구성한다.
- **Plan 7.3 / REQ-009**: `uvicorn backend.app.main:create_app --factory --workers 1`, Always On, health check
  경로를 배포 설정에 명시한다.
- **Plan 7.4 / REQ-001, REQ-010**: `backend/README.md`에 로컬 실행, 환경 변수, curl 예시,
  OpenAPI, BackgroundTasks 운영 한계와 장애 복구 절차를 기록한다.

## 작업 목록

| ID | 선행 작업 | 실행 내용 |
|---|---|---|
| backend-bootstrap | 없음 | `backend/app/main.py`, config, router 골격과 의존성을 구성한다. |
| backend-contracts | backend-bootstrap | 공통 schema, pagination, error contract를 구현한다. |
| backend-security | backend-bootstrap | CORS와 API Key 인증을 구현한다. |
| backend-health | backend-bootstrap | liveness/readiness와 logging을 구현한다. |
| backend-process-refactor | backend-contracts | process 생성과 실행을 분리하고 API에서 즉시 run ID를 확보한다. |
| backend-trigger-api | backend-process-refactor, backend-security | DAILY/RANGE/BACKFILL 202 실행 API와 BackgroundTasks를 구현한다. |
| backend-candidate-query | backend-contracts | 후보 repository/service/router를 구현한다. |
| backend-run-query | backend-contracts | 실행 로그/status repository/service/router를 구현한다. |
| backend-data-query | backend-contracts | 8개 정규화 dataset 조회 adapter/router를 구현한다. |
| backend-tests | backend-trigger-api, backend-candidate-query, backend-run-query, backend-data-query | 단위/API/통합 테스트를 추가하고 기존 회귀 테스트를 실행한다. |
| backend-deployment | backend-security, backend-health | App Service Bicep과 배포 설정을 추가한다. |
| backend-docs | backend-tests, backend-deployment | API/환경/운영 문서를 완료한다. |

## 프로젝트 구조

```text
backend/
  app/
    __init__.py
    main.py
    config.py
    dependencies.py
    errors.py
    logging.py
    schemas/
      common.py
      candidates.py
      collection_data.py
      pipeline_runs.py
    repositories/
      candidates.py
      collection_data.py
      pipeline_runs.py
    services/
      pipeline_execution.py
    routers/
      candidates.py
      collection_data.py
      health.py
      pipeline_runs.py
  README.md
  plan.md
infra/
  backend-appservice.bicep
tests/
  backend/
    test_auth.py
    test_candidates_api.py
    test_collection_data_api.py
    test_health_api.py
    test_pipeline_runs_api.py
    test_pipeline_execution.py
```

## 테스트 및 완료 기준

- API-only 애플리케이션으로 pytest + TestClient를 기본 검증 스택으로 사용한다.
- DB repository는 mock 기반 계약 테스트와 테스트 PostgreSQL이 있을 때의 선택적 통합 테스트를
  분리한다.
- 필수 여정:
  1. 유효한 API Key로 DAILY 요청 시 즉시 202와 조회 가능한 run ID 반환
  2. 잘못된 key, 겹치는 활성 실행, 잘못된 날짜 조합이 각각 401/409/422 반환
  3. 후보 최신/일자/기간 조회가 안정적인 cursor로 중복·누락 없이 페이지 이동
  4. 실행 목록과 단건/날짜별 상세가 DB 상태와 일치
  5. 8개 dataset이 10일 제한, revision/provenance, 페이지 제한을 준수
  6. readiness가 DB 장애를 성공으로 위장하지 않고 non-2xx 반환
- 검증 명령:
  - `pytest -q tests/backend`
  - 관련 기존 회귀:
    `pytest -q tests/test_process_tracking.py tests/test_candidate_pipeline.py tests/test_backfill.py tests/selection`
  - `ruff check backend tests/backend src/sp500_candidate_engine`
- 완료 기준:
  - OpenAPI에 모든 endpoint와 오류 응답이 노출됨
  - 실제 secret이 저장소에 추가되지 않음
  - 포털 Origin 외 CORS 요청이 허용되지 않음
  - PostgreSQL 이외의 데이터 복제/이중 쓰기가 없음
  - App Service 구성과 운영 한계가 문서화됨

## 요구사항 추적

| 요구사항 | 계획 항목 | 구현 증거 |
|---|---|---|
| REQ-001 | 1.1, 1.2, 2.1, 2.5, 7.4 | `backend/app/main.py`, OpenAPI, `backend/README.md` |
| REQ-002 | 3.1~3.5 | pipeline run router/service, process tracking refactor |
| REQ-003 | 3.1, 3.2 | DAILY/RANGE/BACKFILL dispatch tests |
| REQ-004 | 4.1~4.3 | candidate repository/router/tests |
| REQ-005 | 5.1~5.3 | pipeline run repository/router/tests |
| REQ-006 | 6.1~6.4 | collection data adapters/router/tests |
| REQ-007 | 2.2, 4.1, 5.1, 6.1 | PostgreSQL repositories |
| REQ-008 | 1.1, 1.3, 2.4, 7.2 | CORS/API Key config and tests |
| REQ-009 | 1.2, 2.5, 7.1~7.3 | App Service Bicep and startup config |
| REQ-010 | 2.1, 2.3, 3.3, 3.4, 4.3, 5.3, 6.3, 6.4, 7.4 | error handling, logging, tests, runbook |

## 고려 사항

- `BackgroundTasks`는 내구성 있는 작업 큐가 아니다. App Service scale-out은 금지하고, 재시작
  중인 작업은 실패 처리 후 API로 재요청해야 한다.
- 데이터 조회는 임의 SQL API가 아니라 고정 dataset allowlist로 구현한다.
- RANGE와 BACKFILL은 의미가 다르다. RANGE는 전체 수집을 날짜별 실행하며 후보를 생성하지
  않고, BACKFILL은 기존 가격 backfill을 그대로 사용한다.
- 외부 `jongmok-toronbang` 저장소의 포털 연동 코드는 별도 작업으로 둔다.

## 후보 계약 변경 (2026-10-16)

일일 MEDIUM_20D 정량 결과와 별도 LLM 결과는 각각 정확히 20개다.
최종 통합·TradingAgents 전달 목표는 기존 5~10개에서 20개로 변경하며 재축소하지 않는다.
RRF와 최종 전달은 후속 구현이다. 현재 MEDIUM은 `parallel_preselection`에서
외부 제출 없이 종료한다. 아래 10개 검증은 당시 배포의 역사적 기록이며 새 계약의
배포 완료 증거가 아니다. SHORT_5D 레거시 수량과 API 모델 선택은 유지한다.

## 구현·배포 검증 현황 (2026-10-11, 역사적 기록)

- FastAPI 기반 실행/후보/이력/8개 데이터셋 조회 구현 완료.
- `017_backend_requests.sql` 적용: API 요청 상태 및 RANGE 부모·자식 실행 관계 보존.
- 백엔드 별도 앱 `web-sp500-candidate-8d0218f4`, 전용 B3 Plan `asp-sp500-candidate` 배포.
- 통합·회귀 테스트 146개, Ruff, 실제 PostgreSQL 로컬 조회 및 Azure 조회 검증 통과.
- 인증된 RANGE `2026-10-09`: 202 접수 후 SUCCEEDED 및 날짜 상세 조회 확인.
- 종목토론방 포털의 실제 브라우저 Origin에서 readiness/후보/일봉 `fetch()` 200/CORS 확인.
- 포털 Origin preflight 허용, 다른 Origin 거부, 미인증 실행 401, 10일 초과 조회 422 확인.
- cutoff 수정본 배포 `a802183f-8d82-4e7c-b57c-816be39a9b3c` 완료.
- 운영 DAILY `d58b5e37-0964-40fe-ba0e-11517566902d`: 2026-10-11 08:16:08 UTC SUCCEEDED.
  실행 metadata의 scoring/selection 관계를 DB에서 검증했으며 2026-10-09 후보 10개 저장 확인.
  selection `3a46dac1-fc6b-5c18-a482-67d31539aa36`, cutoff 2026-10-10 09:30 UTC,
  고정 모델 `f75be739-4149-518f-8cbe-1cf6296e619a` 사용; SHADOW 상태는 유지한다.
- 새 selection ID 명시 조회와 재배포 후 포털 실제 브라우저의 후보 10개/CORS 호출 검증 완료.
- BACKFILL 상태 조회의 502는 플랫폼 detector에서 502.0 invalid upstream response로 확인:
  05:05~05:35 UTC 44건, 502.3 없음, container recycle 없음. 정확한 연결 장애 원인은
  확정하지 않았으며 DAILY에서도 일시적 502 2건이 재현됐다. 재시도로 검증은 완료했지만
  인프라 오류 해결로 표시하지 않는다. 상세 근거·재발 대응은 [README](README.md)에 기록한다.
- 임시 secret parameter JSON과 배포 ZIP만 정리하며 모델·환경·원천 데이터를 보존한다.
