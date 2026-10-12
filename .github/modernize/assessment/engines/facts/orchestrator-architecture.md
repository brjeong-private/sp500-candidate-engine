# Durable Functions 오케스트레이터 아키텍처

갱신일: 2026-10-12

이 문서는 Candidate Engine의 일일 실행과 외부 분석 시스템 전달을 조정하는
`orchestrator/`의 기준 설계다. 오케스트레이터는 수집·전처리·모델 점수·후보 선정
알고리즘을 소유하지 않는다. Candidate API를 통해 해당 파이프라인을 시작하고 검증된
selection run을 외부 Portal에 전달하는 control plane이다.

## 책임과 경계

| 영역 | 오케스트레이터 책임 | 비책임 |
|---|---|---|
| 일정 | 05:30 ET gate, 날짜별 단일 Durable instance | 거래 세션 원장 생성 |
| 사전 점검 | Candidate·Portal ARM/runtime readiness, TradingAgents readiness | 외부 서비스 복구·배포 |
| Candidate 실행 | 멱등 DAILY 접수, 상태 polling, 후보 계약 검증 | 수집·특징·모델·선정 계산 |
| Portal 전달 | selection run 참조 일괄 제출, 집계 polling | 후보 row 복제, 분석 실행·저장 |
| 상태·알림 | Durable state, terminal summary, ACS Email, Azure Monitor | Candidate/Portal 업무 데이터 저장 |

Candidate 결과의 단일 원본은 PostgreSQL이고, 외부 분석 job·결과의 단일 원본은 Portal
MySQL이다. 오케스트레이터 Storage에는 Durable 실행 이력과 task state만 저장한다.

## 논리 컴포넌트

```mermaid
flowchart TB
    subgraph Trigger["Trigger and Durable Control"]
        Timer["Hourly timer<br/>UTC minute 30"]
        Gate["05:30 America New York gate<br/>previous calendar date"]
        Instance["Deterministic instance<br/>candidate-daily-date"]
        Workflow["Replay-safe daily orchestrator"]
        DurableState[("Storage<br/>history queues tables")]
    end

    subgraph Activities["I/O Activities"]
        Session["Check XNYS session"]
        Ready["ARM and runtime readiness"]
        SubmitCandidate["Submit Candidate DAILY"]
        PollCandidate["Poll Candidate run"]
        Verify["Fetch and verify candidates"]
        SubmitPortal["Submit selection run reference"]
        PollPortal["Poll Portal aggregate"]
        Notify["Send ACS Email"]
    end

    subgraph Services["Owned and External Services"]
        Candidate["Candidate API"]
        CandidateDb[("PostgreSQL<br/>candidate source of truth")]
        Portal["Portal automation API"]
        PortalDb[("MySQL<br/>analysis source of truth")]
        Trading["TradingAgents Container App"]
        Email["ACS Email"]
    end

    Timer --> Gate --> Instance --> Workflow
    DurableState <--> Workflow
    Workflow --> Session --> Candidate
    Workflow --> Ready
    Ready --> Candidate
    Ready --> Portal
    Ready --> Trading
    Workflow --> SubmitCandidate --> Candidate
    Workflow --> PollCandidate --> Candidate
    Candidate --> CandidateDb
    Workflow --> Verify --> Candidate
    Workflow --> SubmitPortal --> Portal
    Workflow --> PollPortal --> Portal
    Portal --> PortalDb
    Portal --> Trading
    Workflow --> Notify --> Email
```

`daily_orchestrator`에는 네트워크 호출, 현재 시스템 시각 조회, random ID 생성과 직접
로깅을 두지 않는다. 외부 I/O는 activity에 격리하고 대기에는 durable timer를 사용해
history replay가 외부 요청을 반복하지 않도록 한다.

## 일일 제어 흐름

