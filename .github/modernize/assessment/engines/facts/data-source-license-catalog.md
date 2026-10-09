# 데이터 수집 원천 및 라이선스 카탈로그

확인 기준일: 2026-10-09

이 문서는 현재까지 확인한 공식 페이지와 공급자 문서를 기준으로 초기 설계 데이터의 수집 원천, 가입 절차, API 인증, 저장·재배포 범위를 정리한다. 계약 상품의 실제 필드, 과거 이력 시작일, 비표시 이용, 파생 데이터 저장과 재배포 권리는 계약에 따라 달라질 수 있으므로 구매 전에 공급자에게 서면 확인해야 한다. 이 문서는 법률 자문이 아니다.

## 권장 조합

### 빠른 MVP 및 오늘부터의 전향적 축적

| 데이터 | 권장 원천 | 가입/API 키 |
|---|---|---|
| 현재 종목군 prototype | Wikipedia revision API | 불필요, 연락처 포함 User-Agent |
| 기업·CIK·공시·표준 XBRL | SEC EDGAR | 불필요, 연락처 포함 User-Agent |
| 상장 심볼·거래소 보조 검증 | Nasdaq Symbol Directory | 불필요 |
| 일봉·분할·배당 | Massive Stocks 유료 플랜 | 계정/API 키 및 이용권 확인 |
| 전향적 실적 일정 | Alpha Vantage | 무료 또는 유료 API 키 |
| 거래 달력 | NYSE/Nasdaq 공식 일정 + `exchange_calendars` | 불필요 |
| 거래정지 | Nasdaq Trade Halt RSS | 불필요 |
| 뉴스 metadata | Massive News 또는 별도 뉴스 계약 | API 키 및 뉴스 권리 확인 |

이 조합은 오늘부터 snapshot을 축적하는 데 적합하지만 역사적 S&P 구성·GICS와 과거 실적 일정 revision을 완전히 복원하지 못한다.

### 생존편향을 통제하는 연구용 조합

| 데이터 | 권장 원천 | 가입/API 키 |
|---|---|---|
| S&P 500 과거 구성·효력일·GICS 이력 | S&P DJI 직접 라이선스 | 영업 문의·계약 |
| 조정 전 OHLCV·분할·배당·상장폐지 | SIP 라이선스 벤더 또는 NYSE Daily TAQ | 유료 계약 |
| SEC 공시·원본 XBRL | SEC EDGAR | 키 불필요 |
| 증권 식별자 | SEC ticker·submissions + Nasdaq Symbol Directory | 키 불필요 |
| 실적 일정 및 revision history | Wall Street Horizon | 영업 문의·계약 |
| 뉴스 metadata 및 과거 이력 | Massive 또는 별도 뉴스 공급자 | 유료 계약 |
| 공식 휴장·조기 폐장·거래정지 | NYSE/Nasdaq 공식 자료 | 대부분 키 불필요 |

공급자 수를 줄이려면 S&P DJI + Massive + SEC + Alpha Vantage + 공식 거래소 일정으로 시작하고, Massive의 TMX corporate-events entitlement가 필요한 일정 revision을 충족하는지 영업팀에 확인한다. 충족하지 못하면 Wall Street Horizon을 추가한다.

## 현재 프로젝트에서 실제 사용 중인 원천

