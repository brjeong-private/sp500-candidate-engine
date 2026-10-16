# 재현 가능한 분석 노트북 환경

## 연구 결과와 운영 후보 계약

일일 기본 MEDIUM_20D 정량 후보는 정확히 20개이며
`config/analytics/model_lightgbm_20d_v1.yaml`,
`config/analytics/label_forward_return_20d_v1.yaml`,
`config/analytics/selection_medium_20d_v1.yaml`을 사용한다.
아래 기존 notebook의 5D·`selection_v1.yaml`은 SHORT 레거시 연구 경로다.
Top-5/10 평가 지표를 20으로 임의 변경하지 않는다.

수집 후 정량 Top 20과 선택 활성화된 독립 LLM Top 20을 병렬 생성하며,
향후 최종 통합·TradingAgents 전달은 기존 5~10개에서 20개로 변경한다.
통합·최종 전달은 아직 미구현이며 notebook 실행이 자동 외부 전달을 활성화하지 않는다.

## 환경 생성

프로젝트의 Qlib·학습·노트북 실행 환경은 Python 3.11을 사용한다.

```powershell
C:\Users\annajeong\AppData\Local\Programs\Python\Python311\python.exe `
  -m venv .venv-alpha158

.\.venv-alpha158\Scripts\python.exe -m pip install -e ".[analytics,notebook,dev]"
.\.venv-alpha158\Scripts\python.exe -m ipykernel install `
  --user --name sp500-alpha158 --display-name "S&P500 Alpha158 (Python 3.11)"
```

VS Code에서 `S&P500 Alpha158 (Python 3.11)` kernel을 선택한다.

DB에서 새 label·model·score·candidate를 저장하는 실행은 Azure PostgreSQL이 실행 중이어야 한다. 비용 방지를 위해 평소 서버는 중지 상태로 유지하며 실행 전에 시작한다.

```powershell
az postgres flexible-server start `
  --name pg-jongmok-candidate-8d0218f4 `
  --resource-group rg-ai-project `
  --subscription 8d0218f4-f340-446d-b76a-3ff419b03e77
```

## 실행 순서

1. `phase4_5_training_selection.ipynb`: Phase 4 학습·평가와 Phase 5 점수·후보의 기준 실행
2. `alpha158_analysis.ipynb`: Alpha158 분포·상관을 보는 기존 탐색용 notebook이며 기준 학습 pipeline은 아님

노트북은 로직을 복제하지 않고 `src/sp500_candidate_engine`의 테스트된 서비스를 호출한다.

## 재현성 입력

- Qlib export run ID와 `manifest.json` content hash
- `config/analytics/model_lightgbm_v2.yaml`
- `config/analytics/label_forward_return_5d_v2.yaml`
- `config/analytics/selection_v1.yaml`
- seed 42
- 날짜 기반 walk-forward split
- artifact 및 config SHA-256

실행 결과와 cell output 사본은 `notebooks/output/`에 저장하며 Git에 포함하지 않는다. 모델·후보 artifact는 `data/output/phase45/`에 저장하며 Git에 포함하지 않는다.

## 비대화형 실행

```powershell
.\.venv-alpha158\Scripts\python.exe -m jupyter nbconvert `
  --to notebook `
  --execute notebooks\phase4_5_training_selection.ipynb `
  --output-dir notebooks\output `
  --ExecutePreprocessor.timeout=3600
```

또는 동일 workflow를 CLI script로 실행할 수 있다.

```powershell
.\.venv-alpha158\Scripts\python.exe scripts\run_phase4_5.py `
  --env-file .env `
  --export-run-id 351a5af0-5bc1-50d0-ab20-fa8292afe787
```