```mermaid
sequenceDiagram
    participant T as Timer
    participant D as Durable Orchestrator
    participant C as Candidate API
    participant P as Portal API
    participant A as ACS Email

    T->>T: Convert UTC to America/New_York
    alt Local time is not 05:30
        T-->>T: Exit
    else Local time is 05:30
        T->>D: Start candidate-daily-date once
        D->>C: Query XNYS exchange session
        alt Not an exchange session
            D-->>D: SUCCEEDED and skipped
        else Exchange session
            D->>C: ARM state and health ready
            D->>P: ARM state and readyz
            D->>A: STARTED notification
            D->>C: POST DAILY with Idempotency-Key
            loop Until Candidate terminal or timeout
                D->>C: GET pipeline run
                D-->>D: Durable timer
            end
            D->>C: GET candidates by date and model purpose
            D->>D: Verify 5 to 10 rows and one selection run
            D->>P: POST analysis date and selection run reference
            loop Until all Portal jobs terminal or timeout
                D->>P: GET daily analysis aggregate
                D-->>D: Durable timer
            end
            D->>A: Terminal summary notification
        end
    end
```

타이머는 UTC 기준 매시 30분 실행되지만 `America/New_York` 변환 결과가 정확히
05:30일 때만 진행한다. 대상일은 현지 직전 달력 날짜이며, Candidate의 XNYS session
조회 결과가 비거래일이면 외부 분석을 시작하지 않는다. 이 구조는 DST 전환과 주말·휴장
판정을 서로 분리한다.

## 상태 모델

```mermaid
stateDiagram-v2
    [*] --> SessionCheck
    SessionCheck --> SUCCEEDED: not exchange session
    SessionCheck --> Preflight: exchange session
    Preflight --> CandidateRunning: ready
    Preflight --> FAILED: readiness or configuration error
    CandidateRunning --> CandidateRunning: durable poll
    CandidateRunning --> TIMED_OUT: candidate deadline
    CandidateRunning --> FAILED: candidate terminal failure
    CandidateRunning --> PortalRunning: candidate succeeded and verified
    PortalRunning --> PortalRunning: durable poll
    PortalRunning --> TIMED_OUT: portal deadline
    PortalRunning --> SUCCEEDED: all jobs completed with results
    PortalRunning --> PARTIAL_FAILED: mixed success and failure
    PortalRunning --> FAILED: all jobs failed
    SUCCEEDED --> [*]
    PARTIAL_FAILED --> [*]
    TIMED_OUT --> [*]
    FAILED --> [*]
```

Candidate의 `PARTIAL_SUCCESS`는 terminal 상태지만 성공으로 간주하지 않는다. Candidate
단계는 `SUCCEEDED`만 다음 단계로 진행한다. Portal의 `completed` job도 `has_result=true`
여야 성공으로 집계한다. 비거래일은 `SUCCEEDED`, `skipped=true`,
`reason=not_exchange_session`으로 구분한다.

## 멱등성과 재실행

세 계층이 중복 실행을 막는다.

1. Timer starter는 `candidate-daily-YYYY-MM-DD` instance가 이미 있으면 새 instance를
   시작하지 않는다.
2. Candidate 제출은 `Idempotency-Key: orchestrator-daily-YYYY-MM-DD`를 사용한다.
   같은 key와 canonical payload는 기존 `process_run_id`를 반환하고 다른 payload는
   `409`로 거부한다.
3. Portal에는 후보별 요청을 반복하지 않고 하나의 `selection_run_id`를 한 번 제출한다.
   이후에는 반환된 `daily_analysis_id`의 집계만 조회한다.

운영자가 같은 날짜를 다시 처리해야 한다면 기존 Durable instance와 Candidate
idempotency record를 함께 고려한 명시적 재실행 절차가 필요하다. 모델 목적을 바꿔 같은
key를 재사용하는 방식은 payload 충돌이므로 허용하지 않는다.

## 외부 계약과 검증

