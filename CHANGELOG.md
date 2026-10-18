# Change Log

- 2026-10-18 | Historical Source Lineage Gate | 승인된 재구성의 read-only 재귀 검토에서 과거 derived split의 raw 부모가 cutoff 이후임을 확인해 세 anchor 학습 전 중단하고, 부모 유형 설명·늦은 부모 차단 회귀 검증과 generic daily freeze의 미래 입력 전체 rollback 경계를 보강했으며 안전 검사는 완화하지 않았다.
- 2026-10-18 | Historical Model Reconstruction | 기존 snapshot의 명시적 rich manifest 고정·격리 context/export·실제 생성 시각·학습 라벨 성숙 및 processor train-only 검증을 재사용 학습 CLI에 추가하고 MEDIUM_20D SHADOW artifact와 해시 결합 증적만 생성하며 정규 승격·활성 모델·과거 weekly-v1 run은 변경하지 않는다.
- 2026-10-18 | Historical Training Runbook | 9월30일~10월14일 신호의 직전 주말 anchor·입력 고정/학습 명령·독립 Quant artifact override 검증·운영 Job 기본 실행 금지와 미실행/미배포 전제를 모델 전용 문서에 기록했다.
- 2026-10-18 | Full Application Release | main의 7f12171 전체 코드를 Backend·immutable 학습 이미지·Function에 배포해 20D 전용 주간 정책·성능 기준 임시 비강제·종료 실행 재시작 차단을 반영하고 기존 후보·근거·운영 설정·B2·private 네트워크를 보존했으며 실제 재학습·승격은 실행하지 않았다.
- 2026-10-18 | Weekly Deployment Record | 공통 하네스·주간 설계·오케스트레이터 가이드·W42 후속 문서의 미배포 상태를 실제 배포 결과로 갱신하고 배포 ID·image digest·비학습 정책 검증과 신규 재학습 E2E 미실행 경계를 기록했다.
- 2026-10-18 | Repository Release Preparation | 사용자 승인에 따라 저장소 전체 변경과 후속 문서를 함께 커밋·푸시하고 동일 코드의 Backend·학습 Job·오케스트레이터 배포를 준비했으며 비밀값·실행 데이터와 기존 리소스 SKU·네트워크 정책은 변경 대상에서 제외했다.
- 2026-10-18 | Weekly 20D Only | 신규 주말 Durable 입력·자동 예약·기본 주간 접수를 MEDIUM_20D로 한정하고 기존 두 목적 history·v1 run 호환과 일일 Fusion을 보존했으며 배포하지 않았다.
- 2026-10-18 | Temporary Performance Gate Suspension | 사용자 확인에 따라 별도 v2 정책에서 다음 지시까지 네 성능 메트릭의 절대·상대 기준만 비강제하고 실제 판정·enforced 증적·정책 알림을 기록하며 데이터·finite 지표·artifact·활성화 검사는 유지했다.
- 2026-10-18 | W42 Promotion Follow-up | 운영의 주간 6개 승격 결정에서 미달 7항목의 정확한 값·기준·차이·run/model ID와 재검증·복구 절차를 별도 문서에 기록하고 최신 실행과 주간 전체의 미달 범위를 구분했다.
- 2026-10-18 | Period Search Reader Production | 승인된 기간검색 근거 조회 호환 수정만 Candidate Backend에 단일 배포해 10월15·16일 각 20개 설명의 RECORDED·v2 목록 정상 반환과 기존 후보·운영 설정·두 App Service B2 보존을 확인하고 ER 문서에 반영했으며 다른 세션의 진행 중 변경·주간 오케스트레이터는 배포하지 않았다.
- 2026-10-18 | Data Storage Guide | 매니페스트·스냅샷·실행 컨텍스트를 쉬운 비유로 설명하고 기본 수집 원본·정규화 DB·LLM 검색 증적·승인 입력·평가 결과의 저장 위치와 DB 미적재 시험·운영 기본 정책의 차이를 별도 문서로 정리했다.
- 2026-10-18 | Parallel DB Evidence | 동일 read-only PostgreSQL snapshot의 날짜별 독립 DB worker 조회와 event loop 밖 입력 준비를 추가하고 기존 packet 순서·시점·screening·cache lineage 검증을 유지했다.
- 2026-10-18 | Parallel Backfill and Search Retry | 다중 날짜 backfill 기본 병렬도 2·검색 동시도 3과 고정 context LLM CLI를 추가하고 수집 DB 반영의 날짜순 lineage·날짜 실패 격리·공유 quota 요청별 정산·일시적 검색 오류 재시도·안전한 실패 감사·동일 service의 완료 종목 재사용을 구현했다.
- 2026-10-18 | User-managed DB SKU | DB SKU·용량을 사용자 관리로 고정하고 별도 명시적 승인 없는 상향·하향·변경을 금지했으며 이번 작업에서 리소스 크기와 운영 설정은 변경하지 않았다.
- 2026-10-18 | October 15-16 Refresh Completion | 두 날짜 신규 LLM·Fusion 후보와 외부 리포트 40건의 저장 완료 후 지정된 기존 결과·리포트만 정리하고 수집·정량 결과 불변 및 immutable trigger 복원을 확인했다.
- 2026-10-18 | Period Search Explanation API | 기존 기간검색 증적 호환 수정을 바탕으로 v2 API의 근거·출처·검증 정보 반환과 미래일·당일 시각 불명·미지원 방식 차단 및 v1 후보 계약 보존을 회귀 검증했으며 배포하지 않았다.
- 2026-10-18 | Collection to Candidate Database ER | 후보 DB 문서에 원본 파일·정규화/관찰 연결·고정 입력·전처리·특징/라벨·모델/결과의 저장 흐름과 ER, 검색 증적 저장 위치 및 근거 기록 상태·배포 호환성을 보강했다.
- 2026-10-18 | Search Enrichment Export | 10월15일 62종목·137개와 10월16일 65종목·142개의 실제 반영 검색 발췌·출처·검사 기록 및 미보강 사유를 성공 run 기준 날짜별 Git 제외 파일로 내보내고 실제 평가 호출 지연과 외부 리포트 진행 상태를 구분했다.
- 2026-10-18 | Weekly Terminal Execution Gate | 같은 주의 종료된 주간 실행을 타이머가 다시 시작하지 않도록 차단해 중복 업데이트·메일을 방지하고 입력 manifest 미준비 재확인·다음 주 실행·일일 Fusion·수동 실행을 유지했으며 배포는 하지 않았다.
- 2026-10-18 | Infrastructure SKU Preservation | Backend 배포 템플릿이 기존 App Service 플랜만 참조하도록 변경하고 SKU·인스턴스 수 덮어쓰기 방지 회귀 검증을 추가했다.
- 2026-10-18 | Operations B2 Protection | Portal·Candidate의 승인 SKU B2 유지와 B1 변경 금지를 공통 하네스·배포 문서에 명시하고 Portal B1을 B2로 복원했으며 기존 Candidate B2는 변경하지 않았다.
- 2026-10-18 | External Citation Projection | 같은 검증 문서·평가 항목의 서로 다른 해석은 동일 증적 확인 후 bounded 설명으로 모으고 DB·검색 출처 층을 구분하며 동일 사유 중복·충돌 증적은 계속 거부하도록 정합화했다.
- 2026-10-18 | Period Search Fusion Witness | 기간검색 뉴스 게시일과 연결 SEC 공시 접수일을 별도 증적으로 구분해 Fusion 설명을 투영하고 기간검색 cutoff 상한·일자 정밀도·원본 공시 연결 검증과 기존 SEC 원문 검증을 유지했다.
- 2026-10-18 | LLM Citation Repair | 실제 재처리에서 확인한 산업 점수의 인용 누락에 대해 재질의에 오류 종목·항목과 10개 인용 한도 내 점수별 근거 배분을 명시하고 기존 근거·결측·최소 지원 항목 검증을 유지했다.
- 2026-10-18 | Optional LLM Search | 별도 v6 정책에서 검색·Python 검증을 먼저 수행하고 승인 자료만 보강하며 승인 자료가 없으면 제외 사유·감사 증적을 저장한 뒤 DB 비가격 자료의 독립 LLM 평가와 Fusion을 계속하도록 분리했다.
- 2026-10-18 | LLM IR Publication Date | 두 날짜 재처리 중 확인한 IR 본문의 명시 게시일 누락을 보완하고 당일 시각·미래일·모호한 게시일 차단을 유지했으며 기간검색 캐시를 날짜 파서 버전으로 분리했다.
- 2026-10-18 | Rank IC Guide | 순위 예측력과 수익률의 차이·확인된 모델 지표·승격 조건을 쉬운 예시로 설명하고 독립 재계산·동일 조건 비교·별도 학습 실험과 미사용 테스트의 개선 원칙을 별도 문서로 정리했다.
- 2026-10-17 | VLO Period Search Report | 승인 리소스에서 기간 필터의 요청/응답 echo와 실제 검색 후보를 확인하고 원문 version proof 미노출로 자동 평가 사용 0건임을 별도 문서·Git 제외 증적으로 남겼다.
- 2026-10-17 | Period-filtered LLM Search | 승인된 Bing Grounding 리소스·프로젝트 연결을 생성하고 freshness 날짜 범위를 실제 도구 설정에 전달하는 별도 v5 검색 정책을 추가했다.
- 2026-10-17 | LLM NY Day Boundary | LLM에 한해 뉴욕 전일 이전 공개/버전 자료는 일자만 허용하고 당일은 05:30 이전의 명확한 시각을 요구하며 수집·정량 fence는 유지했다.
- 2026-10-18 | Local-only Checklists | 모든 깊이의 checklist·체크리스트 Markdown 문서를 Git 제외하고 기존 점검표는 로컬 보존하며 공유 README의 링크를 로컬 문서 안내로 변경했다.
- 2026-10-17 | MEDIUM Duplicate Report Cleanup | 10월 1~7일의 현재 후보 run에 연결된 5일·50개 분석을 보존하고 이전 MEDIUM_20D 분석 5회·작업 50건·이벤트 500건·dispatch 50건·Blob 50개를 삭제했으며 후보 원본·다른 분석·나머지 Blob 398개·기존 네트워크 차단을 보존했다.
- 2026-10-17 | Daily Fusion Only | 공통 하네스와 실행 가이드에 정규 데일리 Fusion 전용 정책을 고정하고 신규 타이머의 Fusion 비활성·누락 차단과 수동·주간·기존 replay 보존을 구현했으며 차단 코드 미배포를 명시했다.
- 2026-10-17 | October Daily Fusion Checklist | 운영 Fusion·LLM 활성 설정을 읽기 전용 재확인하고 기존 일정에 따른 10/19 비거래일 skip·10/20 실제 Fusion의 원천 lineage·최종 20개·전량 ACK 점검표와 사후 기록 양식을 추가했다.
- 2026-10-17 | Pipeline Architecture Refresh | 공통 context 이후 독립 Quant·LLM 병렬 실행과 부분 성공 보존·고정 Fusion·전량 ACK 흐름을 현재 운영 ON/기본 OFF 상태에 맞춰 갱신했다.
- 2026-10-17 | LLM Architecture Refresh | 운영 DB-only v2와 로컬 native 검색 v4를 구분하고 전체 출처·공개 시점·원문 버전 admission 및 새 평가 대화 격리·감사용 모델 metadata 계약을 정리했다.
- 2026-10-17 | Orchestrator Architecture Refresh | 배포된 주간 전용 메일·최대 네 차례 요약·공통 메일 OFF와 terminal parent 재진입 시 DB acceptance로 중복을 막는 구조를 문서에 반영했다.
- 2026-10-17 | Main and Data Documentation | 메인 README·결과/API 문서·ER 색인을 연결하고 원본 선정 근거와 과거 snapshot·미배포 v2 API를 구분하며 SHORT 데이터 정리와 실행 기능 보존을 명시했다.
- 2026-10-17 | Source-based News Admission | 모델 이름·버전·snapshot 날짜를 뉴스 승인/차단 조건에서 제거하고 nullable 감사 metadata로 분리했으며 자료 공개일·원문 버전·전체 출처·평가 격리 검증은 유지했다.
- 2026-10-17 | Weekly Model Email | 주간 전용 발송 스위치·수신처를 분리하고 신규 주간 실행의 시작·모델별 결과·최종 요약 및 발송 실패 상태를 기록하며 기존 Durable 입력의 replay를 보존했다.
- 2026-10-17 | Weekly Email Production | 오케스트레이터만 FC1에 배포해 승인된 단일 수신처의 주간 알림을 활성화하고 파이프라인·리소스 가디언 메일은 비활성으로 유지했으며 운영 설정·host·기존 ACS 권한을 확인했다.
- 2026-10-17 | Native Search Validation | 전체 회귀 616건·관련 Ruff/타입 검사와 기존 PostgreSQL 호환을 검증하고 실제 native 검색의 시점 증거 미충족을 평가 호출 없이 차단한 증적을 보존했다.
- 2026-10-17 | SHORT Candidate Cleanup | 운영 DB의 전체 기간 SHORT_5D 선정 run 10개·후보 100건·선정 근거 200건을 삭제하고 다른 모델 후보·점수·원천을 보존했다.
- 2026-10-17 | SHORT Report Cleanup | SHORT_5D 분석 3회·작업 30건·이벤트 300건·dispatch 30건과 연결 Blob 리포트 30개를 삭제하고 다른 리포트 448개 및 기존 네트워크 차단 설정을 보존했다.
- 2026-10-17 | Native LLM Search Replacement | 서버 SEC 추가 다운로드·HTML 파싱 보강과 해당 v3 정책을 제거하고 Azure Responses native web_search를 사용하는 별도 v4 정책으로 대체했다.
- 2026-10-17 | Search Quarantine Harness | 전체 consulted sources·고정 원문 버전·공개 시점·검색/평가 모델 snapshot을 검증하고 미래/미확인 검색 전체 폐기와 새 평가 대화 격리를 강제했다.
- 2026-10-17 | Search Privacy and Evidence | 검색에는 공개 회사 metadata만 전달하며 tool 응답·admission 결정·context/policy hash를 파일로 보존하고 승인된 발췌만 기존 JSONB/설명 v3에 연결했다.
- 2026-10-17 | Candidate Database ER | 후보 관련 공통 입력·정량·LLM·Fusion 테이블의 역할·키·관계·근거 저장 위치와 ER 다이어그램을 별도 문서로 정리했다.
- 2026-10-17 | External Explanation Witness | 검증 외부 인용의 원문/facts hash·공개/취득 시각·artifact를 candidate-explanation-v2로 투영하고 기존 v1 snapshot·API handoff 호환을 유지했다.
- 2026-10-17 | VLO Selection API Verification | 10월16일 VLO의 실제 원천 run을 읽기 전용 조회해 정량·LLM 근거와 RRF 정합성을 확인하고 운영 통합 설명 endpoint 미노출·검증 한계를 별도 문서와 로컬 결과 JSON에 기록했다.
- 2026-10-17 | Verified External Scoring Contract | 기존 v2를 유지하며 고정 SEC 공시 원문의 검증된 factual projection을 점수에 반영하는 별도 v3 정책·출처 계층·원문 hash·artifact 재현 계약을 추가했다.
- 2026-10-17 | External Enrichment Harness | 공통 및 LLM 전용 하네스에 공개·관찰·revision cutoff와 모델 기억·최신 웹·미래 결과 금지를 명시하고 원천 접근·시점·artifact 실패의 우회 성공을 금지했다.
- 2026-10-17 | Enrichment Architecture | 데이터·LLM 아키텍처에 DB 입력·검증 외부 보강·LLM 해석·미확보 정보를 분리하고 원문 파일과 기존 JSONB 증적·정책 선택·운영 미활성 경계를 명시했다.
- 2026-10-17 | Foundry Resource Cleanup | 승인된 추가 Foundry 두 리소스와 하위 프로젝트를 영구 제거 없이 소프트 삭제하고 기존 프로젝트 모델·인프라를 보존했으며 삭제 직후 쿼터 반환 미반영 상태를 확인했다.
- 2026-10-17 | Korean Event LLM Prompt | 이벤트 평가·재질의를 한글로 바꾸고 자연어 응답의 한국어 검증과 한글 항목 요약을 추가하며 prompt·요약 version을 갱신해 영문 cache와 분리했다.
- 2026-10-17 | VLO Read-only OpenAI Probe | 10월16일 VLO의 고정 packet을 읽기 전용으로 검증해 새 한글 prompt로 실제 단건 호출하고 요청·응답을 Git 제외 임시 파일에 보존했으며 DB 적재는 하지 않았다.
- 2026-10-17 | Explanation and Historical Harness Validation | 회귀 577건·Ruff·관련 모듈 타입 검사·기존 진단 9건 불변과 격리 PostgreSQL의 설명 조회·JSONB 수치 정규화 hash·미래 수정본 차단·rollback·v1 handoff 호환을 검증했다.
- 2026-10-17 | Historical News Revisions | 변경된 이벤트 payload의 이용 가능 시각을 관찰 이전으로 소급하지 않고 과거 소급 기록된 후속 revision도 분석 cutoff 이후 관찰본이면 차단했다.
- 2026-10-17 | Historical LLM Cutoff Harness | 사용자 확정 run cutoff를 새 입력·screening lineage·캐시·모델 호출 전·Fusion 근거에 강제하고 재구성의 늦은 수집과 미래 공개 정보를 구분하며 하네스 identity를 고정했다.
- 2026-10-17 | Candidate Explanation Snapshots | 추가 DDL·LLM 호출 없이 기존 rationale·scored citation과 Quant 기준·RRF 기여를 bounded Fusion JSONB에 원자적으로 저장하고 계약·설정·입출력 hash를 provenance에 보존했다.
- 2026-10-17 | Versioned Explanation API | 정확한 Fusion run의 v2 typed 설명 조회·과거 NOT_RECORDED·무결성 실패를 구현하고 v1 필드 allowlist와 기존 handoff hash·ACK 계약을 유지했다.
- 2026-10-17 | Explanation Contract Documentation | 공통 하네스·결과 샘플·메인 및 Backend 문서를 실제 저장·조회·실패 계약과 미배포·포털 별도 범위에 맞춰 갱신했다.
- 2026-10-17 | Model LLM Fusion README | 메인 README의 후보 선정 설명을 모델·LLM·Fusion 세 항목으로 재구성하고 이벤트 평가 가중치·RRF 산식·통합 제약·결과 저장 및 외부 전달 경계를 명시했다.
- 2026-10-17 | Local-only Plans | 모든 깊이의 plan.md·*.plan.md·*-plan.md·*_plan.md·plan 접두 문서와 plans 폴더를 Git 제외하고 기존 추적 계획은 로컬 보존 상태로 해제했다.
- 2026-10-17 | Main Documentation Refresh | 메인 README를 event v2·정확한 Fusion·독립 stage·운영 ON/코드 기본 OFF·24개 migration과 검증된 API/CLI 계약에 맞추고 문서 색인을 갱신했다.
- 2026-10-17 | Result Schema Documentation | 결과 샘플의 cutoff·선정 policy version을 현재 계약과 맞추고 독립 stage 제어 ID·실제 Fusion ID 구분 및 미구현 설명 설계 경계를 명시했다.
- 2026-10-17 | Daily Pipeline Error Runbook | 오늘18:30 KST·10월16일 세션의 정기 실행과 단계별 오류·고정 run/context·안전한 조회·재시도·운영 배포 증거를 별도 공유 문서로 작성했다.
- 2026-10-17 | Documentation Consistency | 정량·LLM·통합 상세 설계의 로컬 plan 링크를 공유 운영 문서로 바꾸고 노트북·모델 변경 이력·초기 지침의 현재 운영과 역사적 기록을 구분했다.
- 2026-10-17 | Selection Explanation Design | 파이프라인 분리와 독립적으로 기존 LLM rationale·항목별 근거와 Fusion JSONB를 재사용하는 분석일별 선정 근거 저장·조회 및 포털 연동 설계를 스키마 샘플에 추가했다.
- 2026-10-17 | Independent Pipeline Design | 기존 일일 흐름·선정 정책 보존을 전제로 정량·LLM·Fusion별 독립 API/CLI·상태·고정 계약·재시도와 파라미터 설계 문서를 구현 전에 작성했다.
- 2026-10-17 | Unified Pipeline Architecture | 전체 아키텍처에 수집·공통 manifest·독립 후보 경로·주간 모델·Fusion·기존 외부 전달의 통합과 경계를 정리했다.
- 2026-10-17 | Independent Stage Ledger | migration 024에 단계별 수락·claim·성공·SHORTFALL·실패·retry lineage와 고정 계약 hash·활성 입력 고유 제약·terminal 보호를 추가했다.
- 2026-10-17 | Independent Stage API | 서버 인증과 멱등 키를 요구하는 단독 Quant·LLM·Fusion 실행·상태·재시도 API를 추가하고 API 재시작 중단과 CLI 소유 실행을 구분했다.
- 2026-10-17 | Independent Stage CLI | run-stage·show-stage·retry-stage를 공통 실행 service에 연결하고 레거시 학습 CLI와 단독 고정 추론을 분리했다.
- 2026-10-17 | Pinned Standalone Quant | 독립 정량 수락 시 artifact·설정 계약을 고정하고 동일 MEDIUM 결과 재사용과 context별 export 잠금·SHORT 호환·추론 전용 동작을 구현했다.
- 2026-10-17 | Isolated Standalone Candidates | LLM-only는 Quant·Qlib·Fusion gate와 분리하고 Fusion-only는 명시 원천 두 run만 처리하며 외부 전달을 시작하지 않도록 검증했다.
- 2026-10-17 | Standalone Execution Guides | 공통 하네스·README·Backend 가이드에 독립 실행 입력·응답 ID·인증·재시도·설정 변경·중단 복구와 migration 순서를 추가했다.
- 2026-10-17 | Independent Stage Validation | 전체 테스트 533건·신규 4개 stage 모듈 타입 검사·Ruff와 격리 PostgreSQL의 24개 migration·독립 Fusion·멱등 재시도·terminal 보호 검증을 통과했다.
- 2026-10-17 | Independent Stage Production | 운영 migration 024·최소 앱 권한과 Backend 배포를 완료하고 독립 Quant·LLM·Fusion API의 성공20개 재사용·멱등성·인증·성공 retry차단 및 새 LLM 호출0건을 검증했다.
- 2026-10-17 | Independent CLI Execution Tests | 실제 run-stage·show-stage·retry-stage 진입점이 공통 실행 service와 CLI 소유 상태를 사용하고 레거시 학습이나 다른 단계를 실행하지 않도록 회귀 검증했다.
- 2026-10-17 | Candidate Result Schema Sample | 현재 Quant·이벤트 LLM·Fusion 후보 API의 가상 스키마 샘플과 점수·항목별 근거·RRF 산식·DB 및 API 노출 경계를 별도 문서로 정리했다.
- 2026-10-17 | Split Pipeline Design | 정량·LLM을 별도 Job·권한·복구 단위로 분리하고 공통 입력 고정 후 병렬 실행·독립 Fusion·단계별 재시도·안전한 전환을 수행하는 별도 변경 계획을 작성했다.
- 2026-10-17 | Production Fusion Handoff | 고정 Fusion 성공 20개를 재사용해 활성화 입력 누락으로 건너뛴 전달을 재실행하고 포털 분석 46의 20개 전량 접수·실제 워커 실행을 확인했다.
- 2026-10-17 | Production Deployment Evidence | 운영 migration·원천 run/context·보호 lock·복구 백업·전달 재개와 로컬 시간 기록 경계를 배포 기록에 반영했다.
- 2026-10-17 | Production Hybrid Rollout | 사용자 승인으로 Candidate·Durable·별도 Portal 수신부와 PostgreSQL 022/023·MySQL 004를 운영 적용하고 최소 권한·보호 lock을 유지했다.
- 2026-10-17 | Production Recovery Backup | 10월 15일 기존 분석 1건·작업 10개·보고서 10개를 비공개 저장소에서 hash 검증해 백업했으며 성공 Fusion20 검증 전 삭제는 차단했다.
- 2026-10-17 | Portal Single Response | UI 자산을 변경하지 않고 별도 Portal PR의 MEDIUM 조회를 20개 단일 응답·고정 run·전량 검증으로 수정하고 백엔드 전용 layer로 배포했다.
- 2026-10-17 | Production Evidence Manifest | 운영 LISTED 상태를 정식 적격 상태로 인식하고 상태·공시·재무·이벤트 observation 원천 의존성을 cutoff 제한의 versioned preselection manifest에 고정했다.
- 2026-10-17 | Bounded Event Packets | 대형 운영 evidence를 문자 한도 안에서 결정적으로 오래된 항목부터 축소하고 잘림·결측·개수와 실제 제공된 근거 링크를 일치시켰다.
- 2026-10-17 | LLM Citation Validation | 종목별 구조화 schema로 다른 종목 근거 인용을 차단하고 기존 호출 예산 안에서 의미 검증 재시도를 감사·실패와 구분해 기록했다.
- 2026-10-17 | Frozen Input Retry Cache | 동일 context·정책의 immutable packet·screening을 hash·manifest·cutoff 검증 후 재사용하고 canonical lineage identity v3와 원천 run 참조를 보존했다.
- 2026-10-17 | Replay Cache Timing | 재구성 cache는 manifest에 고정된 원천 row의 공개 시각을 검증하고 늦은 재관찰 container와 구분하며 운영 재현은 snapshot·관찰 시각까지 엄격히 차단한다.
- 2026-10-17 | Unscored Evidence Notes | 유효한 동일 종목 근거로 미평가 항목의 한계를 설명한 인용은 보존하되 점수·지원 항목 수·가중치에는 포함하지 않으며 기존 raw 응답도 재검증 후에만 재사용한다.
- 2026-10-17 | Validated Repair Cache | 의미 검증 재시도에서는 검증 성공 cache를 우선·전용으로 조회해 동일한 실패 응답의 반복 재생을 막고 필요할 때만 제한된 새 모델 호출을 수행한다.
- 2026-10-16 | Event LLM Runtime | 기존 v1을 보존하며 7일 이벤트·90/10 운영 대조 표본·비가격 packet·최소 3개 근거 항목 가중치 재정규화 정책 v2를 구현했다.
- 2026-10-16 | LLM Retry and Audit | RPM/TPM·재시도 예산·원문 응답 저장·context 제한 배치 재사용과 동시 평가 잠금 및 결측·coverage 감사를 추가했다.
- 2026-10-16 | Exact Fusion Selection | MEDIUM 전용 k=10 유리수 RRF·동일 instrument 합산·issuer 중복 제거·섹터 2/4·union 한정 SHORTFALL을 구현했다.
- 2026-10-16 | Fusion Persistence | migration 023에 append-only Fusion run·candidate·audit와 LLM 확장 및 원천 run·manifest·정책 hash 검증·원자 저장·동시 멱등성을 추가했다.
- 2026-10-16 | Top20 Migration Compatibility | migration 022 재실행·구 제약 잔존을 수정하고 MEDIUM 성공 20개·SHORT 레거시 성공 5~10개 및 선정 수량 상하한을 구분해 보존했다.
- 2026-10-16 | Manifest Evidence Lineage | 공시 조회의 중복 snapshot 컬럼을 해소하고 가격 근거를 manifest observation snapshot에 연결하며 LLM 입력 identity에 lineage hash를 포함했다.
- 2026-10-16 | Fusion API | 기존 Quant·LLM 조회를 유지하며 Fusion 목록·run·전달 envelope API와 LLM 항목별 근거·결측·screening 조회를 추가했다.
- 2026-10-16 | Hybrid Daily Control Plane | 독립 병렬 branch 뒤 Fusion을 연결하고 성공 Quant 재사용·원천 run 고정·단계별 결과와 실패 보존을 구현했다.
- 2026-10-16 | Fusion Top20 Handoff | 기존 오케스트레이터에 기본 비활성 versioned 20개 전량 전달·엄격한 ACK·멱등 재시도·미완료 전달 재개를 추가하고 SHORT 분석 경로를 보존했다.
- 2026-10-16 | Hybrid Safe Configuration | Backend·Durable IaC와 설정 예제에 legacy LLM 기본 정책 및 기본 비활성 Fusion·외부 전달 플래그와 계약 선택을 추가했다.
- 2026-10-16 | Hybrid Runtime Documentation | README·Backend·오케스트레이터·구현 지침에 구현된 기본 비활성 경로와 운영 활성화·외부 수신 검증 경계를 구분하고 신규 API·policy·ACK 계약을 갱신했다.
- 2026-10-16 | Hybrid Architecture Alignment | 모델·수집·데이터·전체·오케스트레이터 설계를 구현된 이벤트 v2·MEDIUM Fusion·기본 비활성 전달과 맞추고 과거 운영 검증 기록은 보존했다.
- 2026-10-16 | Hybrid Verification | 전체 테스트 492건·Ruff·신규 22개 모듈 타입 검사·23개 migration 구문 및 격리 PostgreSQL-WASM의 rollback·배치 재사용·멱등 충돌·전량 ACK·레거시 수량 검증을 통과했고 운영 DB·외부 API는 호출하지 않았다.
- 2026-10-16 | Hybrid Infrastructure Validation | Backend·Durable Bicep의 로컬 컴파일을 통과했고 기존 App Service API 버전 타입 경고 2건을 유지했으며 운영 배포·기능 활성화는 수행하지 않았다.

