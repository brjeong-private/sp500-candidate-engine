# Model Change Log

모델·라벨·전처리·평가·선정 의미가 바뀔 때마다 새 version과 artifact를 생성하고 이 문서에 기록한다. 기존 실행 기록과 artifact는 덮어쓰지 않는다.

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
