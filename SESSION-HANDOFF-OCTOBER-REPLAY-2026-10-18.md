# 새 세션 인계: 2026년 10월 후보·분석 보고서 재처리

작성: 2026-10-18 17:20 KST 전후. **작업 완료 보고서가 아니라 실행 중 작업의 인계 문서**다.
수치는 작성 시점 기준이다. 행동 전에 실제 프로세스·결과 파일·DB 상태를 다시 확인한다.

## 0. 가장 먼저 — 실행 중 평가를 중복 시작하지 말 것

1. [PROJECT-HARNESS.md](PROJECT-HARNESS.md)를 먼저 읽는다.
2. [11일 전체 실제 ID·영수증 snapshot](SESSION-HANDOFF-OCTOBER-REPLAY-2026-10-18.json)을 읽는다.
3. **이전 세션에서 다음 평가가 실행 중이다. 재실행하지 않는다.**
   - tool shellId: `oct-llm-early8`
   - 확인된 PowerShell PID `32812`, 실제 Python PID **`32272`**
   - 결과 감시 shellId `oct-early-first-ready`, PowerShell PID `29200`
4. 평가가 끝날 때까지 기존 세션/프로세스를 종료하지 않는다. attached 명령은 원래
   세션 종료 시 중단될 수 있다. 새 대화는 **같은 체크아웃의 관련 작업**으로 이어간다.
5. 새 대화에서 이전 shellId가 안 보인다고 평가를 다시 시작하지 않는다.
   PID와 아래 `result.json`을 먼저 확인한다. 이미 성공한 날짜는 재호출하지 않는다.
6. 이전 SQLite todo/state가 새 대화에 없을 수 있으므로 이 문서·snapshot·실제 파일을 기준으로 한다.

```text
후보 저장소:
C:\Users\Boram Jeong\repo\sp500-candidate-engine

Portal/TradingAgents 저장소:
C:\Users\Boram Jeong\repo\jongmok-toronbang

이전 세션 files(이하 $s):
C:\Users\Boram Jeong\.copilot\session-state\2c02baae-4ee1-4fb3-aaaf-016ea6591301\files

작업 증적 루트(이하 $w):
$s\october-replay-20261018

진행 중 결과:
$w\llm-evaluation-early\<날짜>\result.json
```

작성 시점 9/30·10/1은 `RUNNING`, 나머지 6일은 아직 평가 차례 전이다.
8일 전체 입력 준비는 이미 통과했다. **새 세션은 최신 상태를 다시 읽어야 한다.**

## 1. 원래 사용자 지시

- 필요한 정의는 실행 전에 질문해 확정한다. 독립 작업은 병렬 처리한다.
- **기본 데이터 수집을 다시 하지 않는다.**
- 해당 주차에 필요한 과거 정량 모델을 최신 승인 주간 요건으로 재빌드한다.
- 기존 MEDIUM_20D 후보와 연결 분석 결과는 백업 후 삭제·교체한다.
- Quant20·독립 LLM20·Fusion20을 각각 저장하며 **보고서는 최종 Fusion20만** 생성한다.
- `ca-jongmok-tradingagents`를 필요한 동안 증량하고 완료·중단/대기 시 원복한다.
- 가상 매매 수익률을 상세한 별도 파일로 남긴다. 중간 실행 결과를 사용자에게 알린다.
- 원천·기존 모델·다른 목적·범위 밖 날짜를 보존한다.
- **코드는 커밋만 하고 Git push하지 않는다.**
- Portal/Candidate App Service **B2를 B1으로 바꾸지 않는다. DB SKU도 변경하지 않는다.**

후보 저장소 구현 범위는 후보 선정까지다. TradingAgents 코드는 별도 Portal 저장소에서만
수정했다. 이번 운영/계산 script는 이전 세션의 files에 있다.

## 2. 확정된 날짜와 가상 매매 규칙

### 2.1 날짜

- **신호 날짜:** 2026-09-30~2026-10-14의 11거래일.
- 목록: 9/30, 10/1, 10/2, 10/5, 10/6, 10/7, 10/8, 10/9, 10/12, 10/13, 10/14.
- 주말은 제외한다. **10/12는 미국 주식 거래일**이다.
- D 데이터의 후보 cutoff는 다음 달력일 D+1 **뉴욕 05:30**으로 고정한다.
- 신호 다음 **거래일 시가**에 체결한다. 10/1 매수를 위해 9/30 신호를 추가했다.
- 10/14 마지막 신호는 10/15 시가에 체결한다.
  **10/15·16 새 신호는 만들지 않는다. 10/16은 보유분 종가 평가다.**
