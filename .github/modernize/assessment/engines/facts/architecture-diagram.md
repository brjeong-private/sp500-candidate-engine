# 프로젝트 전체 아키텍처

갱신일: 2026-10-12

이 문서는 개발과 함께 갱신하는 후보 선정 엔진과 운영 자동화의 기준 아키텍처다.
Candidate Engine의 책임은 후보 저장까지이며, 포털·TradingAgents의 분석·리포트는
외부 시스템의 책임이다. 실선은 구현된 애플리케이션 계약 또는 Bicep에 정의된
리소스 관계이고, 점선은 외부 시스템 내부의 논리 관계다.

## 설계 전제

- 스케줄러는 매일 한 번 `05:30 America/New_York`에 실행한다.
- 거래일에는 직전 완료 세션을 처리하고, 비거래일에는 reference·event refresh만 수행한다.
- 시장 데이터는 Massive Stocks Basic을 사용한다.
- Massive 호출은 전체 collector가 공유하는 단일 limiter에서 분당 5회로 제한한다.
- SEC EDGAR와 Alpha Vantage는 Massive와 quota가 독립이므로 병렬 실행한다.
- Alpha Vantage earnings calendar는 ticker별 호출이 아니라 전체 목록을 하루 1회 받는다.
- SEC는 JSON API와 nightly bulk ZIP을 사용하고, 재무 fact는 정규화 후에만 분석 입력으로 사용한다.
- 현재 Wikipedia·Yahoo 경로는 prototype 이력 재현용으로만 남기며 신규 운영 경로에서는 Massive·SEC·Alpha Vantage를 사용한다.
- Candidate API의 기본 모델 목적은 `MEDIUM_20D`이고 `SHORT_5D`는 명시적 one-off
  실행·조회에만 사용한다. 모델 간 자동 fallback은 없다.
- 운영 스케줄은 Python Durable Functions가 담당한다. Candidate Engine은 포털이나
  TradingAgents의 분석 결과를 저장하지 않는다.

## 전체 Azure 운영 아키텍처

<!-- mermaid-checked: no braces in labels, all subgraphs closed, unique ids -->
```mermaid
flowchart TB
    subgraph DataSources["Market and Reference Sources"]
        MassiveAzure["Massive"]
        SecAzure["SEC EDGAR"]
        AlphaAzure["Alpha Vantage"]
        CalendarAzure["XNYS Calendar"]
    end

    subgraph CandidatePlane["Candidate Plane"]
        CandidateApp["Candidate API<br/>Python App Service"]
        CandidateEngine["Collection to Candidate Selection"]
        CandidateDb[("PostgreSQL Flexible Server<br/>candidate source of truth")]
    end

    subgraph OrchestrationPlane["Orchestration Plane defined by infra orchestrator bicep"]
        FunctionApp["Python Durable Functions<br/>Linux Flex Consumption FC1"]
        DurableState["Storage Account<br/>Durable state and code package"]
        Vault["Key Vault<br/>API keys and email settings"]
        Insights["Application Insights<br/>Log Analytics and alerts"]
        Email["Azure Communication Services Email"]
    end

    subgraph ExternalPlane["External Analysis Plane"]
        PortalApi["Portal Service API<br/>App Service"]
        PortalDb[("MySQL Flexible Server<br/>analysis jobs and results")]
        TradingApp["TradingAgents<br/>Azure Container App"]
        FoundryModel["Microsoft Foundry<br/>model deployments"]
        ReportBlob["Blob Storage<br/>analysis reports"]
    end

    MassiveAzure --> CandidateEngine
    SecAzure --> CandidateEngine
    AlphaAzure --> CandidateEngine
    CalendarAzure --> CandidateEngine
    CandidateApp --> CandidateEngine
    CandidateEngine --> CandidateDb

    DurableState --> FunctionApp
    Vault --> FunctionApp
    FunctionApp --> Insights
    FunctionApp -->|"start and terminal notification"| Email
    FunctionApp -->|"idempotent DAILY request"| CandidateApp
    CandidateApp -->|"candidate and run status"| FunctionApp
    FunctionApp -->|"selection run batch"| PortalApi
    PortalApi -->|"aggregate status"| FunctionApp

    PortalApi -->|"persist external analysis state"| PortalDb
    PortalApi -.->|"dispatch analysis"| TradingApp
    TradingApp -.->|"inference"| FoundryModel
    TradingApp -.->|"write report"| ReportBlob
```

### 05:30 ET 실행 계약

1. Functions timer는 UTC 매시 30분 실행되지만 뉴욕 현지 시각이 정확히 05:30일
   때만 `candidate-daily-YYYY-MM-DD` Durable instance를 시작한다. DST는
   `America/New_York` 변환으로 처리한다.
