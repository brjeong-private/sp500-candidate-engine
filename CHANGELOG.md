# Change Log

사용자 요청에 따른 변경을 한 항목당 한 줄로 기록한다.

형식:

```text
- YYYY-MM-DD | 영역 | 변경 요약
```

## 2026-10-11

- 2026-10-11 | Model v2 | 학습 label을 SPY 초과수익에서 개별 종목 D+1 조정 시가~D+5 조정 종가 raw 수익률로 변경하고 v1 artifact를 보존했다.
- 2026-10-11 | Evaluation | Top-5/10 raw·cost-adjusted return, 양의 수익률 비율과 5개 중첩 cohort max drawdown metric을 추가했다.
- 2026-10-11 | Selection | Score를 `PREDICTED_5D_RETURN`으로 저장하고 음수 예측 후보 허용 및 `NON_POSITIVE_PREDICTION` reason을 추가했다.
- 2026-10-11 | Notebook | Label·model·selection config를 수정하며 재실행할 수 있는 v2 학습 notebook과 model change log를 갱신했다.
- 2026-10-11 | Phase 6 | 명시적 date 기반 candidate pipeline과 CLI, daily opt-in 연결, backfill 분리, challenger gate와 drift metric을 구현했다.
- 2026-10-11 | Shadow Replay | 최근 out-of-sample 20 sessions에서 매일 후보 10개, shortfall 0, sector cap 완화 0을 검증했다.
- 2026-10-11 | Documentation | README와 아키텍처·수집·데이터 문서를 현재 Qlib·scoring·selection 구현 상태로 갱신했다.
- 2026-10-11 | Maintenance | plan·phase result·candidate 임시 파일, notebook output, logs와 작업 환경을 Git 제외 대상으로 정리했다.
- 2026-10-11 | Notebook | Python 3.11 `.venv-alpha158` 기반 재현 환경, versioned config, 비대화형 Phase 4~5 notebook과 실행 가이드를 추가했다.
- 2026-10-11 | Schema | Model registry·scoring·daily score와 selection run·candidate·reason migration 014~015를 적용했다.
- 2026-10-11 | Training | Momentum·Ridge·Qlib LightGBM과 purged walk-forward 평가를 구현하고 2026-10-09 데이터에서 shadow 모델을 등록했다.
- 2026-10-11 | Selection | 503개 종목 점수와 rank·percentile을 저장하고 sector·issuer 제약을 적용한 10개 shadow 후보를 생성했다.
- 2026-10-11 | Data | 2026-10-09 production 수집을 완료하고 252-session Qlib export를 생성했다.
- 2026-10-11 | Documentation | Phase 4·5 결과를 ignored `phase-result/` 하위에 기록하고 계획의 완료 상태와 실제 metric을 갱신했다.
- 2026-10-11 | Migration | Azure PostgreSQL에 analytics migration 011~013을 적용하고 schema ledger와 신규 테이블을 검증했다.
- 2026-10-11 | Benchmark | 보존된 Massive raw snapshot에서 2025-11-24 SPY benchmark를 복구하고 재실행 변경 0건을 확인했다.
- 2026-10-11 | Qlib Export | 251 sessions·540 instruments·126,233 rows의 split-adjusted historical export를 생성·영속화하고 동일 hash 재실행을 검증했다.
- 2026-10-11 | Qlib Validation | 실제 1년 artifact에서 Alpha158 126,236행·158차원·Infinity 0을 검증했다.
- 2026-10-11 | Fix | 다중 FULL partition과 cross-dataset DELTA lineage 및 psycopg cursor executemany를 실제 historical export에 맞게 수정했다.
- 2026-10-11 | Documentation | Phase 3 뒤에 Phase 4 진입 전 migration·benchmark·historical export gate와 실행 결과를 추가했다.

## 2026-10-10