- 기존 10/15·16 후보·보고서는 이번 삭제 범위가 아니다.

### 2.2 포트폴리오

| 항목 | 확정값 |
|---|---|
| 초기 현금 | USD 500 |
| 신규 매수 | 초기 자금의 20%인 **USD 100 고정 notional** |
| 최대 보유 | 10종목. 초기 현금으로는 5종목만 매수 가능 |
| 수량 | 소수점 주식 허용 |
| 매수 판정 | **Buy / Overweight / Hold** |
| 보유 종목 재선정 | 추가 매수·top-up 없음 |
| Sell | 잔량 전량 매도. 미보유면 무시 |
| Underweight | **남은 수량의 50%** 매도. 연속 날짜면 잔량을 다시 절반 |
| 후보/보고서가 없는 보유 종목 | 유지. 임의 청산하지 않음 |
| 현금·자리 부족 | 매수 건너뜀. Fusion 순위 우선, instrument ID 동점 정렬 |
| 같은 시가 처리 | 매도 먼저, 그 후 신규 매수 |
| 차입·공매도 | 없음 |
| 종료 | 10/16 종가 평가. 강제 전량 매도하지 않음 |

주 결과는 **비용·현금배당 제외 가격 수익률**이다. 분할은 일관된 가격/수량 기준으로 처리한다.
편도 **0.1% 거래비용 민감도**를 별도 계산한다. 이 경우 USD100 매수에 USD100.10이
필요하므로 초기 매수가 4건일 수 있다. 실제 현금·체결 건수를 다시 계산하며 음수 현금을 만들지 않는다.
세금·환율·실제 slippage·분석 API 비용은 이 가격 수익률에 포함하지 않는다.

## 3. 사용자 결정과 정책 변경

### 3.1 후보 LLM 보강

- 정책: `config\llm_preselection\policy_event_optional_search_v6.yaml`.
- 검색 후 Python이 인용 URL/페이지 날짜를 검증해 승인한 발췌만 평가한다.
- 승인 자료가 없으면 v6는 `llm_search_omission`·사유·감사 파일을 남기고 DB 비가격 자료로 평가한다.
  미승인 내용을 사실로 채우지 않는다.
- **LLM 전용:** cutoff 뉴욕 전일 이전은 일자 기준, 당일은 timezone 포함 시각이 05:30보다 엄격히 이전.
- Bing freshness는 발견일 filter이며 원문 공개일 증명이 아니다.
- 모델 이름·버전은 source 승인/거부 기준이 아니다.
- Quant 점수·OHLCV는 LLM rubric에 넣지 않는다. 가격은 공유 적격성 검사에만 사용한다.

### 3.2 TradingAgents 엄격 모드 — 롤백 완료, 재도입 금지

이번 세션에서 frozen-evidence strict 모드를 구현·배포했으나 사용자가
**기존 날짜 필터를 사용하고 이번 세션의 엄격한 방식은 롤백**하라고 지시했다.

- 현재는 **기존 graph·날짜 필터·Fusion handoff**다. `report_context`를 보내지 않는다.
- 코드 롤백 commit `a3b6c1e`, Git push 안 했다.
- worker desired/effective image:
  `acrjongmok8d0218f4.azurecr.io/tradingagents@sha256:1dd6bef531fb106479c722f7c85474e2f54cf6703da326c78ad453647f886d9c`
- Portal 복구 image digest:
  `7dfc2ad977040512895f857d50a94d48909584d8bf9479b6f648bdf2ef201542`
- migration005의 `job_analysis_contexts`는 미사용 0행으로 남겼다. DROP하지 않았다.
- source 수정본·현재 vendor snapshot·모델 memory의 완전한 PIT 안전성을 보증하지 않는다.
  **기존 날짜 필터로 지금 만든 판단에 대한 사후 가상성과**로 명시한다.
  strict PASS나 실제 당시 운용 성과로 표현하지 않는다.

### 3.3 과거 종목 상태 — 연구용 적격성 승인