2. 대상은 직전 달력 날짜이며 Candidate의 XNYS session API에서 거래일을 확인한다.
   비거래일은 외부 실행 없이 `SUCCEEDED`와 `skipped=true`로 끝난다.
3. Candidate·Portal App Service의 ARM 상태와 Candidate `/health/ready`, Portal 및
   TradingAgents `/readyz`를 확인한다.
4. Candidate 실행은 날짜 기반 `Idempotency-Key`로 한 번 접수하고 durable timer로
   polling한다. 완료 후보가 같은 date·selection run·model purpose에 속하는지와
   5~10개·순위·식별자 중복을 검증한다.
5. Portal service API에는 후보 row를 복제하지 않고 `analysis_date`,
   `selection_run_id`, `model_purpose`를 일괄 제출한다. Portal이 MySQL에 외부 분석
   job·결과를 저장하고 TradingAgents Container App 실행을 중개한다.
6. 외부 I/O와 ACS Email은 activity에서만 실행한다. 종결 상태는 `SUCCEEDED`,
   `PARTIAL_FAILED`, `TIMED_OUT`, `FAILED`다.

### Candidate API 멱등성

`POST /api/v1/pipeline-runs`는 `X-API-Key`와 `Idempotency-Key`를 요구한다. API는
null을 제외하고 key를 정렬한 canonical JSON의 SHA-256을 PostgreSQL에 저장한다.
같은 key와 같은 hash는 원래 `process_run_id`를 반환해 gateway 또는 activity replay가
중복 수집·후보 생성을 만들지 않는다. 같은 key를 다른 payload에 재사용하면 `409`다.
이 계약은 API 접수 멱등성이고 Durable instance ID의 날짜별 중복 방지와 별개로 함께
적용된다.

### FC1 Bicep 경계

`infra/orchestrator.bicep`은 Linux FC1 Function App, 관리 ID 기반 Durable Storage,
배포 Blob container, Key Vault, Application Insights·Log Analytics, ACS Email,
예외·실패 alert를 만든다. API key와 email 주소 값은 만들지 않고 배포 후 Key Vault
secret으로 주입한다. 기존 Candidate·Portal App Service에는 Reader 역할을 별도로
부여하며, Portal·TradingAgents·PostgreSQL·MySQL 자체는 이 Bicep의 소유 범위가 아니다.

## 전체 애플리케이션 흐름

<!-- mermaid-checked: no \n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
```mermaid
flowchart TD
    subgraph Trigger["Daily Trigger"]
        Scheduler["05:30 ET Daily Scheduler"]
        SessionResolver["Resolve Last Completed US Session"]
        Preflight["Config Key Quota and Checkpoint Preflight"]
    end

    subgraph Sources["Selected Data Sources"]
        Massive["Massive Stocks Basic"]
        Sec["SEC EDGAR JSON and Bulk ZIP"]
        Alpha["Alpha Vantage Earnings Calendar"]
        Wiki["Wikipedia Revision Prototype Universe"]
        Exchanges["NYSE Nasdaq Calendar and Halts"]
    end

    subgraph Collect["Collection Lanes"]
        MassiveQueue["Massive Shared Queue 5 Requests Per Minute"]
        MassivePrice["Grouped Daily Price"]
        MassiveActions["Dividends and Splits"]
        MassiveNews["News Metadata"]
        SecBulk["SEC Bulk Downloads"]
        SecReference["SEC Ticker and Filing Reference"]
        AlphaCalendar["One Global Earnings Request"]
        ReferenceLane["Universe Calendar and Halt Refresh"]
    end

    subgraph Raw["Raw and Provenance"]
        RawWriter["Parallel Raw Snapshot Writers"]
        SnapshotCatalog["Source Snapshot and Content Hash"]
        Checkpoint["Dataset Checkpoints"]
    end

    subgraph Normalize["Normalize and Validate"]
        IdentityMap["Issuer Instrument and Ticker Mapping"]
        MarketNormalize["Price and Corporate Action Normalize"]
        SecNormalize["SEC Concept Period and Unit Normalize"]
        EventNormalize["Earnings News and Halt Normalize"]
        TemporalFence["Point In Time Fence"]
        QualityGate["Dataset Quality Gates"]
    end

    subgraph Storage["Azure PostgreSQL 16"]
        Ops[("ops")]
        Ref[("ref")]
        Market[("market")]
        Fundamental[("fundamental")]
        Event[("event")]
        Analytics[("analytics")]
        Selection[("selection")]
    end

    subgraph Candidate["Candidate Engine"]
        FeatureRun["Feature and Label Runs"]
        ScoreRun["Model Scoring and Universe Ranking"]
        Selector["Daily Five to Ten Candidates"]
    end

    Scheduler -->|"daily"| SessionResolver
    SessionResolver -->|"session date"| Preflight
    Preflight -->|"parallel lane"| MassiveQueue
    Preflight -->|"parallel lane"| SecBulk
    Preflight -->|"parallel lane"| SecReference
    Preflight -->|"parallel lane"| AlphaCalendar
    Preflight -->|"parallel lane"| ReferenceLane

    Massive -->|"shared quota"| MassiveQueue
    MassiveQueue -->|"priority one"| MassivePrice
    MassiveQueue -->|"priority two"| MassiveActions
    MassiveQueue -->|"priority three"| MassiveNews
    Sec -->|"conditional bulk"| SecBulk
    Sec -->|"reference JSON"| SecReference
    Alpha -->|"one request"| AlphaCalendar
    Wiki -->|"prototype only"| ReferenceLane
    Exchanges -->|"official metadata"| ReferenceLane

    MassivePrice --> RawWriter
    MassiveActions --> RawWriter
    MassiveNews --> RawWriter
    SecBulk --> RawWriter
    SecReference --> RawWriter
    AlphaCalendar --> RawWriter
    ReferenceLane --> RawWriter
    RawWriter --> SnapshotCatalog
    SnapshotCatalog --> Checkpoint

    SnapshotCatalog --> IdentityMap
    SnapshotCatalog --> MarketNormalize
    SnapshotCatalog --> SecNormalize
    SnapshotCatalog --> EventNormalize
    IdentityMap --> TemporalFence
    MarketNormalize --> TemporalFence
    SecNormalize --> TemporalFence
    EventNormalize --> TemporalFence
    TemporalFence --> QualityGate

    QualityGate --> Ops
    QualityGate --> Ref
    QualityGate --> Market
    QualityGate --> Fundamental
    QualityGate --> Event

    Ref --> FeatureRun
    Market --> FeatureRun
    Fundamental --> FeatureRun
    Event --> Selector
    FeatureRun --> Analytics
    Analytics --> ScoreRun
    ScoreRun --> Selection
    Selection --> Selector
```

