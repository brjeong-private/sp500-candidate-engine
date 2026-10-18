# Model Change Log

모델·라벨·전처리·평가·선정 의미가 바뀔 때마다 새 version과 artifact를 생성하고 이 문서에 기록한다. 기존 실행 기록과 artifact는 덮어쓰지 않는다.

## Certified eligible-scope historical fits — 2026-10-18

Sep25·Oct2의 MEDIUM_20D를 각 원래 주말 cutoff로 실제 재학습했다. 독립 원천 검증이
미완료인 9개 issuer 전체의 가격 이력·actions를 새 입력 scope에서 제외했으며 기존
S&P 500 membership·21개 원본 action·12개 인증 proof·raw 부모·기존 모델은 보존했다.
DD의 인증 action도 issuer 전체 제외 규칙에 따라 입력에서 제외해 실제 split 입력은
11개다. 기존 source timestamp를 변경하거나 archive 날짜로 공개 시각을 만들지 않았다.

| 데이터 anchor | 학습 LightGBM model ID | Coverage | Test blocks | Rank IC |
|---|---|---:|---:|---:|
| 2026-09-25 | `72d7ae33-91bf-53ae-8dcd-13e79fd04f6c` | 0.972352232557221 | 15 | -0.007180049227192266 |
| 2026-10-02 | `6cae0332-9696-53d4-ac07-11ab7e307ea2` | 0.972352232557221 | 15 | -0.007180049227192266 |

Coverage는 필터링한 494개만 분모로 삼지 않고 원래 PIT membership과 503개 reference
floor를 보존한 `147711 / 151911`이다. 원래 historical membership 501~504개를
503개로 다시 쓰지 않았다. 목적·20D label·train-only fitting·purge·finite·최소 test
block과 weekly-v2 기준은 유지했다.

두 실행의 Ridge Rank IC는 -0.005887378846971518로 LightGBM보다 높았다.
기존 선택 규칙상 Ridge가 shadow winner였으므로 **LightGBM-only serving artifact
packaging은 실패로 중단했다**. 학습 weight·모델 row는 모두 SHADOW로 보존하고
임의로 winner를 바꾸지 않았다. 실제 fit/생성 시각은 Oct18이며 과거로 소급하지 않았다.
기존 `301785d6-...` 모델·이미 수락된 `artifact-registry.json`·weekly/active state는
변경하지 않았으며 새 registry는 별도 이름의 NOT READY 진단 파일이다.

추가로 Sep30~Oct8에는 실제 as-of instrument-state가 0개여서 후보 inference 최소
20개 gate를 충족하지 못한다. 학습 완료를 Quant/LLM 후보 실행 준비 완료로 표현하지
않으며 이 reference-state gate도 완화하지 않았다.

## MEDIUM_20D v1 isolated Sunday challenger — 2026-10-18

- 기존 Alpha158·LightGBM·20D raw-return 의미와 학습/평가 설정을 재사용한 별도
  `HISTORICAL_RECONSTRUCTION`이다. 정규 weekly run의 재실행·소급 승격이 아니다.
- 데이터 anchor는 `2026-10-09`, 새 지식 cutoff는 일요일
  `2026-10-11T09:30:00+00:00`이다. 모든 학습/평가 가격과 label exit는 Oct9 이하이며,
  실제 fit/artifact 시각은 아래와 같이 Oct18이다. 토요일 context를 수정하지 않았다.
- Windows 긴 경로로 중단한 첫 export는 보존하고 새 UUID·짧은 로컬 경로에서 완료했다.
  coverage·test block·finite·PIT·artifact 검증을 유지하며 현재 승인된
  `weekly-v2-20d-performance-suspended`의 성능 기준 비강제를 명시 적용했다.

```text
export_run_id: 2ca2ad52-b23b-5f3f-bcea-0df92329225d
model_version_id: 301785d6-8512-514a-972c-b4a734e7c3b5
fit_at: 2026-10-18T02:45:57.566494+00:00
fit_completed_at: 2026-10-18T02:46:02.158196+00:00
artifact_created_at: 2026-10-18T02:46:02.604077+00:00
label_semantics: RAW_STOCK_20D_RETURN
score_semantics: PREDICTED_20D_RETURN
coverage: 1.0
test_blocks: 16
Rank IC mean: 0.006071621217650402
fold Rank IC median: 0.017246324342173415
Top-10 net return at 10 bps: 0.03051508489666669
Top-10 max drawdown: -0.13883960753131785
manifest_sha256: 721b3f545181102bb7c0022e81bff23b24087694e83e18a354df6eaa2732af8b
model_sha256: 4c5f8e4eb667ecf5942187a4d69282edf50f36541a021099056b94f22d5b2550
provenance_sha256: 234108b7422b3602d17c41d80f1fb2b90e70d19d83e861b9e5ac20aefe5767e6
promotion_status: SHADOW
promotion_allowed: false
```

