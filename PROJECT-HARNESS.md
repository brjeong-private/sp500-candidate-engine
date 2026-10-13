# S&P 500 Candidate Engine 공통 하네스

**적용 범위**: 저장소의 코드, SQL, 설정, 배치, 모델, 테스트, 운영 문서 전체
**목적**: 수집부터 후보 선정까지 동일한 범위·시점·무결성·재현성 규칙을 강제한다.

이 문서는 프로젝트 공통 불변식의 기준 문서다. 기능별 계획이나 설계 문서가 이 문서와 충돌하면 이 문서를 우선하며, 예외가 필요하면 변경 이유·영향·검증 방법을 먼저 문서화해야 한다.

## 1. 프로젝트 범위

프로젝트의 끝은 다음 네 단계다.

```text
수집 -> 전처리 -> 모델 점수 -> 후보 선정
```

### 포함

- 시장·기업행위·종목·유니버스·공시·재무·이벤트 데이터 수집
- 원본 snapshot, 정규화, 품질 검사, point-in-time manifest 생성
- Qlib 데이터 export, 조정가격, 특징, 라벨, processor, 모델 학습·평가
- 일일 모델 점수, 전체·그룹 순위, 5~10개 후보와 선정 사유 저장
- 후보 결과를 외부 소비자가 읽을 수 있는 안정적인 조회·파일 계약

### 제외

- TradingAgents 또는 다른 agent의 실행·상태·prompt·memory·report·비용 관리
- 후보에 대한 LLM 분석, 매수·매도 판단, 주문 생성과 자동 매매
- 외부 분석 시스템의 재평가·cooldown·중복 실행 정책
- 외부 소비자의 최신 뉴스·웹 검색에 대한 시점 통제

후보 결과는 **후속 분석 대상 목록**이며 매수 추천이나 포트폴리오 주문이 아니다. 외부 시스템 연동은 이 저장소 밖에서 별도로 구현한다. 이 저장소는 특정 외부 소비자에 종속된 스키마나 실행 상태를 만들지 않는다.

오케스트레이터는 Candidate 실행과 외부 소비자 연계를 조정하는 control plane이며,
Candidate Engine의 사업 범위를 위 네 단계 밖으로 확장하지 않는다.

## 2. 규칙의 적용 우선순위

`.local/PROJECT-HARNESS.local.md`가 존재하면 개발 머신에만 필요한 추가 규칙으로
선택 적용한다. 로컬 하네스는 이 공통 하네스의 범위와 불변식을 완화하거나 대체할 수 없다.

1. 이 문서의 공통 불변식
2. 승인된 schema와 versioned 설정
3. 기능별 설계·구현 계획
4. 실험용 notebook·임시 분석

실험 코드도 원천 데이터를 변경하거나 미래 누수 방지 규칙을 우회할 수 없다. 실험 결과가 운영 결과로 승격되려면 동일한 manifest·설정·artifact 검증을 통과해야 한다.

## 3. 데이터 무결성

### 3.1 원본 불변성

- 원본 응답은 content hash와 함께 immutable snapshot으로 보존한다.
- 정정·재수집·재계산은 기존 원본이나 논리 revision을 덮어쓰지 않는다.
- 동일 자연키와 동일 payload hash는 기존 revision을 재사용한다.
- payload가 바뀐 경우에만 다음 revision을 생성한다.
- 급등락·결측이라는 이유로 원본 값을 임의 수정하거나 삭제하지 않는다.

### 3.2 식별자와 시점

- ticker 문자열을 영구 식별자로 사용하지 않고 `instrument_id`를 기준으로 한다.
- ticker, 거래소, 종목 상태, 유니버스 membership, 분류는 유효기간을 보존한다.
- `valid_from/to`, `source_available_at`, `observed_at`을 서로 다른 의미로 관리한다.
- 동일 issuer의 복수 share class는 명시된 정책 없이 하나로 합치지 않는다.

### 3.3 거래일과 결측

- 날짜 계산은 versioned 거래소 session을 기준으로 한다.
- 휴장, 상장 전, 상장폐지 후, 거래정지, provider 결측을 같은 `NaN`으로 취급하지 않는다.
- `$change`와 일일 수익률은 직전 **거래 session** 기준이다. 중간 session 값이 없으면 여러 날 수익률을 1일 수익률로 만들지 않고 결측·품질 상태를 기록한다.
- forward fill로 가격·거래량·라벨을 임의 보완하지 않는다.

### 3.4 기업행위

- raw OHLCV와 adjusted OHLCV를 분리한다.
- split·dividend factor는 사용한 action revision과 adjustment policy version을 참조한다.
- 가격과 거래량 조정 방향을 함께 검증하여 이중 조정을 막는다.
- ratio 충돌이나 action lineage 누락이 있으면 해당 종목의 특징·점수 생성을 차단한다.