- 2026-10-10 | Analytics Phase 1 | Versioned XNYS calendar, split·dividend adjustment, manifest-constrained daily-bar repository와 데이터 기초 테스트를 추가했다.
- 2026-10-10 | Analytics Phase 2 | Qlib export schema, CSV staging, binary provider exporter, artifact hash와 export 품질 gate를 추가했다.
- 2026-10-10 | Analytics Phase 3 | Alpha158 runtime adapter, train-only processor artifact, 5-session SPY 초과수익 label과 feature·label persistence를 추가했다.
- 2026-10-10 | Dependency | Python 3.11/3.12 analytics 환경용 pyqlib·pyarrow·PyYAML optional dependencies를 추가했다.
- 2026-10-10 | Testing | Analytics Phase 1~3 단위·회귀 테스트와 실제 Qlib Alpha158 integration smoke test를 추가했다.
- 2026-10-10 | Documentation | Phase 1~3 진행 단계와 구현·검증 결과를 각각 별도 결과 문서로 기록했다.
- 2026-10-10 | Harness | 프로젝트 범위를 수집·전처리·모델 점수·후보 선정으로 고정하고 데이터 무결성·미래 누수 방지·평가·실패 규칙을 공통 하네스로 추가했다.
- 2026-10-10 | Planning | 후보 선정 계획에 점수 해석, 전체 universe 순회, 시점 재현, 학습 라벨, 후보 평가 관련 검토 의견을 반영하고 TradingAgents 구현 범위를 제거했다.
- 2026-10-10 | Documentation | README의 전체 아키텍처와 수집 파이프라인을 정비하고 데이터 스키마 ER 다이어그램을 추가했으며 데이터 원천 미구현 사유·1년 backfill 통합 결과를 반영하고 Azure Backfill VM 내용을 제거했다.

## 2026-10-09