`ref.instrument_state`는 거래소와 `LISTED` 관찰 이력이다.
일반 수집은 SEC 목록에서 확인하면 저장하고 상태가 같으면 새 행을 만들지 않는다.
과거 backfill은 이 이력을 채우지 않았다. 최초 관찰은 10/9 12:49 UTC, 503종목 각 한 행이다.
**종목이 그날 처음 상장됐다는 뜻도, S&P500 목록이 없다는 뜻도 아니다.**

사용자가 명시 승인:

> 새 수집 없이 기존 DB의 해당일 가격·해당일로 기록된 S&P500 구성으로 연구용 대상 판단.

- 정책 `historical-membership-price-research-v1`, 분류 `EXPERIMENTAL_RESEARCH_ELIGIBILITY`.
- 공식 과거 상태를 확인한 것으로 주장하지 않는다.
- `ref.instrument_state`나 원본 공개·관찰 시각을 소급 수정하지 않는다.
- 새 immutable HRECON 연구 context에서만 적용한다.
  정규 일일·주간 기본값과 OPERATIONAL_REPLAY는 유지한다.
- cutoff·미래 가격/미성숙 라벨 금지·품질·lookback·identity·모델 조건은 그대로다.
- 승인 범위는 [PROJECT-HARNESS.md](PROJECT-HARNESS.md) §7.1.1에 기록했다.

## 4. 주차별 모델 — 실제 재빌드/서빙 완료

| 학습 data anchor | 적용 신호 날짜 | 실제 모델 ID |
|---|---|---|
| 9/25 | 9/30~10/2 | Ridge `861b5f38-f10c-565f-989d-7253d34c13f5` |
| 10/2 | 10/5~10/9 | Ridge `3fc6ebf4-03ee-5624-bfab-cd259fe2accb` |
| 10/9 | 10/12~14 | LightGBM `301785d6-8512-514a-972c-b4a734e7c3b5` |

- 정책 `weekly-v2-20d-performance-suspended`.
  성능 절대/상대 gate는 비강제지만 지표는 계산·저장한다.
  coverage·test blocks·finite·label/source/artifact 무결성은 유지했다.
- fit/generated/artifact 시각은 **현재 실제 시각**이다. 당시 fit처럼 backdate하지 않았다.
- 첫 두 주차는 Ridge가 비교에서 우세했다.
  사용자가 **Ridge 그대로 artifact·추론 loader 지원**을 명시 승인했다.
  LightGBM으로 강제 대체하거나 Ridge 가중치를 LGBM으로 표시하지 않았다.
- 안전한 숫자 기반 Ridge artifact와 원래 fitted 전처리·가중치·feature 순서를 보존했다.
  기존 LightGBM schema2/loader와 backward compatible하다.
- 기존 주간 run, 운영 active assignment/live binding, 모델301785, 원본 source는 유지했다.
- 10/9 anchor는 **10/11 일요일 09:30 UTC 학습 knowledge cutoff**를 사용했다.
  주말까지 실제 확보한 archive로 구성하되 가격·label·effective 날짜는 10/9 뒤를 넣지 않았다.
- 앞 두 주차는 독립 확인된 기업행위만 투영하고 불확실한 **9 issuer를 명시적 품질 제외**했다.
  원래 membership·21개 action·parent·hash는 보존했다.
- 앞 두 주차 coverage **147,711/151,911 = 97.2352%**, test blocks **15개**.
  denominator를 줄여 coverage를 부풀리지 않았다.

실제 source·모델·Quant delivery:

```text
data\output\historical-models\execution-20261018\delivery-ridge-research-final.json
data\output\historical-models\execution-20261018\handoff-current.json
data\output\historical-models\execution-20261018\handoff-certified-subset.json
```

기존 accepted `artifact-registry.json` SHA:
`6544fd1dc6277d46f630a04371377220f7311f2d27f0789b42d1687f529fd90e`.
**Quant12~14 계약이 pin한 파일이므로 덮어쓰지 않는다.** Ridge는 별도 registry를 만들었다.
경로·hash는 delivery 파일을 읽는다.

## 5. 실제 완료와 미완료

