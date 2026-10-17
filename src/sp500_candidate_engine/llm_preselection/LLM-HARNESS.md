# LLM 검색·격리 평가·미래 정보 차단 하네스

[공통 하네스](../../../PROJECT-HARNESS.md)가 우선한다.
기존 v1/v2의 DB-only 평가는 보존한다. 새 검색 경로는
`config/llm_preselection/policy_event_search_v4.yaml`을
명시 선택한다. 서버의 SEC 원문 다운로드·HTML 파싱 보강 경로는 제거했다.
기간 필터가 필요한 경로는 [policy_event_period_v5.yaml](../../../config/llm_preselection/policy_event_period_v5.yaml)의
Foundry Bing Grounding을 선택하며 `freshness`를 도구 파라미터에 고정한다.

## 1. 취득 주체와 데이터 경계

1. 기존 DB packet은 고정 context/manifest에서 읽는다.
2. **검색은 Azure OpenAI Responses API의 provider-hosted `web_search`가 수행한다.**
   서버는 뉴스·SEC·IR URL을 GET하지 않는다. 프롬프트만으로 검색했다고 간주하지 않는다.
3. 검색 모델에는 회사명·ticker·CIK·cutoff·공개 공시 식별정보만 전달한다.
   전체 DB packet, 내부 UUID, 뉴스 계약 payload·재무 자료·secret은 검색에 전달하지 않는다.
4. 검색 모델의 응답·추론·전체 대화는 격리한다. 검증을 통과한 인용 문단만 별도 packet에 넣는다.
5. 평가 모델은 **새 system/user 대화**에서 DB packet과 승인 문단만 받는다.
   `previous_response_id`, 검색 assistant message·reasoning·미검증 문단을 재사용하지 않는다.
   평가 호출에는 검색 도구를 제공하지 않는다.

Azure 검색은 Bing Grounding을 사용하며 별도 비용·데이터 처리 경계가 적용된다.
공개 metadata만 검색에 전달하는 whitelist는 프롬프트가 아니라 호출 코드에서도 강제한다.

## 2. 미래 정보 사용 금지 — 강제 admission gate

- 업무 날짜와 cutoff는 기존 실행 값을 고정한다. 재실행 시 현재 시각으로 이동하지 않는다.
- **LLM만 적용:** cutoff의 뉴욕 날짜보다 이전 공개/원문 버전일은 일자만 판정한다.
  생성 시각 부재를 이유로 전일 자료를 거부하지 않는다. 당일은 timezone-aware 시각이
  뉴욕 05:30보다 엄격히 이전이어야 한다. 당일 날짜만 있거나 정각/이후이면 거부한다.
  별도 cutoff가 더 이르면 그 경계를 넘기지 않는다. 사건일이 아닌 공개/버전일 기준이다.
  시각이 있으면 NY 날짜로 변환하고 날짜만 있으면 NY 달력일로 본다.
  이 규칙은 Python `asof.py`가 강제하며 수집/정량 규칙은 바꾸지 않는다.
- **날짜가 과거인 일반 뉴스 페이지는 과거 원문 revision 증거가 아니다.**
  LLM이 주장한 공개일·URL·검색 쿼리의 날짜 제한도 검증 증거가 아니다.
- 초기 승인 범위는 기존 packet에 고정된 CIK/accession의 SEC 원문 버전이다.
  공개 시각은 모델 추정이 아니라 DB manifest의 공시 접수 metadata를 사용한다.
  현재 뉴스·회사 홈페이지·검색 index·다른 accession·다른 회사는 승인하지 않는다.
- 모든 `web_search_call`의 실제 실행·완료를 확인한다. `include`로 받은 전체
  `action.sources`와 open/find 대상 URL까지 검사한다. 최종 답변의 인용만 검사하지 않는다.
- 미래/현재/버전 불명 출처가 **하나라도** 검색에 섞이면 해당 검색 응답 전체를 폐기한다.
  안전한 문단만 사후 추려서 이미 오염된 검색 대화를 평가에 넘기지 않는다.
- 검색 쿼리·응답의 명시적 미래 날짜/연도/분기 주장도 거부한다.
  발췌 내용은 분석 cutoff뿐 아니라 인용 원문의 공개 시점 이후 결과를 주장할 수 없다.
- 원문을 확보하지 못했다는 답변·출처 없는 문단·잘린/잘못 연결된 인용은 사실로 승격하지 않는다.
  승인된 문단이 없으면 실패하며 DB-only 성공으로 fallback하지 않는다.
- 모델 이름·버전은 재현성 metadata로만 기록한다. 날짜 없는 alias·버전 변경·metadata 부재를
  이유로 과거 공개·원문 버전이 검증된 자료를 차단하지 않는다. 자료의 공개 시점과
  원문 revision 검증을 모델 metadata 검증으로 대체하지 않는다.