| 원천 | 사이트 | 실제 수집 데이터 | 라이선스·사용 범위 | 판정 |
|---|---|---|---|---|
| Wikipedia Revision API | [API](https://en.wikipedia.org/w/api.php), [S&P 500 page](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies) | cutoff 이전 revision, ticker, 회사명, sector, sub-industry, CIK | Wikipedia 콘텐츠는 CC BY-SA 조건과 attribution/share-alike 적용 가능성이 있으므로 원문 재배포 시 준수. S&P 공식 데이터가 아님 | prototype 전용 |
| Yahoo Chart API | `https://query1.finance.yahoo.com/v8/finance/chart/{symbol}` | 2026-10-01 OHLCV와 adjusted close | 공식 지원·SLA가 확인된 상용 데이터 API가 아니며 Yahoo 이용조건과 제3자 시장 데이터 권리가 적용될 수 있음. 생산·상업·연구 재배포 원천으로 사용하지 말고 라이선스 벤더로 교체 | prototype 전용 |
| Massive Stocks Basic | [Docs](https://massive.com/docs), [Pricing](https://massive.com/pricing) | 2026-10-08 grouped daily 503, actions 99, news 291 | 내부 저장·파생 특징·비표시 분석 권리는 계약 확인 필요. 5회/분, EOD, 가격 2년, actions/news 무료 범위 제한 | production 수집 시작 |
| SEC EDGAR | [APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | company ticker/exchange 10,435개 응답, universe state 503개 연결 | 무료 JSON·bulk, 연락처 User-Agent. filings/facts는 아직 미적재 | reference 구현 |
| Alpha Vantage | [Documentation](https://www.alphavantage.co/documentation/#earnings-calendar) | 전체 earnings 4,573개 응답 중 universe 467 events | 무료 key 25회/일, 전체 목록 하루 1회. 과거 revision history 없음 | production 수집 시작 |

## 상세 원천 카탈로그

### 1. S&P 500 구성과 GICS

#### S&P Dow Jones Indices

- 사이트:
  - [S&P 500 index page](https://www.spglobal.com/spdji/en/indices/equity/sp-500/)
  - [Index announcements](https://www.spglobal.com/spdji/en/index-announcements/)
  - [S&P U.S. Indices Methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf)
  - [GICS resources](https://www.msci.com/indexes/index-resources/gics)
- 수집 대상:
  - 구성 증권과 기업 식별자
  - 편입·편출 발표 시각과 효력일
  - 과거 constituent snapshot
  - index weight 또는 shares, 계약 상품에 포함되는 경우
  - sector, industry group, industry, sub-industry 및 변경 이력
- 가입:
  - S&P Global 또는 S&P DJI 영업 문의
  - 필요한 지수, 역사 깊이, 전달 방식 API/SFTP/file, 사용자 수를 명시해 견적 요청
- API 키:
  - 공개 무료 키 방식으로 확인되지 않음
  - 계약 후 제공되는 전달 채널과 자격증명 사용
- 라이선스 범위:
  - 구성 데이터와 회사별 GICS는 proprietary data
  - 내부 분석, 비표시 이용, 파생 데이터·모델 특징 저장, 보고서 표시, 재배포 권리를 계약서에 명시해야 함
  - 공개 methodology와 announcement만으로 완전한 point-in-time history를 구성할 수 없음
- 적합성:
  - 전향적 MVP: 선택 사항
  - 생존편향 통제 연구: 사실상 필수

영업 문의 시 요청할 문구:

```text
S&P 500 point-in-time constituent history, announcement and effective timestamps,
historical company-level GICS, internal non-display analytics, derived feature/model
storage, backtesting, and retention rights.
```

대안으로 S&P Capital IQ, CRSP/Compustat, FactSet, LSEG, Bloomberg에 같은 범위를 문의할 수 있지만, 실제 상품·역사 깊이·지수/GICS 재배포 권리는 계약 확인이 필요하다.

### 2. 기업·CIK·공시·재무

#### SEC EDGAR

- 사이트:
  - [EDGAR API documentation](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
  - [Developer resources](https://www.sec.gov/about/developer-resources)
  - [Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets)
  - [EDGAR calendar](https://www.sec.gov/submit-filings/filer-support-resources/edgar-calendar)
- API:
  - `company_tickers_exchange.json`
  - `data.sec.gov/submissions/CIK##########.json`
  - Company Facts
  - Frames
  - EDGAR archives 및 filing documents
- 수집 대상:
  - CIK, 회사명, ticker, exchange, SIC, fiscal year end
  - accession, form, filing/report/acceptance dates
  - 10-K, 10-Q, 8-K, amendments 및 원본 XBRL
  - 표준 taxonomy facts와 filing provenance
- 가입/API 키:
  - 계정·키 불필요
  - 조직/연락처가 포함된 User-Agent 필수
- rate limit:
  - SEC fair-access 지침상 최대 10 requests/second
  - bulk ZIP을 우선 사용하고 조건부 요청·backoff 적용
- 라이선스 범위:
  - SEC 공공 데이터는 내부 저장·분석에 적합
  - filing에 포함된 issuer 문서·전시물·이미지 등 제3자 콘텐츠의 저작권까지 자동으로 자유 재배포되는 것은 아님
  - 원문 전체를 외부 서비스에 재배포하기 전 별도 권리 검토
- 적합성:
  - MVP와 연구 모두 필수
  - Company Facts/Frames만으로 custom tag와 상세 context를 완전히 복원하지 말고 필요 시 원본 XBRL 파싱

필요한 사용자 작업은 없지만 `.env`의 `HTTP_USER_AGENT`에 실제 연락 가능한 이메일을 유지해야 한다.

### 3. 상장 심볼과 증권 식별자

#### Nasdaq Symbol Directory

- 사이트:
  - [Symbol Directory](https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs)
  - `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt`
  - `https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt`
- 데이터:
  - 현재 symbol, security name, listing exchange, market category, ETF/test flag, round lot
- 가입/API 키:
  - 불필요
- 라이선스·제약:
  - 현재 snapshot 보조 검증용
  - 완전한 과거 ticker·상장 상태 이력으로 사용하지 않음
  - 자동화·보존·재배포는 Nasdaq 사이트 및 데이터 이용조건 확인

#### OpenFIGI, 현재 단계 제외

- 사이트:
  - [API documentation](https://www.openfigi.com/api/documentation)
  - [OpenFIGI](https://www.openfigi.com/)
- 데이터:
  - FIGI, composite FIGI, share-class FIGI
  - ticker, exchange code, security type, name
- 가입/API 키:
  - 계정 생성 후 API 키 발급 권장
  - 키 없이도 제한적으로 사용할 수 있으나 batch와 rate limit이 더 작음
- 확인된 rate-limit 방향:
  - 무키 사용은 낮은 요청·batch 제한
  - 키 사용은 더 높은 요청 빈도와 batch 지원
  - 정확한 현재 수치는 API documentation 응답 헤더와 계정 플랜에서 재확인
- 라이선스·제약:
  - OpenFIGI API와 데이터 이용은 OpenFIGI terms 적용
  - 내부 식별자 매핑 용도로 사용하고 대량 재배포·원본 database 제공은 계약 확인
  - CUSIP는 별도 proprietary identifier이므로 라이선스 없이 영구 저장·재배포하지 않음
현재 프로젝트 provider selector와 `.env`에서는 제외했다. 향후 FIGI가 실제 조인 요구사항이 될 때 별도 승인 후 도입한다.

### 4. 일봉 OHLCV와 corporate actions

#### Massive

- 사이트:
  - [Pricing](https://massive.com/pricing)
  - [Stock aggregates](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
  - [Dividends](https://massive.com/docs/rest/stocks/corporate-actions/dividends)
  - [Splits](https://massive.com/docs/rest/stocks/corporate-actions/splits)
  - [Market-data terms](https://massive.com/legal/market-data-terms-of-service)
- 데이터:
  - 일봉 OHLCV, VWAP, transaction count
  - dividend declaration/ex/record/pay dates, amount, currency
  - split execution date와 비율
  - plan에 따라 과거 이력과 최신성 범위가 다름
- 가입/API 키:
  - Massive 계정 생성
  - Stocks 플랜 선택 후 API key 발급
  - 상업·팀·자동화 이용이면 개인 플랜이 충분한지 영업팀에 확인
- rate limit:
  - 무료/미구독 자산은 낮은 제한이 적용될 수 있음
  - 유료 플랜의 실제 throughput과 concurrency는 현재 pricing·계정 limits 확인
- 라이선스 범위:
  - 시장 데이터는 Nasdaq/UTP·NYSE 등 원천 계약과 Massive terms 적용
  - 구독만으로 재배포, 외부 display, 비표시 상업 이용, derived-data 재판매 권리가 자동 부여된다고 가정하지 않음
  - 다음 권리를 서면 확인:
    - 내부 비표시 분석
    - PostgreSQL 장기 보존
    - 조정계수와 Alpha158 등 파생 특징 저장
    - 모델 학습·백테스트
    - 내부 리포트 표시
    - 원천 데이터 외부 재배포 금지 범위
- 환경변수:
  - `MASSIVE_API_KEY`
- 적합성:
  - 빠른 MVP의 Yahoo 교체 대상으로 권장
  - 연구용으로는 delisted securities, corrections, historical depth와 이용권을 계약 확인

이 프로젝트가 선택한 **Massive Stocks Basic** 하네스 값:

- 분당 5회
- 가격은 장 마감 데이터
- 가격 과거 2년
- 배당·뉴스도 무료 플랜의 과거 범위 제한 적용

공급자 정책 변경 가능성이 있으므로 pricing/계정 화면과 계약서를 정기적으로 다시 확인한다.

#### NYSE Daily TAQ

- 사이트: [NYSE Daily TAQ](https://www.nyse.com/data-products/catalog/daily-taq)
- 데이터:
  - 미국 거래소의 trades, quotes, NBBO, master 및 administrative messages
  - 장기간 consolidated-tape 원시 데이터
- 가입:
  - NYSE data services 영업 계약
- API 키:
  - 일반적인 무료 REST API key가 아니라 계약된 전달 채널 사용
- 라이선스 범위:
  - display, non-display, derived data, 저장, 사용자·서버 수, 재배포 권리 계약 필요
- 적합성:
  - 가장 강한 검증 원천 또는 자체 일봉 산출용
  - 원시 TAQ에서 sale-condition과 regular-session 규칙으로 일봉을 직접 만들어야 하므로 초기 개발량과 비용이 큼

### 5. 실적 일정과 corporate events

#### Wall Street Horizon

- 사이트:
  - [Earnings calendar](https://www.wallstreethorizon.com/earnings-calendar)
  - [Field reference example](https://www.wallstreethorizon.com/upload/WSHEclassesandfieldsforIBAPI2022-12-23.pdf)
- 데이터:
  - confirmed/forecast earnings dates
  - pre-market, during-market, post-market timing
  - date revisions와 source document
  - conference call 및 기타 corporate events, 계약 상품에 따라 다름
- 가입/API 키:
  - 영업 문의와 상용 계약
  - 전달 방식과 credentials는 계약에 따름
- 라이선스 범위:
  - 역사적 revision archive, 내부 DB 보존, backtesting, derived event signal, 사용자 수를 서면 확인
  - 외부 고객·리포트로 원천 일정 데이터를 재배포할 권리는 별도 확인
- 적합성:
  - 과거 시점 재현과 일정 revision 연구에 권장

#### Alpha Vantage Earnings Calendar

- 사이트:
  - [Home/API key](https://www.alphavantage.co/)
  - [API documentation](https://www.alphavantage.co/documentation/#earnings-calendar)
- 데이터:
  - 향후 3·6·12개월 earnings calendar
  - symbol, name, report date, fiscal date ending, EPS estimate, currency, time of day
- 가입/API 키:
  - 이메일로 무료 API key 발급 또는 premium 가입
- rate limit:
  - 이 프로젝트의 일반 무료 키 하네스는 하루 25회로 고정
- 라이선스·제약:
  - revision history와 confirmation 상태 모델이 연구용으로 충분하다고 가정하지 않음
  - 매일 snapshot을 자체 저장하면 오늘 이후의 revision은 축적 가능
  - 장기 저장·상업 이용·재배포는 Alpha Vantage terms와 플랜 확인
- 환경변수:
  - `ALPHA_VANTAGE_API_KEY`
- 적합성:
  - 저비용 전향적 MVP
  - 역사적 revision 연구에는 부적합
  - 실적 일정은 symbol을 지정하지 않고 전체 목록 1회 조회 후 내부 ticker와 매핑

#### Massive TMX Corporate Events

- 사이트: [TMX corporate-events partner page](https://massive.com/partners/tmx)
- 데이터:
  - TMX Global Corporate Events Calendar 기반 events
- 가입:
  - Massive 또는 TMX entitlement 문의
- 라이선스·제약:
  - 기본 Stocks subscription에 포함되는지, 별도 addon인지, revision history와 과거 snapshot이 제공되는지 영업 확인
- 적합성:
  - 공급자 수를 줄일 후보
  - Wall Street Horizon을 대체할 수 있는지는 계약 필드 확인 전 미확정

### 6. 뉴스와 중요 이벤트

#### SEC 및 issuer IR

- SEC 8-K, 6-K, 10-Q, 10-K와 amendments를 material-event 기본 원천으로 사용
- issuer investor-relations 사이트는 자발적 발표의 1차 원천이지만 형식·robots·history가 제각각
- press-release 본문은 issuer 또는 배포사의 저작권이 적용될 수 있으므로 기본 저장은 title, URL, published time, hash와 필요한 metadata로 제한

#### Massive News

- 사이트:
  - [News API](https://massive.com/docs/rest/stocks/news)
  - [Market-data terms](https://massive.com/legal/market-data-terms-of-service)
- 데이터:
  - article ID, title, description, publisher, author, URL, publication time
  - associated tickers, keywords, plan에 따라 sentiment
- 가입/API 키:
  - Massive API key
- 라이선스 범위:
  - publisher article full text와 이미지는 별도 권리가 적용될 수 있음
  - 기본 저장은 metadata와 URL
  - description/full text 장기 저장, 모델 입력, 외부 표시·재배포는 계약 확인
- 적합성:
  - 후보 이벤트 탐지용 metadata에 적합

#### Nasdaq Trade Halt RSS

- 사이트:
  - [Trade Halt RSS](https://www.nasdaqtrader.com/Trader.aspx?id=TradeHaltRSS)
  - [Halt codes](https://www.nasdaqtrader.com/trader.aspx?id=TradeHaltCodes)
- 데이터:
  - symbol, company, market, halt/resume time, reason code
- 가입/API 키:
  - 불필요
- 운영:
  - Nasdaq 안내 주기보다 자주 polling하지 않음. 기존 안내는 1분 간격
- 라이선스·제약:
  - 내부 이벤트 감지와 source URL 보존
  - feed 재배포·상업 display는 Nasdaq terms 확인

### 7. 거래 달력과 비정상 휴장

#### NYSE 및 Nasdaq 공식 일정

- 사이트:
  - [NYSE hours and calendars](https://www.nyse.com/markets/hours-calendars)
  - [NYSE Trading Days PDF](https://www.nyse.com/publicdocs/Trading_Days.pdf)
  - [Nasdaq calendar](https://www.nasdaqtrader.com/Trader.aspx?id=Calendar)
  - [SIFMA unscheduled-hours policy](https://www.sifma.org/wp-content/uploads/2018/01/SIFMA-Policy-on-Unscheduled-Changes-in-Trading-Hours-April-2019.pdf)
- 데이터:
  - 휴장일, 정규 open/close, 조기 폐장
  - 비정상·임시 변경은 별도 operational alert로 보정
- 가입/API 키:
  - 불필요
- 라이선스·제약:
  - 공식 페이지/PDF를 내부 달력 검증에 사용
  - 공개 페이지가 내구성 있는 역사 API는 아니므로 수집 시각·문서 hash와 함께 archive
  - 원문 PDF 재배포 대신 파생 session metadata와 source link를 저장

#### exchange_calendars

- 사이트: [GitHub repository](https://github.com/gerrymanoim/exchange_calendars)
- 용도:
  - XNYS 등 computed baseline session 생성
- 가입/API 키:
  - 불필요
- 라이선스:
  - 저장소의 현재 오픈소스 LICENSE를 dependency 도입 시 확인·고정
- 제약:
  - 공식 공지의 대체물이 아니며 예외·임시 휴장을 공식 자료로 보정

## 사용자가 진행할 가입·계약 체크리스트

### 우선 진행 권장

- [ ] Massive 계정 생성 및 API key 발급
- [ ] Massive에 내부 non-display analytics, DB retention, derived features, ML/backtesting 권리 문의
- [ ] Alpha Vantage 무료 key 발급, 전향적 earnings snapshot용
- [ ] S&P DJI 영업팀에 point-in-time constituent/GICS 견적 요청
- [ ] Wall Street Horizon에 earnings revision archive 견적 요청

### Massive에 확인할 질문

```text
We need U.S. equities daily unadjusted OHLCV, dividends, splits, symbol changes,
delistings, corrections, historical coverage, and news metadata for internal
non-display analytics and machine-learning/backtesting.

Please confirm:
1. Included history and correction policy.
2. Rights to retain normalized data in PostgreSQL.
3. Rights to store adjusted factors and derived Alpha158/model features.
4. Whether internal reports may display excerpts or values.
5. Whether TMX corporate events and revision history are included.
6. API concurrency and rate limits for about 500 symbols daily.
```

### S&P DJI에 확인할 질문

```text
Please quote S&P 500 point-in-time constituent history and historical GICS with
announcement/effective timestamps for internal non-display analytics, backtesting,
derived feature/model storage, and long-term reproducibility.
```

### Wall Street Horizon에 확인할 질문

```text
Please quote confirmed and forecast earnings dates with point-in-time revisions,
time-of-day, source links, historical snapshots, internal database retention,
backtesting, and derived event-signal rights for U.S. equities.
```

## 환경변수 계획

키를 발급받은 뒤 로컬 `.env`에만 입력하고 저장소에는 올리지 않는다.

```dotenv
MARKET_DATA_PROVIDER=massive
CORPORATE_ACTION_PROVIDER=massive
NEWS_DATA_PROVIDER=massive
IDENTIFIER_DATA_PROVIDER=sec_edgar
EARNINGS_CALENDAR_PROVIDER=alpha_vantage
FUNDAMENTALS_DATA_PROVIDER=sec_edgar

MASSIVE_API_KEY=
MASSIVE_BASE_URL=https://api.massive.com
ALPHA_VANTAGE_API_KEY=
ALPHA_VANTAGE_BASE_URL=https://www.alphavantage.co/query

# Contract-specific values. Names may change after delivery method is confirmed.
SP_DJI_DELIVERY_MODE=
SP_DJI_ENDPOINT=
SP_DJI_USERNAME=
SP_DJI_SECRET=

WSH_DELIVERY_MODE=
WSH_ENDPOINT=
WSH_USERNAME=
WSH_SECRET=
```

키 입력 후 다음 명령은 실제 key 값을 출력하지 않고 설정 여부만 보여준다.

```powershell
.\.venv\Scripts\python.exe -m sp500_candidate_engine --env-file .env check-config
```

현재 Massive·Alpha Vantage·SEC collector는 아직 구현 전이므로 key를 입력해도 기존 Yahoo prototype 수집기가 자동으로 전환되지는 않는다. 다음 구현 단계에서 각 provider adapter를 추가하고 이 selector에 연결한다.

## 도입 우선순위

1. SEC EDGAR, Nasdaq symbol/halts, 공식 거래 달력 수집기 구현
2. Massive 계약 및 Yahoo 일봉 교체, 분할·배당 수집
3. Alpha Vantage earnings snapshot을 오늘부터 축적
4. S&P DJI 계약 후 과거 구성·GICS 재구축
5. Wall Street Horizon 또는 검증된 TMX entitlement로 과거 earnings revision 보강
6. 뉴스 metadata 계약 범위 확정 후 이벤트 수집

가장 큰 연구 품질 차단 요소는 S&P point-in-time constituent/GICS와 earnings revision history다. 가장 큰 운영 안정성 차단 요소는 현재 Yahoo prototype을 라이선스가 명확한 OHLCV·corporate-action 공급자로 교체하는 것이다.