- 2026-10-16 | README Horizontal Architecture | 메인 README의 후보 파이프라인·모델 아키텍처 다이어그램을 좌에서 우로 흐르는 가로 방향으로 변경했다.
- 2026-10-16 | Fusion Ranking Contract | 사용자 정의로 MEDIUM_20D 전용·k=10·목록 순위·동일 instrument 합산·issuer별 최고 후보·섹터 2/4와 union 한정 SHORTFALL 계약을 명시했다.
- 2026-10-16 | Event LLM Screening Contract | 기존 LLM과 분리된 신규 정책에 최근 7일 유형별 1점·실적 전후 7일·이벤트 90개와 결정적 운영 대조 10개 기준을 정의했다.
- 2026-10-16 | LLM Evidence Scoring Contract | 신규 비가격 LLM 평가에 최소 3개 근거 항목·가중치 재정규화·null 결측·품질 및 불확실성과 주관적 위험 임계값 미도입을 명시했다.
- 2026-10-16 | Fusion Provenance Contract | 원천 selection run과 공통 manifest identity·정확한 RRF 순위·원자 저장·재실행 및 동시 멱등성 요구를 구현 지침에 추가했다.
- 2026-10-16 | Fusion External Handoff Contract | 성공한 Fusion 20개 전량의 versioned 외부 전송·수신 identity 검증·재시도와 SHORT 레거시 보존 및 외부 분석 제외 경계를 정의했다.
- 2026-10-16 | Fusion Harness Scope | 공통 하네스에 신규 이벤트 LLM·MEDIUM Fusion 범위와 Top 20 union 예외의 이유·영향·필수 검증을 정식 반영했다.