Oct12–14 신호의 명시적 artifact override admission을 검증했다. 과거 model row의
hash·weekly run·active assignment는 모두 보존하고 새 SHADOW baseline 3개만 추가했다.
live artifact 환경 바인딩·승격·배포·후보 실행은 이 학습에서 수행하지 않았다.
이 실행은 새로운 split FULL projection 인증/정책을 승인한 것이 아니며 Sep25/Oct2의
earlier-weekend 재구성은 여전히 미완료다. 실행 계약과 제한은
[역사 학습 실행 문서](src/sp500_candidate_engine/analytics/HISTORICAL-TRAINING.md)를 따른다.

## 독립 실행·통합 후보 운영 연결 — 2026-10-17

정량·이벤트 LLM·RRF Fusion과 단독 실행 API/CLI·상태·재시도를 구현·배포했다.
MEDIUM_20D·SHORT_5D의 모델 weight·label·horizon·평가 지표는 변경하지 않았다.
이벤트 LLM v2·RRF k=10·섹터2/4와 최종20개 계약을 유지하고, 실행 제어 stage ID와
원천 scoring/selection/ranking/Fusion ID를 분리한다.
운영에서 세 단독 경로가 고정 context의 기존20개 결과를 재사용함을 검증했으며
새 모델 학습·추가 LLM 호출·새 champion 승격으로 표현하지 않는다.
현재 배포·오류 확인은 [운영 점검서](DAILY-PIPELINE-RUNBOOK.md)를 따른다.
아래 날짜별 모델 성능·검증 상태는 당시 기록으로 보존한다.

## 후보 수·외부 전달 계약 — 2026-10-16

일일 MEDIUM_20D 정량 선정은 `medium-20d-top20-v1` 정책으로 정확히 20개이며,
향후 최종 TradingAgents 전달도 기존 5~10개에서 20개로 변경한다. 별도 LLM Top 20과의
RRF 통합·전달은 아직 미구현이다. 모델 weight·label·20거래일 horizon은 바뀌지 않으며,
SHORT_5D 레거시와 Top-5/10 평가·promotion 지표, 과거 10개 검증 기록을 보존한다.
후보 수 변경은 Top-20 수익률 검증이나 신규 champion 승격 기록이 아니다.

## Weekly retraining control contract — 2026-10-16

이 항목은 모델 release나 승격 기록이 아니라 주간 재학습 control contract의 구현
기록이다. `SHORT_5D`와 `MEDIUM_20D`의 label·score 의미와 기존 model version은
변경하지 않았다.

- production score·selection을 쓰지 않는 `run_training_only_workflow()`와 주간 run
  상태 전이를 구현했다. 학습 결과는 우선 `SHADOW`로 등록된다.
- versioned absolute/현 champion 대비 relative promotion gate를 구현했다. coverage,
  test block 수, Rank IC, fold Rank IC 중앙값, net Top-10 return, Top-10 max drawdown이
  누락되거나 유한하지 않으면 fail closed한다.
- schema-v2 manifest와 model weight의 SHA-256을 서로 다른 값으로 관리하고,
  `SHORT_5D`/`MEDIUM_20D` 목적·label·prediction horizon 계약을 검증한다.
- PostgreSQL active assignment는 manifest URI/SHA-256, Blob ETag/version, generation을
  보존하며 expected-generation CAS와 rollback history를 사용한다.
- DAILY 실행은 최초 assignment를 process metadata에 pin하고 retry에서도 같은
  generation과 artifact identity를 사용한다. 목적 간 artifact fallback은 허용하지 않는다.
- Azure PostgreSQL 16.15에서 migration rollback/실제 적용과 FK, generation CAS,
  stale-write 차단, rollback history를 검증했다.

상태 구분:

- **구현·자동 테스트 완료**: training-only 분기, promotion evaluator, artifact
  packaging/loading/cache, assignment repository, DAILY pinning.
- **DB 적용·검증 완료**: PostgreSQL 16.15 weekly schema와 제약.
- **배포 검증 안 됨**: 이 코드와 주간 Container Job/Blob/DAILY backend의 운영
  deployment 및 promotion E2E.
- **아직 통합 안 됨**: weekly job의 gate 평가·decision 저장·artifact upload·CAS
  activation·activation smoke·자동 rollback 연결.

