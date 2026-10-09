# 일 1회 후보 선정 수집 파이프라인

갱신일: 2026-10-09

## 목표와 범위

이 파이프라인은 미국 시장의 직전 완료 거래 세션을 기준으로 하루 한 번 데이터를 수집하고, 재현 가능한 input manifest를 생성한다. 수집 성공 자체가 후보 생성 성공을 의미하지 않으며, core dataset 품질 gate를 통과한 경우에만 특징·점수·후보 단계가 실행된다.

선택 공급자:

- Massive Stocks Basic: 가격, 분할, 배당, 뉴스
- SEC EDGAR: 기업 식별, 공시, XBRL 재무
- Alpha Vantage: 전체 종목 실적 일정
- NYSE/Nasdaq와 calendar library: 거래 세션, 조기 폐장, 거래정지
- Wikipedia revision: 공식 S&P 계약 전 prototype universe

## 일일 실행 시각

| 항목 | 설계 |
|---|---|
| scheduler | 매일 05:30 America/New_York |
| 처리 세션 | 직전 완료한 미국 거래 세션 |
| 거래일 | 전체 수집 후 core gate와 후보 단계 실행 |
| 주말·휴장일 | SEC·earnings·news·reference refresh, 새 market candidate run은 생성하지 않음 |
| 목표 완료 | grouped endpoint 사용 시 06:00 ET 이내, per-ticker fallback 시 약 07:30 ET |

05:30 ET를 선택한 근거:

1. Massive EOD 데이터가 전일 장 마감 이후 준비될 시간을 둔다.
2. SEC nightly bulk ZIP이 약 03:00 ET에 갱신된 이후다.
3. fallback 503 ticker 수집이 약 101분 걸려도 다음 정규장 09:30 ET 전에 완료 가능하다.
4. 한국 시간은 서머타임에 따라 변하므로 고정 KST가 아니라 ET schedule을 사용한다.

## 공급자 하네스

### Massive Stocks Basic

| 제약 | 설계 반영 |
|---|---|
| 분당 5회 | 모든 Massive collector가 하나의 token bucket 공유. burst 없이 12초당 1회 |
| 장 마감 가격 | 전일 완료 세션만 수집. 실시간 후보 선정에 사용하지 않음 |
| 가격 과거 2년 | target date가 실행일 기준 약 2년보다 오래되면 fail closed |
| 배당 과거 범위 제한 | snapshot coverage에 실제 반환 범위 기록 |
| 뉴스 과거 범위 제한 | 전향적 축적을 기본으로 하고 완전한 과거 뉴스라고 표시하지 않음 |

가격 수집 우선순위:

1. grouped daily endpoint 1회로 미국 전체 일봉을 받고 universe 503개를 내부 필터링한다.
2. Basic entitlement에서 grouped endpoint를 사용할 수 없는 경우 ticker별 endpoint로 fallback한다.
3. ticker별 503회는 `ceil(503 / 5) = 101분`이므로 병렬 HTTP로 제한을 우회하지 않는다.

Massive shared queue 순서:

1. 가격
2. 분할
3. 배당
4. 뉴스 metadata

각 endpoint의 pagination도 같은 5회/분 quota를 사용한다. `next_url`이 끝날 때까지 진행하되 실행별 page safety cap을 두고 초과 시 dataset을 실패 처리한다.

### SEC EDGAR

| 기능 | 수집 방법 |
|---|---|
| issuer/ticker/exchange | `company_tickers_exchange.json` 조건부 요청 |
| submissions | nightly `submissions.zip` 조건부 다운로드 |
| 표준 facts | nightly `companyfacts.zip` 조건부 다운로드 |
| 원본 filing/XBRL | allowlist form·accession에 대해 EDGAR archive 조회 |

운영 규칙:

- API key는 없고 실제 연락처가 포함된 User-Agent를 사용한다.
- 공식 한도 10 req/s보다 보수적인 5 req/s limiter를 사용한다.
- bulk ZIP 동시 다운로드는 최대 2개다.
- ETag/Last-Modified가 같으면 304를 기록하고 기존 snapshot을 재사용한다.
- Company Facts를 그대로 분석에 넣지 않는다.
- taxonomy concept, unit, instant/duration, period start/end, fiscal year/period, accession과 amendment를 정규화한다.
- 재무 정규화가 비활성화되면 fundamental dataset은 quality gate에서 실패한다.

### Alpha Vantage

| 제약 | 설계 반영 |
|---|---|
| 일반 무료 key 하루 25회 | 프로젝트 전체 Alpha 호출 예산을 하루 25회로 제한 |
| earnings 전체 목록 가능 | symbol 없이 earnings calendar 전체 목록을 하루 1회 요청 |
| revision history 부족 | 매일 원 응답 snapshot을 저장해 오늘 이후 revision을 자체 축적 |

정상 실행은 1회이며 timeout·5xx 재시도는 최대 2회로 제한한다. 최대 3회를 사용해도 22회의 일일 여유를 남긴다. ticker별 503회 호출은 하네스가 거부한다.