- 2026-10-16 | README Model Architecture | 메인 README에 시점 고정·조정가격·Alpha158·주간 학습과 승격·일일 고정 추론·Top 20 선정·독립 LLM 및 후속 RRF의 모델 아키텍처를 명시했다.

- 2026-10-16 | README Full Architecture | 메인 README에 후보 엔진·Portal·TradingAgents agent 계층·외부 데이터·MySQL·보고서 Blob·UI를 포함한 전체 시스템 아키텍처를 복원하고 기존 후보 파이프라인 상세도를 유지했다.

- 2026-10-16 | Final Candidate Handoff Docs | TradingAgents 최종 전달 목표를 기존 5~10개에서 20개로 통일하고 재축소 금지·SHORT 레거시 보존·현재 MEDIUM 전달 차단을 구분했다.
- 2026-10-16 | RRF Design Contract | RRF 설계서에 후보 수 변경 이력과 병렬 중간 Top 20·후속 최종 Top 20 전달 계약을 명시하고 현행 LLM과 제안 screening·schema를 구분했다.
- 2026-10-16 | Main README Refresh | 메인 README 전체를 재구성해 현재 상태 섹션을 제거하고 범위·20개 계약·독립 파이프라인·재학습·API·설치·배포 경계를 갱신했다.
- 2026-10-16 | Pipeline Architecture Docs | 전체·모델·수집·데이터·오케스트레이터 설계와 다이어그램을 MEDIUM Top 20·선택 LLM 병렬 구조 및 미구현 RRF 경계에 맞췄다.
- 2026-10-16 | Candidate Consumer Guides | Backend·Portal 계약 예제·구현 지시서·노트북·모델 문서와 배포 가이드의 20개 기준을 맞추고 과거 10개 검증·Top-5/10 평가 기록은 보존했다.