## 파이프라인 실행 아키텍처

<!-- mermaid-checked: no \n, no em-dash/en-dash, no {} in labels, subgraphs are id["label"], arrows are -->|"label"|, all subgraphs closed by end, ids unique -->
```mermaid
flowchart LR
    subgraph Phase0["Phase 0 Preflight"]
        P0A["Resolve Session"]
        P0B["Validate Keys and Source Policies"]
        P0C["Load Checkpoints"]
    end

    subgraph Phase1["Phase 1 Parallel Network Lanes"]
        MQueue["Massive Token Bucket"]
        M1["Grouped Price One Request"]
        M2["Dividend Pages"]
        M3["Split Pages"]
        M4["News Pages"]
        S1["SEC Ticker JSON"]
        S2["SEC Submissions ZIP"]
        S3["SEC Company Facts ZIP"]
        A1["Alpha Earnings All Symbols"]
        R1["Calendar Universe and Halts"]
    end

    subgraph Phase2["Phase 2 Parallel Local Work"]
        RawWrite["Atomic Raw Writes"]
        ParseMarket["Parse Market"]
        ParseSec["Parse and Normalize SEC"]
        ParseEvents["Parse Events"]
        ParseReference["Parse Reference"]
    end

    subgraph Phase3["Phase 3 Gates"]
        TimeGate["Cutoff and Manifest Gate"]
        DataGate["Completeness and Schema Gate"]
        CoreDecision["Core Dataset Ready"]
    end

    subgraph Phase4["Phase 4 Persistence"]
        DatasetTx["Dataset Transactions"]
        Manifest["Final Input Manifest"]
        Log["One Line Stage Logs"]
    end

    subgraph Phase5["Phase 5 Candidate Run"]
        Features["Features"]
        Scores["Scores"]
        Candidates["Candidates"]
    end

    P0A --> P0B
    P0B --> P0C
    P0C --> MQueue
    P0C --> S1
    P0C --> S2
    P0C --> S3
    P0C --> A1
    P0C --> R1

    MQueue --> M1
    M1 --> M2
    M2 --> M3
    M3 --> M4

    M1 --> RawWrite
    M2 --> RawWrite
    M3 --> RawWrite
    M4 --> RawWrite
    S1 --> RawWrite
    S2 --> RawWrite
    S3 --> RawWrite
    A1 --> RawWrite
    R1 --> RawWrite

    RawWrite --> ParseMarket
    RawWrite --> ParseSec
    RawWrite --> ParseEvents
    RawWrite --> ParseReference
    ParseMarket --> TimeGate
    ParseSec --> TimeGate
    ParseEvents --> TimeGate
    ParseReference --> TimeGate
    TimeGate --> DataGate
    DataGate --> DatasetTx
    DatasetTx --> CoreDecision
    CoreDecision --> Manifest
    Manifest --> Features
    Features --> Scores
    Scores --> Candidates

    P0B --> Log
    M4 --> Log
    S3 --> Log
    A1 --> Log
    R1 --> Log
    DataGate --> Log
    DatasetTx --> Log
    Manifest --> Log
```