이 변경으로 승격된 모델은 없다. 아래에 기록된 기존 모델 상태를 변경하거나 새로운
`CHAMPION`을 주장하지 않는다.

## MEDIUM_20D v1 — 2026-10-11

- 기존 `SHORT_5D`를 보존하고 Alpha158·LightGBM 기반 20거래일 raw-return
  회귀 모델을 별도 `MEDIUM_20D` 목적으로 등록했다.
- label은 `D+20 adjusted close / D+1 adjusted open - 1`이다.
- 100/40/40 sessions, step 20의 purged walk-forward를 사용했다.
- 2026-10-09 후보는 공식 cutoff의 500-session historical reconstruction
  export에서 생성했다.

```text
export_run_id: da7992fc-f64f-53a3-893f-21b1b79bc507
model_version_id: 74c367e9-bd84-58ab-b933-19a36dae35c4
scoring_run_id: cd46b3d6-dac2-5d26-b102-499641222d49
selection_run_id: 52d72987-ddf0-5a7f-9be7-1fc11aef5960
label_semantics: RAW_STOCK_20D_RETURN
score_semantics: PREDICTED_20D_RETURN
Rank IC mean: 0.006072
Top-10 net return at 10 bps: 3.0515%
promotion_status: SHADOW
```

가격 session과 label exit는 target date 이하로 제한했다. 당시 관찰 snapshot의
완전한 operational replay는 아니므로 결과를 `HISTORICAL_RECONSTRUCTION`으로
분류한다. Azure OpenAI 뉴스 특징은 optional이며 이번 모델 입력에는 포함하지 않았다.

## v2 two-year retrain — 2026-10-11

- 동일 v2 raw-return 계약과 hyperparameter를 2024-10-11~2026-10-09 500 sessions로 재학습했다.
- Baseline 비교는 유지하되 후보 scoring은 `PREDICTED_5D_RETURN` 계약을 만족하는 Qlib LightGBM으로 고정했다.

```text
export_run_id: b47ef1cc-fd0b-5c75-a0c4-e38e89c0a889
model_version_id: f75be739-4149-518f-8cbe-1cf6296e619a
scoring_run_id: fa74d683-2c11-521b-a791-5e6496920834
selection_run_id: b87800b5-8cd3-5634-91bb-b91b74a47690
LightGBM Rank IC mean: -0.005342
LightGBM Top-5 raw return: 0.6040%
LightGBM Top-10 raw return: 0.4842%
promotion_status: SHADOW
```

## v2 — 2026-10-11

- Label을 SPY 초과수익에서 `D+5 adjusted close / D+1 adjusted open - 1`의 개별 종목 raw 5거래일 수익률로 변경했다. SPY는 optional 비교 series로만 유지한다.
- Score 의미를 `PREDICTED_5D_RETURN`으로 고정하고 Top-5/10 raw·net return, 양의 수익률 비율, 5개 중첩 cohort max drawdown을 추가했다.

```text
model_version_id: 05d1cea0-469c-5874-ac1e-a6aae6cdd887
scoring_run_id: 44fdfc3b-5a85-5c11-a027-13184c0bc905
selection_run_id: 024d6c28-d523-574e-b6fd-7782c606d2ec
label_semantics: RAW_STOCK_5D_RETURN
score_semantics: PREDICTED_5D_RETURN
promotion_status: SHADOW
```

LightGBM out-of-sample:

```text
IC mean: 0.010612
Rank IC mean: -0.007575
Top-5 raw return: 1.2765%
Top-10 raw return: 0.7011%
Top-5 net return at 10 bps: 1.1765%
Top-10 net return at 10 bps: 0.6011%
Top-5 positive ratio: 55.88%
Top-10 positive ratio: 51.34%
Top-5 overlapping-cohort max drawdown: -17.89%
Top-10 overlapping-cohort max drawdown: -15.52%
```

Rank IC가 음수이므로 `CHAMPION`으로 승격하지 않고 `SHADOW`를 유지한다.

## v1 — 2026-10-11

- 초기 Alpha158·LightGBM 모델. Label은 종목 5일 수익률에서 동일 구간 SPY 수익률을 차감한 초과수익이었다.
- Score는 ranking signal로 저장했고 503개 종목 중 10개 SHADOW 후보를 선정했다.

```text
model_version_id: e6c3176d-bbc3-58ab-b904-0e9337690a78
label_semantics: LEGACY_EXCESS_RETURN
promotion_status: SHADOW
Rank IC mean: -0.007190
Top-10 excess return: 0.3077%
```