- 2026-10-16 | Quantitative Top 20 Contract | MEDIUM 정확히 20개 선정 정책에 독립 version을 부여해 기존 10개 결과와 충돌을 방지하고 수량·레거시 보존 회귀 검증을 추가했다.
- 2026-10-16 | Quantitative Independent Completion | 일일 정량 Top 20 완료·중복 검사를 LLM 결과에서 분리하고 MEDIUM 제출 key를 Top 20 전용으로 구분했다.
- 2026-10-16 | Quantitative Output Metadata | 일일 정량 후보 파일에 실제 모델 목적·예측 기간을 명시해 MEDIUM 결과가 SHORT 기본값으로 표시되지 않도록 수정했다.
- 2026-10-16 | Local OpenAI Environment | 업로드한 로컬 인증 환경파일을 Git 제외된 저장소 루트로 이동하고 기본 환경 로딩 위치에 맞췄다.
- 2026-10-16 | Azure OpenAI Compatibility | 실제 연동에서 확인한 temperature 미지원 오류를 해결하기 위해 해당 강제 설정을 제거하고 strict JSON 계약을 유지했다.
- 2026-10-16 | Azure OpenAI Smoke Test | 로컬 Entra 인증과 실제 배포의 strict JSON 응답을 최소 요청으로 검증하고 정상 응답을 확인했다.
- 2026-10-16 | Independent LLM Pipeline | LLM Top 20을 정량 추론 내부에서 분리하고 전용 pipeline·모듈 실행 진입점과 형제 실행 결과를 추가했다.
- 2026-10-16 | LLM Folder Separation | LLM 설정을 config/llm_preselection으로 이동하고 전용 구현·테스트 폴더와 독립 실행 구조를 하네스·구현 지시서에 반영했다.
- 2026-10-16 | Parallel Failure Isolation | 공통 manifest 준비 뒤 Qlib export·모델 검증과 LLM을 독립 실행하여 한쪽 실패 시 다른 결과를 보존하고 양쪽 실패를 명시했다.
- 2026-10-16 | Parallel Preselection Idempotency | MEDIUM 일일 중복 실행을 건너뛰기 전에 정량 Top 20과 LLM Top 20이 모두 성공했는지 검증하도록 보강했다.
- 2026-10-16 | Daily Parallel Preselection | 일일 수집 후 MEDIUM_20D Alpha158 정량 Top 20과 manifest-fenced Azure OpenAI Top 20을 병렬 생성하고 최종 병합은 후속 범위로 분리했다.
- 2026-10-16 | Quantitative Top 20 | MEDIUM_20D 전용 selection policy와 DB position 상한을 20개로 확장하면서 SHORT_5D 레거시 5~10개 정책을 유지했다.
- 2026-10-16 | LLM Temporal Evidence | 뉴스·실적·SEC filing/facts·기업행위·종목 상태·유니버스·가격을 execution manifest와 cutoff로 제한하는 evidence packet과 lineage를 추가했다.
- 2026-10-16 | LLM Ranking | Entra 인증 Azure OpenAI strict JSON 배치 평가·최종 재정렬, bounded retry, token/hash 감사와 성공 run 재사용을 구현했다.
- 2026-10-16 | LLM Preselection Schema | LLM run·packet·evidence·call attempt·assessment와 별도 Top 20 candidate 결과를 append-only schema로 추가했다.
- 2026-10-16 | LLM Preselection API | 정량 API와 분리된 LLM run·후보·source evidence 조회 endpoint를 추가했다.
- 2026-10-16 | LLM Runtime Infrastructure | Candidate 관리 ID의 최소 Azure OpenAI RBAC와 feature flag·endpoint/deployment 설정을 App Service IaC에 추가했다.
- 2026-10-16 | Preselection Downstream Gate | 두 Top 20의 최종 병합 전까지 MEDIUM 중간 후보를 Portal·TradingAgents에 자동 제출하지 않도록 오케스트레이터를 변경했다.
- 2026-10-16 | Daily MEDIUM Only | 정기 일일 파이프라인을 MEDIUM_20D 단일 실행으로 변경하고 SHORT_5D·명시적 API 모델 선택·기존 dual 흐름 및 두 모델 주간 재학습은 유지했다.
- 2026-10-16 | Daily MEDIUM Deployment | MEDIUM 단일 정기 실행을 운영 배포하고 오케스트레이터 101건·후보 API 12건 및 함수 22개 활성·메일 차단·replica 1개 유지 상태를 검증했다.
- 2026-10-16 | Completed Plan Cleanup | 완료된 주간 재학습 플랜을 로컬에 보존하고 Git 추적에서 제외하도록 ignore 항목과 추적 해제를 적용했다.
- 2026-10-16 | Guardian Replica Floor | TradingAgents 최소 replica를 정확한 일치 대신 설정 하한 이상으로 검사하고 하한 미만에서만 복구하도록 변경했다.
- 2026-10-16 | TradingAgents Scaling | 사용자 승인으로 운영 replica 1개 고정·트래픽 전환·기존 리비전 비활성화를 완료하고 워커 3개·메일 차단 유지 및 실제 가디언 SUCCEEDED를 검증했다.
- 2026-10-16 | Orchestrator Email Deployment | 인증된 Flex OneDeploy로 발송 차단 코드를 배포하고 운영 EMAIL_ENABLED=false, 함수 22개 활성 상태와 private Storage 유지 및 테스트 92건을 검증했다.
- 2026-10-16 | Guardian Email | 메일 비활성 시 guardian 알림도 SKIPPED로 기록하면서 실제 preflight 실패 상태는 유지하도록 보완했다.
- 2026-10-16 | Orchestrator Email | ORCHESTRATOR_EMAIL_ENABLED 설정으로 ACS 메일 발송을 건너뛰어도 파이프라인이 계속 실행되도록 변경하고 배포 설정에서 메일을 비활성화했다.
- 2026-10-16 | Weekly Final Validation | 전체 pytest 365건, Ruff, Bicep compile, diff·secret·IDE 문제 검사를 통과하고 배포 임시 파일을 정리했다.
- 2026-10-16 | Weekly Canary | cutoff-fixed 2년 251,978행 export와 실제 SHORT·MEDIUM Job을 완료하고 두 gate의 REJECT 및 active assignment 무변경을 검증했다.
- 2026-10-16 | Weekly Deployment Validation | 최종 Backend·Durable 배포, operational manifest eligibility, private ACR·Blob, PostgreSQL lock, P3v3/VNet·SCM auth 상태를 검증하고 historical validation run을 정리했다.
- 2026-10-16 | Weekly Manifest Fence | eligibility가 training 중 생성된 historical reconstruction context를 재선택하지 않고 최신 operational replay manifest에 고정되도록 수정했다.
- 2026-10-16 | Weekly Activation Rollback | Candidate가 promoted Blob artifact를 실제 materialize·검증하고 실패 시 generation CAS로 이전 assignment 또는 legacy fallback으로 rollback하도록 연결했다.
- 2026-10-16 | Weekly Export Permissions | training ID에 cutoff-fixed export가 요구하는 세 ops derived-context table의 INSERT만 추가하고 원천 데이터는 read-only로 유지했다.
- 2026-10-16 | Weekly Job Correlation | Durable start activity가 생성된 Container Apps execution name을 주간 run에 즉시 CAS binding하도록 내부 API를 추가했다.
- 2026-10-16 | Weekly Retraining Documentation | private training·Backend·Durable 배포 상태와 실제 Job 입력·재시도·승격 계약을 README와 실행 계획에 반영했다.
- 2026-10-16 | Weekly Retry | 실패한 deterministic 주간 run을 다음 주말 tick에서 같은 ID로 안전하게 재수락하고 terminal Durable parent를 재시작하도록 보강했다.
- 2026-10-16 | Weekly Promotion Runtime | training Job이 gate 결정을 기록하고 reject를 종료하며 통과 시 immutable Blob artifact upload와 generation CAS 승격까지 수행하도록 연결했다.
- 2026-10-16 | Weekly Training Input | 격리 training Job이 로컬 사전 export를 가정하지 않고 고정 cutoff로 2년 Qlib 입력을 작업 디렉터리에 생성하도록 연결했다.
- 2026-10-16 | Weekly Training Identity | Container Apps training Job에 Azure 구독·tenant와 Entra PostgreSQL principal 환경을 명시해 관리 ID 설정 계약을 완성했다.
- 2026-10-16 | Weekly Job Runtime | Container Apps Job 실행 시 배포된 전체 template 계약을 보존하고 weekly 입력 환경 변수만 안전하게 덮어쓰도록 수정했다.
- 2026-10-16 | Weekly Training Container | Python 3.12 analytics 환경에서 weekly job module을 실행하는 비root 전용 training image 정의를 추가했다.
- 2026-10-16 | Weekly Orchestration | 주말 eligibility, 멱등 weekly API, Container Apps Job 실행·poll, SHORT/MEDIUM 독립 결과 Durable 흐름을 추가했다.
- 2026-10-16 | Candidate Training Infrastructure | Candidate 전용 private Blob·ACR·Container Apps Job·VNet·관리 ID·최소 RBAC IaC를 추가했다.
- 2026-10-16 | Model Promotion Artifacts | versioned promotion gate와 schema v2 immutable artifact packaging·검증·원자적 cache를 추가했다.
- 2026-10-16 | DAILY Model Binding | DAILY 실행이 active assignment generation·manifest identity를 process metadata에 고정하고 재시도 시 같은 binding을 재사용하도록 연결했다.
- 2026-10-16 | Weekly Retraining Migration | Azure PostgreSQL 16에서 migration transaction rollback과 실제 적용, assignment CAS·rollback을 검증했다.
- 2026-10-16 | Weekly Training Database Access | 주간 학습 관리 ID에 원천 schema 읽기와 analytics schema 쓰기만 부여하는 최소 권한 부트스트랩을 추가했다.
- 2026-10-16 | Weekly Training Workflow | 모델 학습·평가·SHADOW 등록을 재사용하면서 production score·selection 저장을 차단하는 training-only 진입점을 추가했다.
- 2026-10-16 | Weekly Retraining Schema | 주간 학습 실행·승격 결정·active model assignment·이력 테이블과 모델 목적별 champion 유일성 제약을 추가했다.
- 2026-10-16 | Weekly Retraining Repository | deterministic 주간 run 멱등성과 generation 기반 active assignment CAS·rollback 이력 기반을 추가했다.
- 2026-10-16 | Backend Database Bootstrap | backend 관리 ID 부트스트랩이 weekly retraining migration을 적용하도록 확장했다.
- 2026-10-16 | Weekly Retraining Plan | partial 구현 부재, Phase 2 구현 범위와 로컬 검증 환경 제한을 현재 상태에 반영했다.