## 4. 미래 데이터 누수 방지

### 4.1 의사결정 시각

- 모든 일일 실행은 `target_session`, `cutoff_at`, `generated_at`을 구분한다.
- session D 후보는 D 데이터가 확정된 뒤 정의된 cutoff에서 생성한다.
- 특징 입력은 해당 의사결정 cutoff까지 이용 가능했던 정보만 포함한다.
- 미래 가격은 라벨과 사후 평가에만 사용하고 입력 특징에 포함하지 않는다.

### 4.2 manifest 제한 조회

- 모든 분석·학습·추론 조회는 `execution_context_id`를 필수로 받는다.
- context의 `input_manifest_member`에 포함되지 않은 snapshot은 읽지 않는다.
- 단순히 `source_available_at <= cutoff_at`인 최신 row를 임의 선택하지 않는다.
- FULL/DELTA lineage가 끊기거나 precedence가 모호하면 fail closed한다.

### 4.3 재현 모드

- `OPERATIONAL_REPLAY`: 당시 시스템이 실제 관찰한 snapshot만 사용한다. `source_available_at`과 `observed_at`이 모두 cutoff 이하여야 한다.
- `HISTORICAL_RECONSTRUCTION`: 현재 확보한 원천으로 과거 cutoff를 재구성한다. 당시 운영 재현으로 표현하지 않는다.
- 과거 원천 revision, 유니버스, GICS 이력을 복원할 수 없으면 제한을 결과 metadata와 평가 보고서에 명시한다.
- 현재 분류를 과거에 적용한 실험은 point-in-time 분류 실험과 분리한다.

### 4.4 학습 누수

- 무작위 train/validation/test split을 사용하지 않는다.
- processor는 train segment에서만 fit하고 validation/test/일일 추론에서 refit하지 않는다.
- 라벨 horizon이 split 경계를 넘는 표본은 purge한다.
- embargo는 관습적으로 고정하지 않고 검증 구조·horizon과 함께 version 관리한다.
- walk-forward test window가 겹치면 운영 성과에는 날짜별 당시 모델 예측 하나만 사용한다.

### 4.5 사후 사건

- 후보 선정 시점에 알려지지 않았던 거래정지·상장폐지·정정 정보를 이유로 과거 표본을 제거하지 않는다.
- 미래에 exit 거래가 불가능해진 경우 제거하지 않고 versioned 평가 규칙에 따라 손실, 지연 청산 또는 미평가 상태를 기록한다.

## 5. 전처리·Qlib 하네스

- Qlib export는 adjusted `open`, `high`, `low`, `close`, `volume`, `factor`와 versioned calendar를 포함한다.
- 피처 계산용 가격 이력 범위와 후보 자격 membership 범위를 분리한다.
- 편입 전 이력이 합법적으로 확보되어 있으면 warm-up 계산에 사용하되, 편입 전 날짜에는 후보 자격을 부여하지 않는다.
- warm-up 길이는 고정 60일이 아니라 활성 feature definition의 최대 lookback으로 계산한다.
- 초기 Qlib 모델은 Alpha158 단독으로 검증한다. 추가 특징은 별도 feature definition/version으로 관리한다.
- 기본 label은 `D+5 adjusted close / D+1 adjusted open - 1`의 개별 종목 raw 5거래일 수익률이다.
- SPY는 optional 비교 series이며 label 생성·학습·선정의 필수 입력이 아니다.
- label normalization·횡단면 표준화·rank 변환을 적용하지 않는다. 다른 변환을 실험하면 추론값을 원래 수익률 단위로 복원하고 별도 version으로 기록한다.

## 6. 모델 점수 하네스

- v2 score는 `PREDICTED_5D_RETURN` 회귀값이며 상승 확률이나 신뢰도가 아니다.
- 모델별 raw score, rank, percentile, model version, processor version, feature run을 함께 저장한다.
- 모델 버전 간 raw score 차이를 직접 비교하지 않는다. 필요하면 rank percentile 변화나 별도 calibration을 사용한다.
- calibration 없이 `confidence`나 `probability`라는 이름을 사용하지 않는다.
- 동일 scoring run 안에서 rank는 유일하고 결정적이어야 한다.
- 동점 정렬 기준은 설정에 고정한다. 기본값은 `score DESC, instrument_id ASC`다.

## 7. 후보 선정 하네스

### 7.1 적격성

다음 hard gate는 완화할 수 없다.

- cutoff와 manifest 위반 없음
- 대상 날짜의 universe membership 충족
- 필요한 lookback과 필수 특징 충족
- 기업행위·식별자·가격 품질 통과
- 유효한 model/processor/feature artifact 조합
- blocking 품질 이슈 없음

### 7.2 선택 알고리즘

