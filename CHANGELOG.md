# Change Log

사용자 요청에 따른 변경을 한 항목당 한 줄로 기록한다.

형식:

```text
- YYYY-MM-DD | 영역 | 변경 요약
```

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
- 2026-10-09 | Azure | 비밀번호 SFTP로 앱·환경설정을 전송하고 systemd backfill service를 준비하는 bootstrap 도구를 추가했다.
- 2026-10-09 | Dependency | Azure VM password SFTP 배포를 위해 Paramiko와 잠금 의존성을 추가했다.
- 2026-10-09 | Azure | 구독·Korea Central·B4ms·VNet·quota·비용·정책·인터넷 SSH 승인 내용을 반영해 deployment plan을 Ready for Validation으로 확정했다.
- 2026-10-09 | Documentation | README에 Azure backfill VM 구성과 배포 스크립트·임시 비밀 파일 정책을 추가했다.
- 2026-10-09 | Maintenance | Azure upload helper의 import와 line format을 lint 규칙에 맞게 정리했다.