| 대상 | 인증 | 요청·검증 |
|---|---|---|
| Candidate API | `X-API-Key` | session 조회, readiness, DAILY 접수, run polling, candidate 조회 |
| Azure Resource Manager | 관리 ID·`DefaultAzureCredential` | Candidate·Portal App Service가 `RUNNING`인지 확인 |
| Portal API | `Authorization: Bearer` | selection run 일괄 접수와 `daily_analysis_id` 집계 조회 |
| TradingAgents | 서비스 readiness endpoint | `/readyz`의 `status=ready` 확인 |
| ACS Email | 관리 ID·Email Sender RBAC | 시작과 terminal summary 전송 |

모든 외부 URL은 credential·query·fragment가 없는 HTTPS base URL이어야 한다. HTTP
redirect를 따르지 않고 JSON object만 허용하며 응답은 최대 2 MiB로 제한한다. Candidate
후보는 다음을 모두 만족해야 Portal로 전달된다.

- `price_session_date`가 대상일과 일치
- 설정된 `model_purpose`와 일치
- 5~10개이며 `selected_count`와 실제 개수가 일치
- position이 1부터 연속이고 ticker·instrument가 중복되지 않음
- 모든 row가 하나의 `selection_run_id`에 속함
- selection status가 `SUCCEEDED` 또는 명시적 `SHORTFALL`

운영 기본 모델은 `MEDIUM_20D`다. `SHORT_5D`는 명시적으로 설정하는 one-off 경로이며
자동 fallback이 아니다.

## Azure 배포 토폴로지

`infra/orchestrator.bicep`이 소유하는 리소스는 다음과 같다.

- Linux Flex Consumption FC1 Function App과 system-assigned managed identity
- Durable state와 배포 package용 Storage Account·Blob container
- Key Vault와 secret reference, Application Insights·Log Analytics
- Azure Communication Services, Email Service와 Azure Managed Domain
- exception·failed request metric alert와 기존 Action Group 연결
- Storage Blob/Queue/Table, Key Vault secrets, App Insights publisher, Email Sender RBAC

Candidate·Portal App Service, TradingAgents Container App, PostgreSQL, Portal MySQL과 기존
Action Group은 템플릿의 소유 범위 밖이다. Function 관리 ID에는 Candidate·Portal
App Service 범위의 `Reader`를 별도로 부여한다. secret 값은 Bicep에 넣지 않고 배포 후
Key Vault에 주입한다.

현재 Storage·Key Vault·Function의 public network access는 활성화돼 있다. private
endpoint가 필수인 환경은 FC1 VNet 통합, private DNS, 외부 API egress를 별도 설계해야
한다.

## 관측성과 실패 처리

- Application Insights와 Log Analytics가 Function request·exception telemetry를 받는다.
- exception count와 failed request count가 5분 창에서 0보다 크면 기존 Action Group으로
  alert를 보낸다.
- Candidate 기본 timeout은 120분, Portal 기본 timeout은 360분, poll 간격은 60초다.
- Email 실패는 업무 terminal state를 덮어쓰지 않으며 `sent=false`와 오류 타입만
  반환한다.
- 예외 메시지, secret, API 원문 payload를 terminal summary에 포함하지 않는다.

## 구현 매핑

| 구현 | 역할 |
|---|---|
| `orchestrator/function_app.py` | timer, Durable trigger, activity 등록 |
| `orchestrator/scheduler.py` | DST-aware 05:30 gate와 instance ID |
| `orchestrator/workflow.py` | replay-safe 순서, timer, 상태 전이 |
| `orchestrator/clients.py` | Candidate·Portal·ARM·ACS 외부 계약과 검증 |
| `orchestrator/settings.py` | 환경 설정과 HTTPS/resource ID fail-closed 검증 |
| `infra/orchestrator.bicep` | FC1, state, identity, secrets, telemetry, email, alerts |
| `tests/orchestrator/test_orchestrator.py` | 일정·계약·상태·보안 경계 회귀 검증 |

상위 시스템 경계는 [프로젝트 전체 아키텍처](architecture-diagram.md), 실제 실행·배포
방법은 [오케스트레이터 README](../../../../../orchestrator/README.md)를 따른다.