### 공식 거래소·참조 원천

- `exchange_calendars`로 baseline session을 생성한다.
- NYSE/Nasdaq 공식 holiday·early-close 문서로 보정한다.
- Nasdaq halt feed를 일 1회 snapshot으로 저장한다. 실시간 halt 대응이 필요해지면 별도 고빈도 서비스로 분리한다.
- Wikipedia revision은 prototype universe에만 사용한다.
- identifier는 현재 단계에서 SEC CIK·ticker·exchange를 사용하며 OpenFIGI는 제외한다.

## 일일 DAG

### Phase 0: preflight

1. Azure PostgreSQL과 raw storage 접근 확인
2. Massive·Alpha key 존재 확인
3. source policy harness 실행
4. 미국 거래 달력에서 처리할 session 결정
5. dataset checkpoint와 직전 성공 manifest 조회
6. 같은 세션의 진행 중 run이 있으면 advisory lock으로 중복 실행 방지

### Phase 1: 공급자별 병렬 lane

서로 quota가 다른 다음 lane을 동시에 시작한다.

| lane | 네트워크 실행 | 내부 병렬성 |
|---|---|---|
| Massive | shared 5 req/min queue에서 순차 | 응답 parsing만 병렬 |
| SEC | ticker JSON과 bulk ZIP 최대 2개 병렬 | ZIP entry·issuer partition 병렬 normalize |
| Alpha | 전체 earnings 목록 1회 | ticker 매핑 병렬 |
| Reference | calendar, universe, halt 독립 요청 | parser 병렬 |

### Phase 2: raw snapshot

- 응답을 dataset별 임시 파일에 쓴다.
- SHA-256을 계산한다.
- atomic rename한다.
- provider, dataset, coverage, source available time, fetched time, hash를 `source_snapshot`에 기록한다.
- 동일 coverage와 hash는 중복 저장하지 않는다.

### Phase 3: 병렬 정규화

| worker | 출력 |
|---|---|
| reference worker | issuer, instrument, ticker, exchange, universe |
| market worker | raw OHLCV, logical revisions, snapshot observations |
| action worker | split·dividend revisions |
| SEC worker | filing, normalized facts, context hash |
| event worker | earnings revisions, news metadata, halts |

### Phase 4: temporal·quality gate

공통:

- manifest에 포함된 snapshot만 사용
- 미래 session·published time·source available time 차단
- reconstruction과 operational replay 분리
- duplicate natural key와 schema 위반 차단

core blocking:

- 거래 세션 불확정
- universe 미확정
- 가격 completeness가 설정 임계치 미만
- corporate action 충돌로 조정계수 생성 불가
- future row 발견

optional degradation:

- SEC facts 지연
- earnings calendar 실패
- news 실패
- halt feed 실패

optional dataset 실패는 해당 signal을 비활성화하고 stale/failed 상태를 남긴다. 이전 snapshot을 최신인 것처럼 바꾸지 않는다.

### Phase 5: dataset transaction과 manifest

1. dataset별 transaction으로 성공 데이터를 보존한다.
2. checkpoint는 해당 dataset transaction commit 후에만 전진한다.
3. core dataset이 모두 통과하면 final input manifest를 만든다.
4. optional dataset은 성공 snapshot 또는 명시적 missing 상태로 manifest metadata에 기록한다.
5. core 실패 시 후보 단계는 실행하지 않지만 성공한 source snapshot은 보존한다.

### Phase 6: 후보 생성

아직 미구현이다.

1. raw/proccessed feature run
2. label·processor·model version 고정
3. universe-scoped scoring run
4. quantitative·event·history 정책으로 5~10개 후보
5. TradingAgents downstream 전달

## API 호출 예산

### 정상 거래일

| 공급자 | 정상 요청량 | 최악 경로 |
|---|---:|---:|
| Massive price | grouped 1회 | per-ticker 503회, 약 101분 |
| Massive splits | 1회 + pagination | 반환량에 따른 page 수 |
| Massive dividends | 1회 + pagination | 반환량에 따른 page 수 |
| Massive news | 1회 + pagination | 무료 범위와 page cap 적용 |
| SEC | ticker JSON 1 + bulk ZIP 2 | 변경 없으면 304 |
| Alpha Vantage | earnings 전체 목록 1회 | retry 포함 최대 3회 |
| calendar/universe/halt | 원천별 1회 수준 | 조건부 요청 사용 |

Massive의 네 endpoint를 동시에 호출하는 것처럼 보이더라도 실제 네트워크는 shared limiter가 순차화한다. SEC·Alpha·reference lane은 Massive 대기 시간 동안 병렬 진행한다.

## 데이터 목표 대비 상태

