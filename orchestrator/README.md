# Candidate 일일 Durable Functions 오케스트레이터

이 디렉터리는 Candidate Engine의 운영 실행을 시작하고 외부 포털에 검증된 후보를
전달하는 독립 Azure Functions 앱이다. Candidate Engine의 수집·전처리·모델 점수·후보
선정 내부 계약은 변경하지 않으며, 외부 분석 결과나 상태를 Candidate 데이터베이스에
저장하지 않는다.

## 실행 흐름

1. 타이머는 매시 30분(UTC)에 실행되고 `America/New_York` 현지 시각 05:30에만
   직전 달력 날짜를 `candidate-daily-YYYY-MM-DD` 인스턴스로 시작한다.
2. Candidate `exchange-sessions` 조회로 XNYS 거래일인지 확인한다.
3. `DefaultAzureCredential`로 Candidate/Portal App Service ARM 상태를 확인한 뒤
   Candidate `/health/ready`, Portal `/readyz`를 확인한다. 배포 인프라는
   `TRADINGAGENTS_API_URL`을 필수로 설정하며 TradingAgents `/readyz`도
   `status=ready`인지 확인한다.
4. 날짜 기반 `Idempotency-Key`로 Candidate `DAILY` 실행을 한 번 제출하고 Durable
   timer로 상태를 확인한다. 완료 후 5~10개 후보의 날짜·순위·식별자·중복을 검증한다.
5. 검증된 후보 5~10개가 공유하는 `selection_run_id`와 `model_purpose`를 포털 자동화
   API에 한 번 제출한다. 포털 집계의 개별 작업은 재제출하지 않으며 일부 실패는
   `PARTIAL_FAILED`, 전부 실패는 `FAILED`가 된다.
6. Candidate/Portal 제한 시간을 넘으면 `TIMED_OUT`으로 끝난다. 외부 I/O와 이메일은
   activity에서만 실행되어 orchestrator replay가 부작용을 반복하지 않는다.

종결 상태는 `SUCCEEDED`, `PARTIAL_FAILED`, `TIMED_OUT`, `FAILED`다. 비거래일은
`SUCCEEDED`와 `skipped=true`로 기록한다.

## 외부 포털 계약

배포 전에 포털이 다음 서버 간 계약을 제공해야 한다.

- `Authorization: Bearer <token>`을 두 API에 전달
- `POST /api/automation/candidate-analyses`: `analysis_date`, `selection_run_id`,
  `model_purpose` JSON을 한 번 접수하고 `daily_analysis_id` 및 5~10개 `jobs` 집계 반환
- `GET /api/automation/candidate-analyses/{daily_analysis_id}`: 같은 집계를 반환
- 작업 상태는 `pending`, `running`, `completed`, `failed`이며 오케스트레이터 결과는
  포털이 반환한 모든 작업의 `decision`, `has_result`, 안전한 `error` 요약을 보존

## 배포 전제 조건

- `infra/orchestrator.bicep`은 secret 값 없이 Key Vault와 참조만 만든다. 배포 후
  `candidateApiKeySecretName`, `portalApiKeySecretName`, `emailSenderSecretName`,
  `emailRecipientsSecretName`에 해당하는 secret을 별도 보안 절차로 넣어야 한다.
  발신자와 쉼표 구분 수신자 주소는 설정/Key Vault에만 존재해야 한다.
- Candidate와 Portal App Service의 정확한 HTTPS URL과 ARM resource ID를 입력한다.
  오케스트레이터 관리 ID에 두 기존 App Service 범위의 `Reader`를 별도로 부여해야
  한다. 템플릿이 소유하지 않는 다른 resource group의 역할 할당은 자동화하지 않는다.
- 포털 자동화 API와 멱등 계약은 포털 배포에서 먼저 제공해야 한다.
- 운영 배포에서는 비어 있지 않은 HTTPS `tradingAgentsApiUrl` 파라미터가 필수다.
  로컬 격리 테스트에서만 `TRADINGAGENTS_API_URL`을 생략할 수 있다.
- Azure Managed Domain과 Communication Service 연결은 Bicep이 생성한다. 관리 ID의
  Email Sender 역할 전파와 Key Vault secret 생성이 끝난 뒤 코드를 배포한다.
- FC1 코드 ZIP은 출력된 배포 컨테이너에 업로드해야 한다. 저장소는 공유 키와 익명
  Blob 접근을 막고 관리 ID RBAC를 사용한다. private endpoint를 강제하는 조직은
  FC1 VNet 통합과 DNS를 별도로 설계해야 한다.
- `alertActionGroupResourceId`는 운영팀이 소유한 기존 Action Group의 전체 resource
  ID다. 주소를 이 템플릿이나 소스에 기록하지 않는다.

## 로컬 실행

`local.settings.example.json`을 `local.settings.json`으로 복사해 로컬 값만 넣은 뒤
`orchestrator` 디렉터리에서 의존성을 설치하고 Azure Functions Core Tools v4의
`func start`를 실행한다.