- 2026-10-14 | Architecture Documentation | README와 기준 아키텍처를 발표 1장의 candidate_engine·계획 LLM Top 20·외부 TradingAgents 경계로 통일했다.

- 2026-10-14 | Presentation | 중간 발표 4판의 중첩 아키텍처와 LLM 상위 20 병렬 경로를 유지하면서 실제 수집 데이터·에이전트·데이터 계층 명칭을 그레이톤으로 교정한 7판을 추가했다.

- 2026-10-14 | Presentation | 4판 아키텍처 구조 재사용, 수집·스키마 병합, 3계층 하네스와 10월 판정 수익률을 반영한 중간 발표 6판을 추가했다.
- 2026-10-14 | Evaluation | 2026-10-01~12 MEDIUM_20D 후보와 TradingAgents Hold·Overweight 판정의 D+1 시가 매수·10월 12일 종가 평가 근거를 문서화했다.

- 2026-10-13 | Presentation | 후보 엔진과 종목토론방을 통합하고 실제 수집 필드·Alpha158 샘플·상세 아키텍처를 보강한 그레이톤 중간 발표 5판을 추가했다.

- 2026-10-13 | Dual-Model Failure Policy | SHORT_5D eligibility·submit·poll·fetch 실패를 core failure로 분류해 MEDIUM_20D 시작을 차단했다.

