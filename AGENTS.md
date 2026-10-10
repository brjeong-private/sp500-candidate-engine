# Repository Instructions

- 모든 작업은 루트의 `PROJECT-HARNESS.md`를 먼저 적용한다. 기능별 문서와 충돌하면 공통 하네스를 우선한다.
- 프로젝트 범위는 `수집 -> 전처리 -> 모델 점수 -> 후보 선정`까지다. TradingAgents 실행·분석·리포트·비용·재평가는 이 저장소에 구현하지 않는다.
- 사용자 요청으로 코드, 설정, 스키마 또는 문서를 변경할 때마다 `CHANGELOG.md`에 변경 항목별 한 줄 요약을 추가한다.
- 형식은 `- YYYY-MM-DD | 영역 | 변경 요약`을 사용한다.
- 여러 독립 변경은 각각 별도 한 줄로 기록한다.
- API key, token, password, connection secret, raw payload 내용은 변경 로그에 기록하지 않는다.
- 런타임 로그와 임시 검토 파일은 기존 `.gitignore` 정책을 따른다.