| 목표 | 현재 수집 | 재설계 후 | 완전 충족 여부 |
|---|---|---|---|
| 500기업·503증권 마스터 | Wikipedia/CIK 부분 | SEC ticker·exchange 보강 | 현재 시점 기준 가능 |
| 과거 S&P 구성·GICS | 없음 | 현재 선택 공급자로 불가 | S&P DJI 계약 필요 |
| 3~5년 가격 | 하루 1일 | Massive Basic 최대 2년 | 미충족, 플랜 업그레이드 필요 |
| 일일 증분 OHLCV | Yahoo prototype | Massive EOD 일 1회 | 가능 |
| 분할·배당 | 없음 | Massive | forward 가능, 과거 범위 제한 |
| 공시·재무 | 없음 | SEC JSON·bulk ZIP | 가능, 정규화 구현 필요 |
| earnings 일정 | 없음 | Alpha 전체 목록 일 1회 | forward 가능, 과거 revision 미충족 |
| 뉴스 | 없음 | Massive metadata | forward 가능, 과거 범위·권리 제한 |
| 거래 달력 | 없음 | 공식 일정 + library | 가능 |
| 거래정지 | 없음 | Nasdaq halt snapshot | 일 1회 기준 가능 |
| 특징·점수 | 없음 | 수집 후 Qlib | 미구현 |
| 후보 5~10개 | 없음 | scoring 후 selection | 미구현 |

## 실패·재시도·멱등성

- HTTP 429는 `Retry-After`를 따른다.
- Massive는 retry도 5회/분 quota에 포함한다.
- Alpha retry도 25회/일 예산에 포함한다.
- SEC는 403·429 발생 시 User-Agent와 요청률을 점검하고 backoff한다.
- raw payload hash가 같으면 새 raw object를 만들지 않는다.
- 논리 값이 같으면 새 revision을 만들지 않고 snapshot observation만 연결한다.
- 같은 dataset·session·config run은 하나만 활성화한다.
- 변경된 payload만 새 snapshot으로 추가한다.
- 품질 이슈는 run·dataset·entity·rule 기준으로 멱등하며 ACTIVE/RESOLVED 상태를 갱신한다.

## 로그와 운영 지표

`logs/<서울 실행일>.log`에 단계당 JSON 한 줄을 기록한다.

필수 필드:

- pipeline start time
- collection date
- pipeline name
- SUCCESS, PARTIAL_SUCCESS, FAILURE
- duration
- failure reason
- request count, response count, changed row count
- quota wait time
- source coverage

추가 지표:

- Massive queue depth와 throttle seconds
- SEC downloaded bytes와 normalization rejects
- Alpha requests used today
- dataset freshness
- context-visible rows와 logical rows

## 구현 우선순위

1. shared rate limiter와 dataset checkpoint
2. Massive grouped price collector
3. Massive split·dividend collector
4. SEC ticker·submissions·companyfacts bulk collector와 normalizer
5. Alpha global earnings collector
6. 공식 calendar·halt collector
7. Massive news collector
8. fundamental/event schema
9. Qlib feature·score·selection

## 현재 구현된 prototype

- Wikipedia cutoff revision collector
- Yahoo per-symbol daily bar collector
- application·PostgreSQL temporal fence
- raw gzip snapshot과 hash
- ops/ref/market MVP schema
- input manifest·execution context
- logical bar revision·snapshot observation
- 동일일 변경분 upsert
- 일자별 JSONL pipeline log

## 실제 production 구현 및 실행 결과

2026-10-08 세션을 대상으로 실제 provider key를 사용해 실행했다.

| dataset | 구현·적재 결과 |
|---|---:|
| Massive grouped daily | 503 bars |
| Massive corporate actions | 99 revisions |
| Massive news | 291 events |
| SEC company ticker reference | 503 universe instruments에 exchange state 연결 |
| Alpha Vantage earnings | 467 universe events |
| source snapshots | 7 |
| future bars | 0 |
| active production quality issues | 0 |

run identifiers:

- ingestion run: `8496d161-8f00-4ff5-ad3f-e1ae9cd92b20`
- latest input manifest: `5cefeecc-2651-5e15-a89e-3d68302ce217`
- latest execution context: `7f56908c-23bb-596c-926f-211d136207aa`

SEC `submissions.zip`·`companyfacts.zip` 다운로드 메서드는 구현됐지만 일일 orchestrator에는 아직 연결하지 않았다. 따라서 `fundamental.sec_filing`과 `fundamental.fact`는 현재 0행이다. 공식 calendar·halt collector와 Qlib·selection도 아직 미구현이다.

## 실행 명령

```powershell
# 키 값을 출력하지 않고 provider 연결만 확인
.\.venv\Scripts\python.exe -m sp500_candidate_engine `
  --env-file .env probe-providers --date 2026-10-08

# migration과 실제 production 수집·적재
.\.venv\Scripts\python.exe -m sp500_candidate_engine `
  --env-file .env collect-production --date 2026-10-08
```

실제 probe 결과:

- Massive grouped results: 12,592
- SEC listed-company reference: 10,435
- Alpha Vantage earnings rows: 4,573

로컬 실행은 Azure CLI 또는 관리 ID로 PostgreSQL Entra token을 얻어야 한다. credential이 만료되거나 CLI를 호출할 수 없으면 provider 수집 전에 database migration 단계에서 fail closed하며 기존 성공 run은 변경하지 않는다.
