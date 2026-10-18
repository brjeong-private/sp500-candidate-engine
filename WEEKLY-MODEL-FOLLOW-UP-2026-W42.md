# 2026-W42 모델 승격 미달 내역과 후속 확인

기준일: 2026-10-18. 운영 PostgreSQL을 read-only로 조회한 기록이다.
기준은 실제 저장된 `analytics.model_promotion_decision.gate_results`의 `weekly-v1`이다.
`anchor_session`은 학습 입력 기준 거래일이며 실행·완료일이나 예측 horizon이 아니다.

## 1. 결론과 적용 범위

W42에는 20D 3건·5D 3건, 총 6건의 승격 결정이 있고 모두 **REJECTED**다.
학습 실행 오류가 아니라 승격 기준 미달이며, 이 문서는 과거 결과를 변경하지 않는다.
미달은 20D의 평균 Rank IC 3건·구간별 Rank IC 중앙값 1건,
5D의 평균 Rank IC 3건으로 **총 7개 gate 결과**다.

**최신 20D만 보면 평균 Rank IC 하나가 미달하지만, 주간 전체에는 구간별 중앙값 미달도 있다.**
아래에는 실패한 gate를 빠짐없이 기록했다. Rank IC는 순위 상관계수이며 수익률 %가 아니다.

앞으로 신규 정규 주말 업데이트는 **MEDIUM_20D만** 사용한다.
사용자 확인에 따라 **다음 별도 지시까지 성능 메트릭 승격 기준을 임시 비강제**한다.
수치와 미달 사실은 계속 기록하며, 성능이 개선됐거나 과거 모델을 강제 승격했다는 뜻은 아니다.

## 2. 기준에 못 미친 모든 메트릭

미달 폭은 저장된 minimum에서 actual을 뺀 값이다. 표의 날짜는 `anchor_session`이다.

| 목적 | 입력 기준일 | 실패한 gate | 실제 저장 값 | 필요한 minimum | 미달 폭 |
|---|---|---|---:|---:|---:|
| MEDIUM_20D | 2026-10-13 | `absolute.rank_ic_mean` | -0.001231099058787695 | 0.01 | 0.011231099058787695 |
| MEDIUM_20D | 2026-10-15 | `absolute.rank_ic_mean` | 0.0010025925655126166 | 0.01 | 0.0089974074344873834 |
| MEDIUM_20D | 2026-10-15 | `absolute.fold_rank_ic_median` | -0.003293167934110447 | 0.00 | 0.003293167934110447 |
| MEDIUM_20D | 2026-10-16 | `absolute.rank_ic_mean` | 0.00045954353296819435 | 0.01 | 0.00954045646703180565 |
| SHORT_5D | 2026-10-13 | `absolute.rank_ic_mean` | 0.003257207053466027 | 0.01 | 0.006742792946533973 |
| SHORT_5D | 2026-10-15 | `absolute.rank_ic_mean` | 0.004541018460047652 | 0.01 | 0.005458981539952348 |
| SHORT_5D | 2026-10-16 | `absolute.rank_ic_mean` | 0.0004782513659113145 | 0.01 | 0.0095217486340886855 |

평균 Rank IC는 평가 날짜별 순위 상관계수의 평균,
구간별 Rank IC 중앙값은 walk-forward test block별 평균 Rank IC의 중앙값이다.
이 둘은 다른 지표이므로 평균이 양수여도 구간별 중앙값이 음수일 수 있다.

## 3. 최신 20D의 전체 절대 기준

입력 기준일 2026-10-16, weekly run `ced2b957-6723-538b-b526-c007b8ce1bf7`의 기록이다.
완료 시각은 2026-10-17 10:39:56 UTC이며 challenger는
`6a0e1d11-fb69-5039-a649-e282fe802bc6`이다.

| 메트릭 | 실제 저장 값 | 당시 기준 | 당시 판정 |
|---|---:|---:|---|
| `coverage` | 1.0 | ≥ 0.80 | 통과 |
| `test_blocks` | 16 | ≥ 3 | 통과 |
| `rank_ic_mean` | 0.00045954353296819435 | ≥ 0.01 | 미달 |
| `fold_rank_ic_median` | 0.019064504040206525 | ≥ 0.00 | 통과 |
| `net_top_10_return` | 0.027974113745364553 | ≥ 0.00 | 통과 |
| `max_drawdown_top_10` | -0.12100869861822139 | ≥ -0.35 | 통과 |