- **정량: 11일 ×20 = 220개 모두 완료.**
- **LLM·Fusion: 10/12~14 각20, 합계60개씩 완료.**
- **보고서: 10/12~14 각20, 실제60건 생성·private 검증·등급 export 완료.**
- **교체: 10/12~14 old10→new20, SQL·Blob·old Quant 정리 모두 commit 완료.**
- 나머지 8일 입력 준비는 **86/78/73/78/80/76/78/77** 종목으로 통과했다.
  실제 v6 평가가 진행 중이며 작성 시점 첫 두 날짜가 RUNNING이었다.
- **전체220 보고서와 전체기간 수익률은 아직 완료가 아니다.**

완료한 세 날짜:

| 날짜 | context ID | Quant selection ID | LLM selection ID | Fusion ID |
|---|---|---|---|---|
| 10/12 | `bba3636b-5f41-516e-87f7-97fade3ab5c5` | `f6f4b91e-c269-5e11-8c2d-6168ac918a1c` | `b417b2e6-23b7-4528-9e73-0c55e23ed289` | `9070a46a-9b87-4421-a132-117b4be3ce65` |
| 10/13 | `140b81e2-38bd-51e4-8360-bb5fd8633d6a` | `14740a44-7f77-5dbe-b5b7-be4ec6f06d89` | `9c67d0b1-9aff-4a6c-b9c8-bdb868547342` | `50c21c34-24ff-4f0e-9f6c-1696975fd91b` |
| 10/14 | `db0d18ec-e5a1-5d8d-b340-843d36092d67` | `0ffc987d-5a41-5fd5-bbac-24d7a59f843b` | `638fe22b-1abf-4951-bdac-71bded97bca7` | `52800c74-701f-4cee-9010-773ce99b7ef0` |

나머지8일 전체 ID는 snapshot JSON `dates`와 delivery JSON에 있다. 추측하지 않는다.

## 6. 진행 중 LLM 실행의 의미

script: `$s\oct_llm_replay.py`.

- mode `evaluate`, output `$w\llm-evaluation-early`
- `--date-concurrency 2 --assessment-concurrency 3`
- input `$w\research-context-refs\<각8일>.json`
- 같은 process의 날짜들이 **30RPM / 125,000TPM** limiter를 공유한다.
  원 policy60/250k보다 낮춘 operator shaping이다. 실제 quota를 늘린 것이 아니다.
  날짜 수만큼 limiter를 복제하지 않는다.
- candidate repo `.venv\Scripts\python.exe`를 사용한다.
- credential/PG token은 기존 helper로 메모리에서만 취급하며 출력하지 않는다.

process가 살아 있는 동안 **새 평가를 시작하지 않는다**.
각 `result.json`이 SUCCEEDED/20이면 다음 단계로 넘긴다.
실패일은 원인을 찾고 동일 artifact 폴더·정상 응답을 재사용해 실패분만 재개한다.

10/14의 수정된 오류:

- 새 병렬 로직이 반복 HTTP/schema/retry token을 기존 evidence cohort admission cap에
  누적해 기존 직렬보다 의도치 않게 엄격해졌다.
- `_InputTokenBudget.reserve`에서34,918 token 부족으로 중단됐다. TPM 원인은 아니었다.
- **원래 cohort+search admission 의미로 복원**했다. 실제 사용량 감사,
  공유 limiter·retry 횟수·source/evidence 검증은 유지했고 한도는 올리지 않았다.
- 94검색과 정상17batch를 재사용해16/18의9종목만 요청하고 성공했다.
  commit521bc96,158tests pass.

## 7. 성공한 날짜부터 Fusion → report로 진행

8일 전체 완료를 기다릴 필요 없다.

1. 현재 watcher `oct-early-first-ready`가 첫 완료일을 알린다.
   다음에는 `$s\oct_wait_llm_result.py --exclude <처리한날짜>`로 새 읽기 전용 watcher를
   시작할 수 있다. **평가 process를 복제하는 것이 아니다.**
2. LLM selection ID를 같은 날짜의 실제 Quant/context ID와 연결한다.
3. `$s\oct_fusion_delivery.py fuse ... --execute`로 기존 FusionService를 실행한다.
   v6 LLM hash와medium20D Quant policy를 명시한다.
   public stage factory는 live 기본v2일 수 있어 무조건 쓰지 않는다.
4. SUCCEEDED/20을 확인한 뒤 report 전송한다.