- 상위 10개를 먼저 자른 뒤 제약을 적용하지 않는다.
- 전체 적격 universe를 결정적 순서로 순회하면서 issuer 중복, sector 제한 등 정책을 적용하고 목표 개수를 채운다.
- sector cap처럼 완화 가능한 soft constraint와 데이터·시점 gate 같은 hard constraint를 설정에서 구분한다.
- 기본 후보 수는 5~10개다. hard gate 통과 종목이 5개 미만이면 `SHORTFALL`로 종료하고 성공 모양의 fallback을 만들지 않는다.
- 초기 정량 경로는 `selection_type=QUANTITATIVE`로 기록한다. 추후 이벤트·재평가 경로를 추가할 때 별도 type과 quota를 사용한다.
- 후보 선정 결과는 분석 예산 또는 매수 수량을 의미하지 않는다.

### 7.3 결과 계약

최소 필드:

- `selection_run_id`
- `selection_type`
- `price_session_date`
- `cutoff_at`
- `generated_at`
- `scoring_run_id`
- `model_version_id`
- `policy_version`
- 후보별 `instrument_id`, 당시 symbol, position, raw score, rank, percentile, 품질 상태, reason codes

후보 run은 단일 transaction으로 저장한다. position·instrument 중복, 점수 누락, rank 불일치가 있으면 전체를 rollback한다.

## 8. 평가 하네스

### 8.1 모델·후보 평가

- 일별 IC, Rank IC, coverage, score dispersion을 기록한다.
- 최종 선정 후보의 Top-5/10 raw return, 양의 raw return 비율, 비용 차감 return과 중첩 cohort drawdown을 주요 지표로 평가한다.
- benchmark excess return은 optional 비교 지표로만 유지한다.
- 후보 정책 비교는 같은 날짜, universe, cutoff, label, 거래비용 가정으로 수행한다.
- reconstruction 결과와 operational replay 결과를 합쳐 하나의 실운영 성과로 표현하지 않는다.

### 8.2 포트폴리오 평가

매일 생성한 후보의 성과와 포트폴리오 성과를 구분한다. 연환산 수익률, drawdown, turnover를 주장하려면 다음을 먼저 versioned policy로 정의해야 한다.

- 자금 배분과 현금 처리
- 동시 보유 한도
- 동일 종목 재선정
- 보유 기간과 중첩 position
- 거래 가능성, 거래비용, 청산 실패

Qlib `TopkDropoutStrategy` 결과를 본 프로젝트의 일일 후보 정책과 동일한 전략으로 간주하지 않는다.

## 9. 실패·재실행·운영

- 데이터, export, feature, model, scoring, selection 상태를 분리한다.
- optional 데이터 실패를 성공으로 숨기지 않고 disabled/stale/missing 상태로 기록한다.
- core gate 실패 시 점수·후보 단계를 실행하지 않는다.
- 오늘 실행 실패 시 과거 후보를 오늘 결과처럼 재사용하지 않는다.
- 승인된 fallback이 있다면 별도 policy/version과 `fallback_used=true`를 기록한다.
- 동일 idempotency key와 동일 payload는 재사용하고, 같은 key의 다른 payload는 충돌로 실패한다.
- 로그에 secret, token, password, 원문 payload를 기록하지 않는다.
- SKU 하향, 리소스 중지, replica 축소는 비용 절감 목적이라도 실행 전에 사용자 승인을 받는다.
- PostgreSQL, MySQL, Candidate App Service, Portal App Service, TradingAgents,
  orchestrator는 항상 실행 상태를 유지하는 운영 리소스다.

## 10. 필수 검증

변경 범위에 따라 최소한 다음을 검증한다.

- 원본·revision·observation 중복 방지
- cutoff 이후 데이터와 manifest 밖 snapshot 차단
- split 전후 가격·거래량 연속성과 factor lineage
- 거래일·결측·instrument span
- processor train-only fit과 feature dimension
- label entry/exit session, purge, benchmark optionality
- scoring rank·percentile 결정성
- 후보 5~10개, hard/soft constraint, `SHORTFALL`, transaction rollback
- 재실행 idempotency와 artifact hash

문서만 바꾸는 경우에도 범위·용어·상태 표현이 다른 기준 문서와 충돌하지 않는지 검색한다.

## 11. 변경 규율

- 새 기능은 어느 단계에 속하는지 먼저 밝힌다: 수집, 전처리, 모델 점수, 후보 선정.
- 범위 밖 기능은 이 저장소에 구현하지 않고 외부 의존 계약만 일반화한다.
- schema·모델·processor·label·selection policy 변경은 version을 올린다.
- 데이터나 모델 품질 제한은 숨기지 않고 결과 metadata와 문서에 기록한다.
- 사용자 요청으로 변경한 코드·설정·스키마·문서는 `CHANGELOG.md`에 한 줄씩 기록한다.