- `HISTORICAL_RECONSTRUCTION`만 늦은 검색을 허용한다.
  `OPERATIONAL_REPLAY`는 검색 관찰도 cutoff 이내여야 하며 늦은 검색은 호출 전에 차단한다.
- Bing `freshness`는 발견일 범위이며 공개일 증명이 아니다. 기간 검색(`AZURE_BING_GROUNDING_PERIOD`)은
  **Python `source_dates.py`가 인용 URL·페이지에서 직접 읽은 게시일/시각**으로 판정한다
  (`candidate-citations.json` 같은 별도 원문 파일에 의존하지 않는다).
  URL 경로 날짜와 페이지 게시 metadata(`article:published_time`·`datePublished`·`<time datetime>`)
  중 더 늦은 값을 쓰며 수정 시각은 보지 않는다. 뉴욕 기준 전일 이전은 일자만으로 승인하고,
  당일은 timezone이 있는 시각이 05:30 이전일 때만 승인한다. 날짜 미확인·당일 시각 부재·
  미래 날짜·HTTPS 공개 호스트가 아닌 URL·fetch 실패는 해당 출처만 거부(fail closed)한다.
  승인된 문단의 날짜 라벨은 모델 값이 아니라 Python이 쓴 값이며 재생 시 같은 규칙으로 재검증한다.
  모델이 쓴 공개일은 증거로 쓰지 않는다.

## 3. 보증 범위와 한계

이 하네스는 **검증 가능한 원천 버전·공개 시점·데이터 전달 경로**를 제한한다.
모델 metadata는 감사용이며 자료 시점의 증명이나 평가 차단 조건이 아니다.
일반 `web_search`는 원문의 신뢰 가능한 공개/수정 시각·과거 본문 hash를 제공하지 않는다.
따라서 일반 뉴스의 과거 날짜만 보고 점수에 넣거나 보강 성공으로 보고하지 않는다.
일반 뉴스까지 승인하려면 신뢰할 수 있는 과거 원문 버전 증거를 반환하는 검색 도구 계약이 필요하다.

검색 발췌는 모델이 만든 인용 요약이며 **원문 자체나 의미적 사실성의 완전한 보증이 아니다.**
인용·URL 검증만으로 환각이 없다고 주장하지 않는다. 미래 날짜 문자열 검사는 추가 방어일 뿐,
자의적인 날짜 필터나 모델 자기신고를 원천 시점 증명으로 대체하지 않는다.
계획/가이던스와 실제 결과를 혼동하지 않으며 불확실한 항목은 null·정보 부족으로 남긴다.

## 4. 인용·재현·실패

- 기존 `evidence_link_id/source_snapshot_id`는 DB 공시 entity/metadata의 identity다.
  검색 artifact를 원문 파일이나 DB 원천 snapshot이라고 표현하지 않는다.
- `LLM_SEARCH_VERIFIED` 인용은 같은 공시의 `search_evidence_hash`에 정확히 연결한다.
  `DB_PACKET` 인용의 검색 hash는 null이다.
- 검색 응답 전체·전체 consulted sources·요청 fingerprint·관찰 시각·모델 snapshot을
  content-addressed JSON artifact로 보존한다. 실패 응답도 격리 증적으로 보존한다.
- cache는 context·instrument·base packet·lineage·policy·검색 prompt·모델·endpoint에 묶는다.
  재사용할 때 저장 tool trace를 admission gate에 다시 통과시킨다.
- artifact 누락/변조·원문 버전 불일치·검색 도구 미실행·미래 출처·본문 미확보는
  명시적 실패다. 서버 다운로드·다른 모델·구 정책으로 조용히 대체하지 않는다.
- 기존 정규화 수집 DB·DDL은 늘리지 않는다. 승인된 bounded 검색 발췌/proof만 기존
  immutable 입력 JSONB에 보존하며 raw 검색 대화는 파일/객체에 격리한다.
- 후보 수·rubric·지원 항목 재정규화·RRF는 유지한다. 승인된 새 정보로 새 정책의 점수는
  달라질 수 있으나 과거 run을 덮어쓰지 않는다.
- 한국어 평가·인용 이유·정보 부족을 검증한다. JSON key/enum/UUID는 번역하지 않는다.
- 단건 증적 실행은 DB 연결/쓰기 없이 고정 입력 파일로 실행할 수 있다.
  검색 거부 시 평가 호출은 0건이며 숫자 점수를 생성하지 않는다.

## 5. 운영

v4는 로컬 구현이며 운영 활성화·배포는 별도다. 검색 도구 지원·허용된 데이터 처리 경계·
지속적인 artifact 저장소·원문 버전 검증 계약을 확인한 뒤 명시적으로 선택한다.
근거: [Azure native web search](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search),
[OpenAI 전체 consulted sources](https://developers.openai.com/api/docs/guides/tools-web-search).