- 2026-10-09 | Backfill | XNYS 세션 기반 3개월 backfill dry-run 계획과 API 호출량 계산을 추가했다.
- 2026-10-09 | Temporal | Production 수집이 operational 또는 historical reconstruction mode를 명시적으로 전달하도록 변경했다.
- 2026-10-09 | Reference | 변경 없는 ticker identifier가 날짜별로 중복 생성되지 않도록 validity interval 처리를 추가했다.
- 2026-10-09 | Reference | 변경 없는 SEC instrument state가 날짜별로 중복 생성되지 않도록 validity interval 처리를 추가했다.
- 2026-10-09 | Documentation | 3개월 backfill 위험과 실행 전 필수 수정 사항을 임시 데이터 검토 문서에 추가했다.
- 2026-10-09 | Process | 앞으로 모든 사용자 요청 변경을 이 파일에 한 줄씩 기록하도록 저장소 규칙을 추가했다.
- 2026-10-09 | Testing | 3개월 XNYS 65세션과 Massive·Alpha backfill 예산을 검증하는 테스트를 추가했다.
- 2026-10-09 | Documentation | README와 파이프라인 문서에 네트워크를 실행하지 않는 `plan-backfill` 명령을 추가했다.
- 2026-10-09 | Dependency | XNYS 공식 세션 계산을 위해 `exchange-calendars`와 잠금 의존성을 추가했다.
- 2026-10-09 | Backfill | `plan-backfill`의 날짜 필드를 ISO 문자열로 직렬화해 CLI JSON 출력을 수정했다.
- 2026-10-09 | Review | 3개월 backfill 검토 문서에 수정 완료 항목과 남은 실행 blocker를 구분해 기록했다.
- 2026-10-09 | Schema | 일·배치 process run과 날짜별 수집·재처리 상태를 저장하는 migration을 추가했다.
- 2026-10-09 | Logging | 실행 1회당 JSONL 파일 하나를 사용하는 process 진행 로그 경로를 Git 제외 대상으로 추가했다.
- 2026-10-09 | Massive | Backfill이 가격 한 번만 호출할 수 있도록 grouped daily 수집 메서드를 분리했다.
- 2026-10-09 | Backfill | 날짜별 universe·Massive 가격 snapshot과 reconstruction manifest를 멱등 저장하는 repository를 추가했다.
- 2026-10-09 | Process | 실행 상태·heartbeat·날짜별 시도·재처리 queue를 관리하는 process tracker와 실시간 JSONL writer를 추가했다.
- 2026-10-09 | Backfill | 전체 1차 수집 후 실패 날짜 확인과 자동 재처리를 수행하는 Massive 가격 backfill orchestrator를 추가했다.
- 2026-10-09 | Backfill | range action·news를 일별 05:30 ET cutoff로 필터링해 derived snapshot과 manifest에 연결했다.
- 2026-10-09 | Daily | 일일 production 수집을 process run과 실행별 JSONL 로그로 감싸는 runner를 추가했다.
- 2026-10-09 | CLI | 일일 실행, backfill, 기간 재처리, process 상태 조회 명령을 추가했다.
- 2026-10-09 | Progress | process 상태 조회에 날짜별 최신 시도·수집량·실패·재처리 상태를 포함했다.
- 2026-10-09 | Documentation | README와 파이프라인 문서에 일일·batch·기간 재처리·진행 조회 명령과 process 로그 형식을 추가했다.
- 2026-10-09 | Testing | process 실행별 단일 파일 로그와 일일·batch·재처리·상태 CLI 노출 테스트를 추가했다.
- 2026-10-09 | Quality | production과 backfill의 누락 가격 품질 이슈 dataset code를 분리했다.
- 2026-10-09 | Maintenance | batch·collector 코드의 import와 format을 프로젝트 규칙에 맞게 정리했다.
- 2026-10-09 | Fix | Massive grouped daily 메서드와 range collector의 코드 경계를 수정하고 누락된 타입 import를 보완했다.
- 2026-10-09 | Fix | Backfill repository 메서드 경계를 재구성해 price·parent range·derived supplement persistence를 복구했다.
- 2026-10-09 | Transaction | 날짜별 derived supplement와 final manifest 저장을 하나의 DB transaction으로 묶었다.
- 2026-10-09 | Fix | Backfill·수동 재처리 runner가 process 결과를 올바르게 반환하도록 수정했다.
- 2026-10-09 | Maintenance | Batch pipeline import 순서를 lint 규칙에 맞게 정리했다.
- 2026-10-09 | Harness | 일별 cutoff action·news 필터와 동일 payload revision 결정 로직을 순수 함수로 분리했다.
- 2026-10-09 | Testing | 다음 날 05:30 ET cutoff, 미래 action·news 제외, 동일 payload revision 중복 방지 테스트를 추가했다.
- 2026-10-09 | Architecture | Process·parent raw·daily derived snapshot·logical revision·manifest 관계와 중복·미래 누수 불변식을 데이터 아키텍처에 추가했다.
- 2026-10-09 | SEC | SEC filing·fact derived snapshot, logical dedupe, observation, daily manifest persistence를 추가했다.
- 2026-10-09 | Backfill | SEC bulk를 기간당 한 번 다운로드·정규화하고 accepted_at cutoff 이하 filing·fact만 날짜별 snapshot에 연결했다.
- 2026-10-09 | Maintenance | SEC 통합 후 사용하지 않는 backfill repository import를 제거했다.
- 2026-10-09 | Transaction | Parent range ingestion run과 원문 snapshot 저장을 하나의 transaction으로 묶었다.
- 2026-10-09 | Architecture | Fundamental observation과 process run·날짜별 retry 상태 테이블을 데이터 아키텍처 표에 반영했다.
- 2026-10-09 | Documentation | README에 최대 데이터 backfill 포함 범위와 Alpha historical 제외·남은 작업을 갱신했다.
- 2026-10-09 | Review | 임시 검토와 파이프라인 문서를 최대 데이터 backfill 구현 완료·Azure 실행 대기 상태로 갱신했다.
- 2026-10-09 | Architecture | 전체 아키텍처의 SEC·backfill 구현 상태와 남은 최적화 항목을 갱신했다.
- 2026-10-09 | Documentation | 남은 작업에 dataset checkpoint cursor 연결을 명시했다.
- 2026-10-09 | Recovery | 중단 후 5분 이상 RUNNING 상태인 날짜 attempt를 실패·재처리 대기로 복구하도록 추가했다.
- 2026-10-09 | CLI | 수동 재처리 결과에 parent process와 stale attempt 복구 수를 포함했다.
- 2026-10-09 | Provenance | 기간 원문 parent snapshot과 날짜별 derived snapshot의 parent-child lineage persistence를 추가했다.
- 2026-10-09 | Backfill | Parent range snapshot ID를 모든 날짜 수집과 자동 재처리 경로에 전달하도록 연결했다.
- 2026-10-09 | Temporal | News range가 마지막 세션 다음 날 05:30 ET까지 빈틈없이 chunk되도록 수정했다.
- 2026-10-09 | Review | 임시 backfill 검토 문서를 가격 batch·자동 재처리·process 로그 구현 상태로 갱신했다.
- 2026-10-09 | Policy | 미래 누수 방지형 최대 backfill 범위와 일별 05:30 ET cutoff·Alpha historical 제외 정책을 기록했다.
- 2026-10-09 | Documentation | 공식 수집 파이프라인에 range raw와 날짜별 derived snapshot 분리 원칙을 추가했다.
- 2026-10-09 | Backfill | Dry-run 계획의 남은 작업을 현재 구현 상태에 맞게 staging·checkpoint·공식 reference로 갱신했다.
- 2026-10-09 | Deduplication | 날짜별 derived snapshot을 직전 cutoff 이후 delta로 제한해 action·news·filing·fact 관찰 중복을 줄였다.
- 2026-10-09 | Testing | 이전 cutoff 이전 항목과 현재 cutoff 이후 항목이 derived snapshot에서 모두 제외되는 테스트를 추가했다.
- 2026-10-09 | Massive | Backfill용 전체 기간 dividend·split과 주 단위 news pagination collector를 추가했다.
- 2026-10-09 | Temporal | 거래 세션 다음 날 05:30 ET backfill cutoff 계산과 split 이용 가능 시각 규칙을 추가했다.
- 2026-10-09 | Backfill | 날짜별 cutoff로 필터된 Massive action·news derived snapshot과 final manifest persistence를 추가했다.
- 2026-10-09 | Azure | Ubuntu VM 배포와 3개월 backfill 실행을 위한 필수 deployment plan skeleton을 추가했다.
- 2026-10-09 | Azure | 로컬 backfill 구현 승인과 Azure 배포 대기 상태를 deployment plan에 분리해 기록했다.
- 2026-10-09 | Azure | Ubuntu VM·VNet subnet·NSG·public IP를 idempotent하게 생성하고 auto-shutdown schedule 부재를 검증하는 스크립트를 추가했다.
- 2026-10-09 | Azure | AVM 기반 NSG·subnet·Ubuntu B4ms VM·NIC·public IP Bicep 템플릿을 추가했다.
- 2026-10-09 | Azure | VM AVM output contract에 맞춰 managed identity 출력 타입과 public IP 조회 방식을 수정했다.
- 2026-10-09 | Security | VM 비밀번호와 validation parameter를 ignored 임시 파일로 생성하고 현재 사용자 전용 ACL을 적용했다.
- 2026-10-09 | Azure | Azure validation recipe의 core·Docker N/A·policy 체크리스트를 deployment plan에 추가했다.
- 2026-10-09 | Azure | Bicep build·resource-group validate·what-if와 policy 검증을 통과하고 proof를 기록했다.
- 2026-10-09 | Build | Python wheel build와 전체 35개 테스트를 배포 전 최종 검증했다.
- 2026-10-09 | Security | VM managed identity의 Azure RBAC 불필요와 PostgreSQL least-privilege role 후속 생성을 검증 계획에 기록했다.
- 2026-10-09 | Azure | 배포 전 실행한 테스트·lint·Bicep build·validate·what-if·wheel build 명령과 결과를 validation proof에 기록했다.
- 2026-10-09 | Azure | 공식 azure-validate workflow 완료 후 deployment plan 상태를 Validated로 변경했다.
- 2026-10-09 | Repository | 사용자 요청에 따라 `infra/`를 Git 추적 대상에서 제외했다.
- 2026-10-09 | Azure | Korea Central B4ms 용량 부족에 따라 사용자 승인 fallback인 Standard_D4s_v5로 계획과 배포 스크립트를 변경했다.
- 2026-10-09 | Azure | Standard_D4s_v5로 Bicep build·validate·what-if을 재통과하고 plan을 다시 Validated 상태로 변경했다.
- 2026-10-09 | Azure | D4s_v5 용량 부족 후 사용자 승인 fallback인 Standard_D4as_v5로 계획·스크립트·Bicep을 변경했다.
- 2026-10-09 | Azure | Standard_D4as_v5 validate·what-if 재검증 후 plan을 Validated로 확정했다.
- 2026-10-09 | Azure | 비밀번호 SFTP로 앱·환경설정을 전송하고 systemd backfill service를 준비하는 bootstrap 도구를 추가했다.
- 2026-10-09 | Dependency | Azure VM password SFTP 배포를 위해 Paramiko와 잠금 의존성을 추가했다.
- 2026-10-09 | Azure | 구독·Korea Central·B4ms·VNet·quota·비용·정책·인터넷 SSH 승인 내용을 반영해 deployment plan을 Ready for Validation으로 확정했다.
- 2026-10-09 | Documentation | README에 Azure backfill VM 구성과 배포 스크립트·임시 비밀 파일 정책을 추가했다.
- 2026-10-09 | Maintenance | Azure upload helper의 import와 line format을 lint 규칙에 맞게 정리했다.
- 2026-10-10 | Azure | West US 3 전용 VNet·subnet·NSG·D-series VM과 고정 공인 IP 기반 PostgreSQL 방화벽 연결로 배포 계획과 IaC를 전환했다.
- 2026-10-10 | Fix | 공동 제출 SEC 문서의 accession을 CIK와 함께 식별하도록 parser·DB unique key·persistence를 수정했다.
- 2026-10-10 | Observability | 장시간 range download·SEC parse 단계에 60초 heartbeat와 실패·완료 process 로그를 추가했다.
- 2026-10-10 | Data | 2026-07-09~2026-10-08 XNYS 65개 세션 backfill을 실패·재처리 없이 완료하고 미래 누수·중복 revision 0을 검증했다.
- 2026-10-10 | Documentation | 3개월 backfill 실측 bar·SEC 적재량과 provider 원본 결측 3건을 README·데이터 아키텍처·파이프라인 문서에 반영했다.
- 2026-10-10 | Maintenance | 실행별 JSONL process 로그 디렉터리를 Git 추적에서 제외했다.
- 2026-10-10 | Review | 3개월 실행 결과와 Yahoo prototype 대비 Massive historical sample의 분석 적합성을 ignored 임시 검토 파일로 작성했다.
- 2026-10-10 | Data | 2026-04-09~2026-07-08의 62개 XNYS 세션을 추가 적재해 총 127거래일·63,878 bars의 6개월 데이터를 확보했다.
- 2026-10-10 | Documentation | 6개월 통합 bar·action·news·SEC 적재량과 무결성 검증 결과를 README·아키텍처·임시 실행 결과에 반영했다.
- 2026-10-10 | Architecture | Qlib 분석 적합성 지표·현재 historical schema·목표 export 계약·readiness gate를 별도 문서로 작성했다.
- 2026-10-10 | Fix | 6개월 action 조회가 100페이지를 넘지 않도록 Massive dividends·splits를 비중첩 31일 chunk로 수집하게 수정했다.
- 2026-10-10 | Fix | cutoff 직전 Wikipedia revision에 constituents 표가 없으면 더 오래된 유효 revision을 선택하도록 미래 누수 없는 fallback을 추가했다.
- 2026-10-10 | Data | 1년 raw snapshot에서 Massive bar 125,730건의 VWAP·조정 상태와 SPY 250거래일 benchmark를 API 재호출 없이 revision 적재했다.
- 2026-10-10 | Pipeline | 신규 일일·backfill이 VWAP, 가격·거래량 조정 상태, Massive 요청 옵션과 `PRICE_RETURN` benchmark를 보존하도록 확장했다.
- 2026-10-10 | Documentation | 데이터 수집 보완 10개 항목의 반영 여부·제한과 1년 변경분 재처리·멱등 검증 결과를 기록했다.
- 2026-10-10 | Data | 2025-10-09~2026-04-08 parent run 123일과 manual retry 1일을 완료해 총 251거래일·126,233 logical bars를 확보했다.
- 2026-10-10 | Review | Qlib readiness 문서를 1년 실측 coverage·VWAP·adjustment·benchmark·outlier·temporal integrity 지표로 갱신했다.