```powershell
$repo='C:\Users\Boram Jeong\repo\sp500-candidate-engine'
$s='C:\Users\Boram Jeong\.copilot\session-state\2c02baae-4ee1-4fb3-aaaf-016ea6591301\files'
$w=Join-Path $s 'october-replay-20261018'
$c=Join-Path $repo '.venv\Scripts\python.exe'
$p='C:\Users\Boram Jeong\repo\jongmok-toronbang\.venv\Scripts\python.exe'
# 아래 placeholder는 실제 ID로 바꾼 뒤 실행한다.
& $c "$s\oct_fusion_delivery.py" fuse --target-session '<DATE>' `
  --context-id '<ACTUAL_CTX>' --quant-id '<ACTUAL_QUANT>' --llm-id '<ACTUAL_LLM>' `
  --idempotency-key 'october-replay-fusion20-<DATE>-1' `
  --output "$w\fusion\<DATE>\fusion-record.json" --execute
```

Fusion policy `daily-medium-20d-rrf:1`, k10·sector2→4·issuer중복제거·union밖확장금지.

| 항목 | hash |
|---|---|
| Fusion config | `e7bce34c4abf34f5bc41fb3d93f80c5aa744d24483b483937b8dac4920723b87` |
| Quant policy | `df8a6cc3a6942ca85c485839f4d81a087a238070f25acc5c3d30248466a9e8cd` |
| LLM v6 | `f84d5d11cec57632ef55935e38a998267b09aabd7e0f74890815fbc0aa9a72bf` |

## 8. 임시 capacity와 실제 report 전송

현재 **RESTORED: min1/max1, worker3, Multiple mode**다. 두 App Service는B2다.

- lease: `$w\capacity-lease.json`, helper `$s\oct_replay_capacity.py`
- report가 준비됐을 때만3replica=9worker로 올린다.
  Multiple 교체 중old1+new3=4로 승인상한4를 넘기지 않는다.
- **transition 전에 전체Portal pending/running=0을 새로 확인**한다.
  실행 중이면revision을 바꾸지 않는다. 이미scale상태면 그대로 추가 전송한다.
- 사용자가 새로 변경한 구성은 baseline으로 덮어쓰지 않는다.

```powershell
& $p "$s\oct_report_queue_watch.py" once --output "$w\pre-dispatch-idle-<DATE>.json"
# active_or_pending_jobs=0 확인 후:
& $c "$s\oct_replay_capacity.py" scale --replicas 3 --no-running-jobs-confirmed `
  --state "$w\capacity-lease.json"
& $c "$s\oct_fusion_delivery.py" handoff --record "$w\fusion\<DATE>\fusion-record.json" `
  --output "$w\fusion\<DATE>\handoff-receipt.json" --execute
```

전송은 기존 orchestrator `fetch_fusion_handoff/submit_fusion_handoff`를 재사용한다.
exact20·hash·identity·ACK·idempotency를 검증하고 report_context는 보내지 않는다.
새 Fusionrun은 `create_job(reuse_existing=False)`로 **새20job**을 만든다.
old Quant report를 먼저 삭제할 필요 없다. **new20검증 → old삭제** 순서를 유지한다.
같은Fusionrun의 재전송은 receipt/jobs를 재사용해 중복 생성하지 않는다.

batch마다 queue drain watcher를 켜고 idle이면 곧 원복한다.
LLM/source 대기로 큐가 비었는데3replica를 계속 두지 않는다.

```powershell
& $p "$s\oct_report_queue_watch.py" wait --interval 60 --idle-seconds 120 `
  --timeout 21600 --output "$w\queue-watch-<BATCH>.json"
# drain 알림 뒤 최신queue 확인:
& $c "$s\oct_replay_capacity.py" restore --no-running-jobs-confirmed `
  --state "$w\capacity-lease.json"