- 2026-10-13 | Documentation | Candidate 업무 범위와 오케스트레이터 control plane 경계, 모델별 schema v2 artifact, encrypted Function secret 운영 상태를 README·모델 문서에 반영했다.

- 2026-10-13 | Multi-Model Inference | Candidate DAILY가 SHORT_5D·MEDIUM_20D별 schema v2 artifact/config/label 계약을 strict 선택하고 교차 fallback을 금지하도록 확장했다.

- 2026-10-13 | Dual-Model Timer | cutoff 전 terminal parent가 있어도 정기 시각에는 동일 deterministic ID로 재시작하고 active parent만 재사용하도록 수정했다.

- 2026-10-13 | Dual-Model Orchestrator | 정기 실행을 SHORT_5D 완료 후 MEDIUM_20D를 순차 실행하는 parent orchestration으로 확장했다.
- 2026-10-13 | Duplicate Guard | 동일 날짜·동일 모델의 유효한 성공 selection이 있으면 Candidate·Portal·TradingAgents를 재실행하지 않고 SKIPPED_EXISTING으로 종료하도록 추가했다.
- 2026-10-13 | Resource Guardian | 15분마다 운영 리소스 상태를 점검·안전 복구하고 실패를 경고 메일과 telemetry로 기록하도록 추가했다.
- 2026-10-13 | Orchestrator Email | 모델·대상일·상태를 포함한 메일 제목, skip 단일 메일과 safe failure code 계약을 적용했다.
- 2026-10-13 | Pipeline Telemetry | parent/model/guardian correlation telemetry와 Log Analytics KQL 운영 runbook을 추가했다.
- 2026-10-13 | Documentation | dual-model parent, guardian, private Storage와 중복 skip 기준으로 README·아키텍처·수집·모델 문서를 갱신했다.