나머지 5개 run도 2절에 명시한 미달 외에는 모든 절대 gate가 통과했다.
모든 run의 coverage는 1.0, test_blocks는 20D 16개·5D 12개였다.
5D의 최대낙폭 minimum은 -0.25이며 이 기준도 모두 통과했다.

상대 기준 4개는 평균 Rank IC·구간별 중앙값·Top-10 순수익률·최대낙폭의
`challenger - incumbent >= 0`이다. 하지만 이번 6개 run은
`incumbent_model_version_id=null`이고 상대 gate 24개 모두 `reason=no_incumbent`다.
**기존 운영 모델보다 우수함을 입증한 비교가 아니다.**
고정 manifest로 운영 중이던 모델의 존재와 DB active assignment 존재는 구분한다.

## 4. 추적할 정확한 run과 모델

| 목적 | 입력 기준일 | weekly_run_id | challenger_model_version_id |
|---|---|---|---|
| MEDIUM_20D | 2026-10-13 | `e5b617d6-64d1-5727-835f-43e4c554d5a1` | `f601a90c-e487-5390-977f-a6f1f40b0e68` |
| MEDIUM_20D | 2026-10-15 | `eb9833a9-d1cb-51f0-a5a9-3f2485b5e6ee` | `1b9c0d4e-9d30-554a-afc6-ed849250504e` |
| MEDIUM_20D | 2026-10-16 | `ced2b957-6723-538b-b526-c007b8ce1bf7` | `6a0e1d11-fb69-5039-a649-e282fe802bc6` |
| SHORT_5D | 2026-10-13 | `fb623c5d-323d-5986-b547-3348a00a8db5` | `ef5bd9d9-ba63-5dcd-8072-242df8d6757a` |
| SHORT_5D | 2026-10-15 | `c5fba011-e0af-5f1c-a339-6f461a6ef652` | `0a78c72c-dc7f-56c6-8173-dd3c81961312` |
| SHORT_5D | 2026-10-16 | `5ad6fb41-7503-58b1-a581-f81a8e984dda` | `d5312998-5c70-5c56-be7f-45aa09441bd5` |

재확인용 read-only SQL:

```sql
SELECT w.weekly_run_id, w.iso_week, w.model_purpose, w.anchor_session,
       w.policy_version, w.status, w.challenger_model_version_id,
       d.incumbent_model_version_id, d.decision, d.gate_results
FROM analytics.weekly_training_run w
JOIN analytics.model_promotion_decision d
  ON d.weekly_run_id = w.weekly_run_id
WHERE w.iso_week = '2026-W42'
ORDER BY w.model_purpose, w.anchor_session;
```

## 5. 이번에 변경한 정책과 변경하지 않은 안전 검사

신규 기본 정책은 `config/analytics/weekly_retraining_v2.yaml`의
`weekly-v2-20d-performance-suspended`다.

- 자동 예약과 신규 주간 접수는 MEDIUM_20D만 허용한다. 과거 두 목적의 run·history는 보존한다.
- 다음 별도 지시까지 네 성능 메트릭의 절대·상대 gate를 강제하지 않는다.
  임계값은 낮추거나 삭제하지 않고, 실제 `passed=false`와 `enforced=false`를 함께 저장한다.
- coverage ≥ 0.80·test_blocks ≥ 3, 유한한 지표·incumbent 지표의 유효성,
  point-in-time 입력·특징·목적·artifact 검증, immutable upload·CAS·smoke·rollback은 유지한다.
- 과거 weekly-v1 파일·판정은 변경하지 않는다. 기존 REJECTED run을 다시 학습하거나 소급 승격하지 않는다.
- 이번 변경은 **2026-10-18 Backend·학습 Job 이미지·Function 운영 배포를 완료했다.**
  앞선 기간검색 근거 조회 Backend hotfix뿐 아니라 신규 정책과 terminal 재실행 차단도 포함한다.
  실제 재학습·승격이나 이번 주 REJECTED run 재실행은 수행하지 않았다.

