# Model Change Log

모델·라벨·전처리·평가·선정 의미가 바뀔 때마다 새 version과 artifact를 생성하고 이 문서에 기록한다. 기존 실행 기록과 artifact는 덮어쓰지 않는다.

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