- 2026-10-13 | Orchestrator Secrets | private-only Key Vault reference drift를 제거하고 secure Bicep parameter로 encrypted Function App Settings를 배포하도록 정합화했다.

- 2026-10-13 | Orchestrator Deployment | FC1 Function, private Storage networking, managed identity RBAC, ACS Email과 수동 SHORT_5D trigger를 Azure에 배포했다.
- 2026-10-13 | End-to-End Verification | 2026-10-09 기존 데이터 재사용, SHORT_5D 후보 10개, Portal DailyAnalysis와 TradingAgents 분석 10건, 시작·종료 메일을 검증했다.
- 2026-10-13 | Resource Remediation | 실행 전 App·PostgreSQL·MySQL·TradingAgents·Storage 상태를 제한적으로 복구하고 lock을 원상 복원하는 운영 계약을 배포했다.

- 2026-10-13 | Portal Integration | 후보 5~10개 job의 최초 dispatch를 기다릴 수 있도록 Portal batch 제출 timeout을 5분으로 분리했다.

- 2026-10-13 | Pipeline API | static eligibility route를 UUID 동적 route보다 먼저 등록해 `/pipeline-runs/eligibility`의 422 충돌을 제거했다.

- 2026-10-13 | Pipeline API | 저장된 calendar row와 분리된 XNYS 거래일·cutoff eligibility endpoint를 추가해 오케스트레이터 gate가 실제 운영 규칙을 사용하도록 수정했다.

- 2026-10-13 | Orchestrator Runtime | 비실행 Durable instance 상태를 active로 오인하지 않고 동일 deterministic ID로 재시작하도록 수동 trigger를 수정했다.

- 2026-10-13 | Orchestrator Runtime | Azure Functions Python activity binding이 인식하도록 Candidate activity 입력 annotation을 plain dict로 교정했다.

- 2026-10-13 | Orchestrator Deployment | FC1 deployment content traffic이 Storage private endpoint를 사용하도록 vnetContentShareEnabled를 활성화했다.

- 2026-10-13 | Orchestrator Preflight | STARTED 알림 전에 App Service·PostgreSQL·MySQL·TradingAgents·Storage를 제한적으로 복구하고 lock을 원상 복원한 뒤 ARM·data plane·HTTP readiness를 재검증하도록 강화했다.

- 2026-10-13 | Orchestrator Infrastructure | Durable Functions backend를 관리 ID 기반 표준 Azure Storage로 되돌리고 DTS 리소스·설정·RBAC를 템플릿에서 제거했으며 Storage endpoint 정책 점검 절차를 문서화했다.

사용자 요청에 따른 변경을 한 항목당 한 줄로 기록한다.

형식:

```text
- YYYY-MM-DD | 영역 | 변경 요약
```

## 2026-10-12

- 2026-10-12 | Orchestrator Deployment | 현재 구독에 존재하지 않는 Email Sender role 대신 제공되는 Communication and Email Service Owner role을 사용하도록 교정했다.
- 2026-10-12 | Orchestrator Deployment | Flex Consumption runtime과 충돌하는 중복 FUNCTIONS_WORKER_RUNTIME 앱 설정을 제거했다.
- 2026-10-12 | Orchestrator Infrastructure | Durable Functions 상태 backend를 Consumption Durable Task Scheduler와 task hub, system-assigned identity RBAC로 전환하고 FC1 Storage는 runtime·배포 용도로 분리했다.
- 2026-10-12 | Orchestrator Manual Trigger | Function 인증 수동 HTTP starter에 날짜·모델 목적 검증, 목적별 Durable ID·Candidate 멱등 key와 secret 없는 관리 응답을 추가했다.
- 2026-10-12 | Orchestrator Model Purpose | 모델 목적을 orchestration 입력에서 후보 조회와 포털 batch까지 전달하고 타이머 기본값을 MEDIUM_20D로 고정했다.
- 2026-10-12 | Orchestrator Verification | SHORT_5D 충돌 방지·입력 검증·기존 인스턴스 재사용·Candidate/Portal 전달을 회귀 테스트와 운영 문서에 추가했다.
- 2026-10-12 | Orchestrator Architecture | Durable 제어 흐름·상태 전이·멱등성·외부 계약·RBAC·관측성을 독립 기준 문서로 작성했다.
- 2026-10-12 | Overall Architecture | 전체 Azure 아키텍처에 오케스트레이터 control plane의 저장 경계와 terminal 상태 흐름을 보강했다.
- 2026-10-12 | Architecture Status | 전체 아키텍처의 데이터 완전성 표를 Massive·SEC·Alpha Vantage 실제 적재량과 현재 SHADOW 모델 상태로 교정했다.
- 2026-10-12 | README Architecture | 메인 README의 전체 아키텍처 아래에 구현 기준 오케스트레이터 아키텍처와 상세 문서 링크를 추가했다.
- 2026-10-12 | Architecture Documentation | Candidate Engine, FC1 Durable Functions, Portal service API, TradingAgents Container App, PostgreSQL·MySQL과 ACS Email의 전체 Azure 경계와 데이터 흐름을 문서화했다.
- 2026-10-12 | Pipeline Documentation | 05:30 ET 거래일 trigger, Candidate API 멱등 계약과 MEDIUM_20D 기본·SHORT_5D one-off 실행 정책을 수집·모델·오케스트레이터 문서에 반영했다.
- 2026-10-12 | Orchestrator Infrastructure | 운영 FC1 배포에서 TradingAgents URL을 필수 파라미터로 강제해 readiness 사전 점검이 생략되지 않도록 수정했다.
- 2026-10-12 | Orchestrator Portal Contract | 포털 연동을 Bearer 인증 기반 후보 분석 일괄 제출·집계 조회로 수정하고 5~10개 작업의 부분 실패 요약을 보존했다.
- 2026-10-12 | Orchestrator Readiness | 포털 readiness를 `/readyz`로 수정하고 설정된 경우 TradingAgents `/readyz`도 배포 전 점검하도록 추가했다.
- 2026-10-12 | Durable Orchestrator | 05:30 ET 거래일 게이트부터 Candidate 멱등 실행·후보 검증·포털 부분 실패 처리·ACS Email까지 replay-safe activity와 durable timer로 구현했다.
- 2026-10-12 | Orchestrator Infrastructure | Linux FC1, 관리 ID 기반 Storage·Key Vault·Application Insights·ACS Email과 운영 알림을 구성하는 독립 Bicep을 추가했다.
- 2026-10-12 | Orchestrator Verification | DST·HTTPS 제한·응답 크기·5~10개 후보 검증·종목별 무재시도 부분 실패를 격리 단위 테스트로 추가했다.
- 2026-10-13 | Orchestrator Private Network | FC1 VNet 통합, Blob·Queue·Table private endpoint와 private DNS를 추가하고 Storage를 관리 ID 기반 private-only 계약으로 전환했다.
- 2026-10-12 | Pipeline Planning | Candidate 일일 실행과 외부 포털·TradingAgents 분석을 Durable Function, 멱등 API, readiness, ACS Email로 연결하는 자동화 계획을 구체화했다.
- 2026-10-12 | Candidate API | expand-compatible nullable pair로 파이프라인 Idempotency-Key와 canonical 요청 hash를 영속화하고 동일 요청 재사용·payload 충돌 검증을 추가했다.

## 2026-10-11