```

helper는 새revision ready 후에도 queue를 다시 확인하고 old를 비활성화한다.
worker·image·Multiple을 보존하며 App Service/DB SKU는 건드리지 않는다.

## 9. 보고서의 실제 생성·등급·파일 검증

자세한 계약/command: `$w\ops\README.md`, helper `portal_fusion_results.py`.

- monitor: Portal venv. verify-batch: candidate venv. export: Portal venv.
- **Portal web의 PORTAL_RUN_ANALYSIS=false는 정상**: external API에 위임한다.
  active CA worker가true이다. webflag를true로 바꾸지 않는다.
- 전체20완료 후 private Blob검증한다. pending그룹 때문에console을poll하지 않는다.
- local Blob403은 private network제약이다. 기존private worker경로를 사용한다.
  firewall/RBAC을 풀지 않는다. console약5회/10분,429 Retry-After를 지킨다.
- ticker/date/identity/rating/non-demo/byteSHA/ETag/currentDB state를 대조한다.
- **실제 job·Blob시각과 client intent는 바꾸지 않는다**.
  MySQL DateTime정밀도0과 client/cloud시계차가 있어,
  실제기록한 전송 전phase시각을freshness하한으로 사용했다.
  12/13: `report-batch-freshness.json`. 14: `pre-dispatch-idle-2026-10-14.json`.
  다음batch도 실제관측을pin하고 임의유예/offset을 만들지 않는다.
- handoff helper는RPC전에 `handoff-envelope.json`, 원래 `handoff-intent.json`을 보존한다.
- monitor/verified는삭제plan이byteSHA로pin한다. **plan생성 후 같은path로 덮어쓰지 않는다.**
- 결과: `ops\outputs\{monitor,verified,ratings}-<DATE>.json`과ratings CSV.

## 10. 백업과 기존 결과 삭제

- `$w\candidate-original-backup\manifest.json`:
  old MEDIUM Quant **16runs/160candidates/320reasons**.
- `$w\portal-original-backup\manifest.json`:
  old **11groups/110jobs**와events/dispatch.
  원래110report의private `_recovery/...`copy/SHA검증도 완료.
- 이미12/13/14 old각10은Portal SQL·원본Blob·old Quant3단계 모두삭제했다.
  복구copy, source/model/scoring/feature/label/raw, 범위밖날짜·SHORT는 보존했다.

helper `$w\ops\scoped_result_cleanup.py`, 상세문서 `$w\ops\CLEANUP.md`.
**문서를 먼저 읽는다. default dry-run이다.**

- 날짜만으로DELETE하지 않는다. backup old ID집합만 사용하고new와겹치면 중단한다.
- 새Fusion20·private verified20이 그대로 존재해야 한다.
- row/hash/ETag/FK/sharedlocator/activeoldjob/밖의source_job참조 drift는중단한다.
- 순서: **Portal SQL → old original Blob → old Quant PG**.
- `--execute --confirm-plan-sha256 <plan.plan_id>`로단계별 실행한다.
- 일부commit후실패하면pending으로 남긴다. 앞commit을 없었던 것으로 표시하지 않는다.
- immutable terminal ops audit를바꾸거나 model/source를삭제하지 않는다.

완료한plan:

| 날짜 | old daily/jobs | new daily/jobs | plan ID |
|---|---|---|---|
| 10/12 | 14 / 138..147 | 50 / 538..557 | `692676158703ca84861102168a16c6bf1764952283129511944d2c27ea864796` |
| 10/13 | 16 / 158..167 | 51 / 558..577 | `4cbe28ab64f1784d45ebcd7157c2eedce303179fdc66eb1d0cd2e9cd00f5803e` |
| 10/14 | 44 / 438..447 | 52 / 578..597 | `5dda99777f53bfec8535759634f567c255b9413cb71ce0f5c0b29eb90707d74e` |

영수증: `ops\cleanup-receipts\<12|13|14>-<portal|blobs|candidate>-commit.json`.
**이3일은 재생성·재삭제하지 않는다.**

## 11. 포트폴리오 입력 조립과 최종 상세 보고서

실행/계약문서: `$s\october-portfolio\README.md`.

```text
portfolio_eval.py
portfolio_sensitivity.py
assemble_portfolio_input.py
input-schema.json
```

- 기본36+비용10+mode8=54 tests, assembler포함69 tests를 확인했다.
- `EXISTING_DATE_FILTER_RECONSTRUCTION` 명시mode와 정확한warning을 요구한다.
  source `DATE_FILTERED_UNVERIFIED`, 결과 `OBSERVATIONAL_PAPER_RESULT`.
  strict PASS로 바꾸지 않는다.
- assembler `build()/require_ready_input()`은 **11일각20,총220검증된report** 전에는거부한다.
  60건만갖고 현금500·0%를 전체기간성과로계산하지 않는다.
- 현재조립상태: `assembly-status-actual-incomplete-20261018.json`.
- outcome가격 `$w\portfolio-outcome-prices.json`:
  existing MASSIVE_STOCKS/source28 UNADJUSTED **6,547rows**,50dividend/0split.
  **체결·평가outcome만이며 과거LLM입력으로넘기지 않는다.**
- 달력 `$w\portfolio-calendar.json`: offline exchange_calendars4.13.2 XNYS,13sessions.
  추가network수집없음. 모든종목이NYSE상장이란뜻이아니다. venue불명은UNKNOWN을유지한다.
- source/report SHA와실제생성시각은유지한다.
  “09:00NY등개장전에판단을얻었다고가정”을명시하고 실제보고서생성일을바꾸지 않는다.
- 220건ready후gross+fee민감도를계산한다.
- 거래목록·skip사유·일별NAV/현금/보유·실현/미실현손익·승률/최대DD정의·모델/run/context·
  데이터한계를 **상세한 한국어 별도report파일**로남긴다.
- 최종상세손익report는 **아직 작성하지 않았다**.
  20D모델신호의2주내매매실험이며20거래일선행예측전체가만기평가된것은아니다.

## 12. 커밋·검증·다른 미커밋 변경 보존

후보repo:

- `da5e4a8`, `40b1a4a`, `ef40d01`: 비승격과거재구성,시각/가격context정합.
- `0992a71`: certified issuer scope,원denominator유지.
- `dd352f0`: 기본직렬·선택적평가batch병렬.
- `521bc96`: 병렬의도치않은누적예산regression수정.
- `bd0236e`: 사용자승인연구용적격성harness.
- `77d6d34`, `d1e5f4b`: Ridge서빙·연구8일Quant20·LGB호환/격리.
- 모델/Ridge/research **415pass/6intentional skip**,Ruff/type clean.
- 예산수정158pass,ops handoff/capacity18pass,cleanup122fakepass.

Portalstrict추가 `7a58963`,`487e479`,`4d9bc47`은 `a3b6c1e`로롤백했다.

작성전미커밋:

- 후보repo `SELECTION-DATABASE-ER.md`: 다른작업의변경이다. 되돌리거나함께commit하지 않는다.
- Portalrepo `uv.lock`, untracked `reasoning_update.plan`,`update_plan.md`도 보존한다.
- 이handoff문서/snapshot/CHANGELOG만별도commit하되 **push하지 않는다**.
- APIkey/token/password/connectionsecret/rawproviderpayload를인계·changelog에넣지 않는다.

## 13. 남은 작업 순서

1. 진행중평가PID를중복시작하지말고 첫완료일의실제LLMrun ID를읽는다.
2. 같은날새Quant20+LLM20으로Fusion20을생성·검증한다.
3. 준비된report가있을때만capacity를올려정상handoff20ACK시킨다.
4. 뒤날짜LLM이도는동안앞날짜report를생성해겹쳐처리한다.
5. 각20actualreport완료후private본문/등급/hash검증·export.
6. 해당날짜old결과만백업ID로안전하게정리한다.
7. 전체11일220actualverified까지반복한다. 실패는원인확인후cache로제한재시도한다.
8. assembler→gross/fee민감도→상세한국어손익report·ledger·provenance를저장한다.
9. 일별20,oldMEDIUM범위교체,원천/기존모델/다른날짜/SHORT보존을재검증한다.
10. **queueidle,min1/max1,worker3,기존날짜filterimage,양쪽AppServiceB2**를실리소스로확인한다.
11. 관련CHANGELOG/report를owned변경만commit한다. **Git push금지**.
12. 모두검증하기전task complete하지 않는다. 미완료는미완료로명시한다.

새 대화의 시작 지시:

> 이인계와snapshot을읽고평가PythonPID32272를중복시작하지않고인계한다.
> 전체Quant220와10/12~14의verified60/교체완료는재실행하지않는다.
> 나머지8일LLM→Fusion→기존날짜filterreport→안전한old교체→확정USD500전략손익까지계속한다.
> 승인된Ridge/연구용적격성을사용하고B2·원천·현재active모델을보존한다.
> 임시replica는원복하고코드/report는commit만하며push하지않는다.