## 병렬화 원칙

| 영역 | 실행 방식 | 근거 |
|---|---|---|
| Massive 네트워크 | 단일 shared queue, 12초당 최대 1회 | Stocks Basic 분당 5회 제한을 collector 전체에서 지키기 위함 |
| Massive 응답 parsing | dataset별 병렬 | 네트워크 quota와 무관한 CPU·I/O 작업 |
| SEC bulk 3종 | 최대 2개 동시 다운로드 | SEC 10 req/s보다 보수적이며 대용량 ZIP 동시 부하 제한 |
| Alpha Vantage | SEC·Massive와 병렬, 하루 1회 | 독립 quota이며 전체 earnings 목록 한 번으로 충분 |
| 공식 calendar·halt·universe | 다른 공급자와 병렬 | 독립 원천이며 candidate core 이전에만 완료하면 됨 |
| raw snapshot 쓰기 | dataset별 병렬 atomic write | 서로 다른 파일이고 content hash로 멱등 |
| normalize·quality | dataset별 병렬 | schema별 독립 처리 후 final manifest에서 결합 |
| PostgreSQL | dataset별 transaction 후 manifest 직렬 확정 | 부분 성공을 보존하되 불완전 core로 후보 생성을 막기 위함 |

## 데이터 완전성 상태

| 목표 데이터 | 현재 | 재설계 경로 | 남는 한계 |
|---|---|---|---|
| 현재 S&P 500 종목군 | Wikipedia 503 securities | Wikipedia revision + SEC identity 보강 | 공식 S&P 구성·weight 아님 |
| 과거 구성·GICS | 없음 | S&P DJI 계약 필요 | 현재 선택 공급자로 수집 불가 |
| 일봉 OHLCV | Yahoo 2026-10-01만 | Massive grouped daily | Basic은 장 마감·과거 2년 |
| 3~5년 가격 | 없음 | Massive 상위 플랜 또는 별도 backfill | Basic으로 목표 미충족 |
| 분할·배당 | 없음 | Massive corporate actions | 무료 플랜 과거 범위 제한 |
| CIK·공시·재무 | CIK 일부 | SEC JSON + bulk ZIP | concept·기간·단위 정규화 필요 |
| 실적 일정 | 없음 | Alpha Vantage 전체 목록 하루 1회 | 과거 revision history 없음 |
| 뉴스 metadata | 없음 | Massive News | 무료 플랜 과거 범위와 콘텐츠 권리 제한 |
| 거래 달력·조기 폐장 | 없음 | 공식 일정 + exchange calendar baseline | 비정상 휴장 archive 필요 |
| 거래정지 | 없음 | Nasdaq halt feed | 별도 collector 필요 |
| 특징·점수·후보 | 구현 | Qlib Alpha158·LightGBM·selection | 현재 모델은 SHADOW, 승격 기준 미통과 |

## 기술 구성

| 계층 | 선택 기술 |
|---|---|
| 스케줄·CLI | Python 3.13, 일 1회 |
| 비동기 HTTP | HTTPX |
| Massive 제한 | shared token bucket, 5 req/min |
| SEC 제한 | global limiter 5 req/s, 최대 동시 2 bulk downloads |
| Alpha 제한 | 1 global earnings request/day, 최대 25/day guard |
| 구조화 저장 | Azure PostgreSQL Flexible Server 16 |
| DB 인증 | Microsoft Entra, passwordless |
| 원문 저장 | MVP local gzip, 운영 Azure Blob planned |
| 시점 통제 | source snapshot, input manifest, execution context |
| 로깅 | `logs/YYYY-MM-DD.log` JSONL |

## 구현 상태

현재 구현·실행 완료:

- Massive grouped daily price, dividend, split, news collector
- Massive shared 5회/분 limiter와 pagination
- SEC company ticker·exchange reference collector
- SEC submissions/companyfacts bulk ZIP downloader·normalizer·filing/fact persistence
- Alpha Vantage 전체 earnings calendar collector
- event·corporate-action·instrument-state production schema와 persistence
- raw snapshot 7종, final manifest와 operational execution context
- Yahoo/Wikipedia prototype, temporal fence, 변경분 upsert와 JSONL 로그
- XNYS backfill, range action/news, SEC fact cutoff, 자동·수동 재처리와 process 진행 로그

아직 미구현 또는 운영 검증 대기:

- 공식 calendar·halt collector
- dataset checkpoint 실제 전진 로직
- staging COPY·set-based merge 최적화
- 양의 Rank IC를 충족하는 champion 승격

후보 저장이 이 저장소의 마지막 단계다. 후보 이후 분석, agent 실행, report, 비용과 재평가는 별도 프로젝트에서 관리한다.