- 2026-10-11 | Presentation | 최신 MEDIUM_20D 모델·하네스·Backend API·TradingAgents 외부 경계를 반영한 8장 중간발표 v4를 작성했다.
- 2026-10-11 | MEDIUM_20D Model | 20거래일 label·purged walk-forward·scorecard 모델 선택과 다중 모델 저장/API를 구현하고 2026-10-09 SHADOW 후보 10개를 저장했다.
- 2026-10-11 | Advanced Features | 장기 가격·SEC 가용성·총수익 label·optional Azure OpenAI 뉴스 분류와 E2~E6 readiness 계층을 추가했다.
- 2026-10-11 | Temporal Safety | 과거 후보 export의 명시적 cutoff 선택, label 성숙 경계와 historical reconstruction 제한을 검증했다.
- 2026-10-11 | Model Documentation | README·모델 아키텍처·모델 변경 이력과 ignored 후보 결과 파일을 MEDIUM_20D 실제 실행 결과로 갱신했다.
- 2026-10-11 | Backend Deployment | 기본 후보 API가 MEDIUM_20D를 반환하도록 기존 App Service에 배포하고 SHORT_5D 명시 조회·포털 CORS·readiness를 운영 검증했다.
- 2026-10-11 | API Documentation | 후보 API의 MEDIUM_20D 기본값, SHORT_5D 명시 조회, 모델 간 자동 fallback 금지와 응답 의미를 README에 명시했다.
- 2026-10-11 | Model Architecture Documentation | 하단에 추가된 Alpha158·LightGBM·scoring·결과 계약 정보를 기존 모델 흐름에 맞춰 재배치하고 다중 기간 확장을 독립 절로 정리했다.
- 2026-10-11 | Backend Verification Tests | 기존 실행 재검증의 중복 POST 방지, gateway 재시도 상한과 실패·성공 poll 증거의 영속화를 회귀 테스트로 검증했다.
- 2026-10-11 | Backend DAILY Deployment | cutoff 수정본 재배포 후 운영 DAILY의 scoring·selection 성공과 고정 SHADOW 모델 기반 신규 후보 10개, 실제 포털 CORS를 확인하고 임시 배포 파일을 정리했다.
- 2026-10-11 | Backend Gateway Diagnostics | 502.0 플랫폼 gateway 오류와 container recycle 부재를 확인하고 미확정 세부 원인·재발 대응 및 완료된 배포 검증을 운영 문서에 기록했다.

- 2026-10-11 | Model Plan | 63거래일 계획을 20거래일 중기 수익률 모델로 개정하고 다중 모델 API, 검증 scorecard, E1~E6 및 Azure OpenAI 특징 계약을 확정했다.
- 2026-10-11 | Model Plan | Azure OpenAI 뉴스 특징을 optional로 전환하고 실패 시 상태를 기록하되 미래 정보 없이 non-LLM 모델 분석을 계속하도록 정책을 수정했다.
- 2026-10-11 | Configuration Example | Azure OpenAI endpoint·deployment·API version과 Entra service-principal 환경변수 예시를 추가했다.
- 2026-10-11 | Backend Verification | 실행 검증의 대기 시간을 설정 가능하게 하고 run ID·응답 시각·상태·request ID를 영속 기록하며 후보 조회의 미지원 process 필터를 제거했다.
- 2026-10-11 | Backend Artifact Deployment | 명시적 모델·manifest의 원격 checksum 검증과 Bicep checksum 설정을 추가하고 로컬 추론 검증 산출물을 Git 제외했다.

- 2026-10-11 | Backend Inference Cutoff | API 추론 export에 요청 session의 결정 cutoff를 명시해 재수집 관찰 시각이 상속되어 과거 후보 생성이 차단되는 오류를 수정하고 CLI export 기본 동작을 보존했다.

- 2026-10-11 | Backend Live | 전용 B3 App Service에 API를 배포하고 Managed Identity PostgreSQL 조회, 인증된 RANGE 완료와 실제 종목토론방 브라우저 CORS 호출을 검증했다.

- 2026-10-11 | Backend Plan | PostgreSQL 단일 원본, 비동기 실행·후보·실행 이력·8개 데이터셋 API, 10일 조회 제한과 App Service 배포·검증 계획을 작성했다.
- 2026-10-11 | Backend Foundation | FastAPI application factory, 정확한 포털 Origin CORS, 실행 API Key 인증, 표준 오류·request ID·상태 확인 API와 backend 의존성을 추가했다.
- 2026-10-11 | Backend Read APIs | 날짜별 최신 성공 후보, 필터 결합 서명 커서, 8개 정규화 데이터셋의 10일 조회 및 provenance와 API 실행 상태·날짜별 attempt 조회를 typed 모델과 SQL/API 테스트로 추가했다.
- 2026-10-11 | Backend Status | API 후보 생성이 진행 중이면 수집 완료 시각을 상속하지 않고 API 소유 finished_at의 null 상태를 유지하도록 조회와 회귀 테스트를 보강했다.
- 2026-10-11 | Backend Execution | 거래일·완료 cutoff·provider 범위를 검증한 API 접수를 원자적으로 영속화하고 동일 run ID, RANGE child ID, 전역 활성 작업 제한, API 소유 중단 복구와 후보 추론 warm-up export를 기존 배치 함수에 연결했다.
- 2026-10-11 | Backend Operations Docs | API 소유 상태·중단 복구, inference-only DAILY의 고정 model/manifest hash·설정 기반 61-session 이력·영속 출력 경로와 공유 B1의 미검증 용량 제한을 문서화했다.
- 2026-10-11 | Backend Workspace | BACKEND_WORKSPACE_DIR와 명시적 model manifest·checksum 환경 설정을 기존 service 생성자에 연결하고 Qlib·후보 출력을 영속 workspace에 저장하면서 배포된 config·SQL 경로와 분리했다.
- 2026-10-11 | Model Core | 기존 5일 경로를 보존하면서 versioned 20-session label·LightGBM config와 horizon별 학습·평가·scoring 전파를 추가했다.
- 2026-10-11 | Model Safety | 20일 E1 scoring의 LLM 비의존성을 명시하고 historical cutoff 선택과 fit 시점 label 성숙도 검사를 fail-closed로 강화했다.
- 2026-10-11 | Backend Model Provisioning | 명시적으로 선택한 registry LightGBM과 parquet feature 순서를 검증해 weights 및 checksum manifest만 배치하는 artifact 준비 도구를 추가했다.
- 2026-10-11 | Backend Least Privilege | API 소유 DAILY·BACKFILL은 runtime migration을 생략하고 일별 수집의 DDL을 명시적으로 비활성화하면서 CLI의 자동 migration 기본 동작을 보존했다.
- 2026-10-11 | Backend Deployment | 포털을 변경하지 않는 별도 App Service Bicep, 비밀값 제외 source ZIP, Entra DB 권한 부여 도구와 운영 문서를 추가했다.

- 2026-10-11 | Backfill | Massive Basic 허용 범위 내 추가 1년 248 sessions를 실패·재처리 없이 적재해 전체 500 sessions를 확보했다.
- 2026-10-11 | Data Quality | 2년 범위 미래 데이터 위반 0, semantic duplicate 0, SPY 500/500, blocking issue 0을 검증했다.
- 2026-10-11 | Model Retraining | 2년 Qlib export 251,471행으로 Model v2를 재학습하고 LightGBM SHADOW 후보 10개를 갱신했다.
- 2026-10-11 | Fix | Momentum·Ridge는 평가 baseline으로만 유지하고 `PREDICTED_5D_RETURN` 후보 scoring은 Qlib LightGBM artifact로 고정했다.
- 2026-10-11 | Architecture | 전처리·Alpha158·raw-return label·walk-forward·평가·scoring·selection 계약과 다이어그램을 모델 아키텍처 문서 및 README에 추가했다.
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
- 2026-10-17 | LLM | 기간 검색 뉴스를 인용 URL·페이지에서 Python이 읽은 게시일/시각으로 판정하도록 재구현했다(전일 이전은 일자, 당일은 05:30 이전 시각만 승인, 미확인은 거부).
- 2026-10-17 | Documentation | 프로젝트·LLM 하네스에 인용 페이지 게시일 판정 규칙과 candidate-citations.json 비의존을 명시했다.