모델 업데이트가 끝나도 자동으로 성능 기준을 되살리지 않는다. 사용자 별도 지시가 필요하다.
성능 기준 비강제는 실제 예측력 개선이나 수익을 보장하지 않으며 미달 모델도 승격될 수 있다.

### 5.1 운영 배포 증적

배포 원본은 `main`에 푸시한 `7f12171fa166ccc55b7afe44a0a45c6414da168d`의
깨끗한 Git archive다. 뒤따르는 문서 갱신 commit은 배포 코드 변경이 아니다.

| 대상 | 배포 식별자 | 확인 결과 |
|---|---|---|
| Candidate Backend | `6c239663-d55f-42dc-af6e-e3ce8dbd9ba4` | 배포 성공, live·ready 정상, 배포 artifact의 기본 정책·evaluator·v2 YAML 원본 hash 일치 |
| 학습 Container Apps Job | `candidate-training:7f12171` | 아래 immutable digest로 template 갱신 성공, 기존 command·환경·리소스·identity 보존 |
| Function 오케스트레이터 | `a2843ed9-b6f4-4d06-b90b-16fcac0a229e` | private Storage를 유지한 remote-build OneDeploy 성공, host Running·함수 24개 indexing |
| 비학습 이미지 smoke | `sp500-candidate-training-vzbmfij` | Succeeded, 실제 학습 모듈 hash·20D 전용 정책·성능 비강제·coverage 미달 거부 확인 |

학습 이미지 digest:
`sha256:f0133c29fb79635bb893fdfede88ec7186d11e0bad45dadd1d10b9cb30ca2d7e`.
Job은 변경 가능한 tag 대신 이 digest를 참조한다. 기본 cloud builder의 private ACR
접근이 차단되어 기존 private-network Kudu 경로에서 동일 의존성의 기존 image에
커밋된 코드·설정 layer를 게시했다. registry 공개 접근이나 방화벽은 완화하지 않았다.

10월15·16일 Fusion 후보는 각각 20개와 기존 v1 응답 hash를 유지했고,
설명 API는 각각 `RECORDED`·20개 및 기간검색 증적 5개·10개를 반환했다.
Backend·Function 설정, FC1 host/network, Job의 image 외 template·configuration·identity,
private ACR 정책과 두 App Service의 B2·1 instance가 배포 전과 같음을 확인했다.
DB 크기·데이터, 모델 assignment, 외부 Portal 앱은 이 배포에서 변경하지 않았다.
비학습 smoke는 evaluator만 검증하며 신규 주간 재학습·승격·활성화 E2E를 실행한 것이 아니다.

## 6. 나중에 follow-up할 내용

1. 원본 예측·가격·종목 identity로 Rank IC와 test block 중앙값을 독립 재계산하고
   날짜·label 성숙·분할 조정·중복 제거·coverage를 확인한다.
2. 기존 운영 모델과 20D challenger를 같은 기간·종목·horizon·비용 가정으로 평가한다.
   이번 `no_incumbent` 결과나 서로 다른 기간의 저장 지표를 직접 우열 비교로 쓰지 않는다.
3. 특징·학습 기간·정규화·모델 파라미터 개선은 별도 SHADOW 실험으로 수행한다.
   평균과 block 중앙값을 모두 확인하고 최종 미사용 평가 구간을 보존한다.
4. 사용자가 재활성화를 지시하면 새 version의 20D 정책을 추가하고
   `performance_gates_enabled: true`로 설정한다. 기존 v1/v2 파일을 덮어쓰지 않고
   policy registry와 Backend 기본 version을 함께 변경한다. Job이 새 정책을 지원하도록
   배포한 뒤 신규 run에서 기준 적용을 확인한다.

후속 기록에는 새 run/model ID, 평가 기간·universe·비용 가정, 네 성능 메트릭의
실제 값·기준·차이, 성능 기준 재활성화 승인과 배포 상태를 함께 남긴다.

관련 코드: `analytics/promotion.py`, `analytics/weekly_job.py`,
`backend/app/services/weekly_training.py`, `orchestrator/function_app.py`,
`orchestrator/workflow.py`. 경로의 `analytics`는 `src/sp500_candidate_engine/analytics`다.
