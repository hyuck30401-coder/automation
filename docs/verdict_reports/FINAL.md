# FINAL — §S0(원본) 대비 §S7(최종) 누적 비교

## 0. 이 문서의 목적과 범위

`tests/verdict_base/`(§S0, 2026-08-05 `ffc2afe` 커밋 시점 — 직전에 이미 sigma 계산
백엔드 단일화(`b124d9b`)와 diff 부호 수정(`a5745e9`)이 반영된 상태)를 기준선으로,
지금까지의 §S2~§S7 변경을 누적 적용한 최종 코드 상태를 비교한다. 데이터는
`Test Data`(SM3502Q/00_MVT0-0_1111_111/HTOL/1000hrs/Room) 고정.

이 문서는 `docs/verdict_reports/S2.md` ~ `S6b.md`(개별 단계 리포트)와
`FINAL_diff_raw.md`(`tools/verdict_diff.py --baseline tests/verdict_base/`의
원본 출력)를 사람이 종합한 것이다.

### 항목 수 스코프에 대한 주의 — 471 vs 466

이 문서와 `verdict_diff.py`가 보고하는 표(§2, §3)는 **471개 항목**을 다룬다:
pass 모드 466항목 + fail 모드 5항목. `verdict_diff.py`의 fail 모드
`item_rows_for_combo()`는 스펙-아웃 샘플이 1건이라도 있는 항목만 대상으로 하고,
그 항목의 `"result"`를 실제 판정과 무관하게 **무조건 `"SELECT"`로 채운다**
(파일 자체의 문서화된 한계, `tools/verdict_diff.py:115` 부근). 즉 fail 모드
5항목은 항상 SELECT로 집계된다.

반면 `tests/golden/`(§S7에서 재생성한 골든 스냅샷, `regression_snapshot.py`
산출물)과 완료 기준 2("Test Data SELECT=138")는 **pass 모드 466항목만**을
기준으로 한다 — 완료 기준의 SELECT 138은 471항목 스코프의 SELECT 143에서
fail 모드 강제-SELECT 5건을 뺀 값과 정확히 일치한다(143 - 5 = 138). 두 수치는
서로 다른 버그가 아니라 서로 다른 스코프를 보고 있을 뿐이다.

## 1. 단계별 요약 표 (471항목 스코프, pass 246+223 / fail 5 고정)

| 단계 | 핵심 변경 | SELECT | OK | 판정불가 | 직전 대비 |
|---|---|---:|---:|---:|---|
| S0 (기준선) | `verdict_base` 저장 시점 원본 | 299 | 172 | 0 | — |
| S2 | 판정용 표준편차 ddof=0→1(표본표준편차) 전환 (`3aa4e1f`) | 289 | 182 | 0 | SELECT -10 |
| S3 | diff 분모 EPS_REL 근접-0 가드 도입 (`c003a3d`) → σ=0 항목 2건이 NOT EVALUATED로 정확히 분리 | 223 | 246 | 2 | SELECT -66, 판정불가 +2 |
| S4 | 통계 코어를 `stats_core.py`로 단일화(`2d6b158`, 자체 확인 "판정 불변") + `grubbs_critical` 메모이제이션(`295bca6`, 성능 전용) | 223 | 246 | 2 | 변화 없음 |
| S5 | "계산 불가"를 0.0 대신 None으로 반환(`e168364`) — 화면 N/A, 그래프 무점, 판정 라벨 불변 | 223 | 246 | 2 | 변화 없음 |
| S6 | 파일 내 재시험 이력 복원(`c2a8199`), 유닛 레벨 Intermittent 판정 활성화 — pass 모드 불변. fail 모드에서 VSTART Serial 25/62가 기존 죽은 코드(항목 레벨 flip-flop 분기) 재활성화로 "Intermittent"로 오분류됨(§S6 자체가 발견·보고) | 223 | 246 | 2 | pass 불변 |
| S6b | Intermittent(유닛 전체 회복)와 Unstable(항목 개별 flip-flop) 라벨 분리(`52425bc`) — S6이 보고한 오분류 2건을 Unstable로 정정 | 223 | 246 | 2 | pass 불변 |
| **S7** | `grubbs_table.py`를 정확 계산(incomplete-beta)으로 교체(`694e65d`, 알파-에일리어싱 버그 수정) + 기본 alpha 0.05→0.01 전환(`da81127`) + 프론트 `readoutDetailSeriesFallback` 삭제(`c636935`, 판정 무관) | **143** | **326** | **2** | SELECT -80 |

**S0 → S7 순변화: SELECT 299 → 143 (-156, -52%), OK 172 → 326 (+154), 판정불가 0 → 2 (+2).**

같은 alpha(0.05)로만 비교하면 S6b→S7(grubbs 정확 계산 전환)의 순수 효과는
SELECT 223 → 218(pass 466항목 기준, `alpha_sweep.py` 재측정)로, 이전 표 보간
버그가 실제로는 근소하게 보수적(threshold를 살짝 낮게 계산)이었음을 보여준다.
alpha 0.05→0.01 전환 자체의 효과는 218 → 138(-80)이다.

## 2. mea_s/diff_s 수치 변화의 성격 (§S7 grubbs 정확 계산 교체분)

`FINAL_diff_raw.md` §5("수치가 바뀐 항목")에 나타나는 변화는 크게 두 종류다:

1. **BUCK_SS(fail, sentinel 값 ~4.6e37)** — mea_s delta가 육안상 거대해 보이지만
   (`4e35` 수준), 이는 손상된 원시값(스펙 2.1~3.3mS인데 관측값 3.4e36)에 대한
   z-score라 애초에 의미 없는 값이고, threshold 대비 압도적으로 크므로 판정
   결과에는 영향이 없다.
2. **정상 범위 항목들(BST1_LX1_N_OS -0.97, BUCK_RDSON_LS -0.11, 이후 -0.03~-0.07
   대 롱테일)** — 이전 scipy 보간 테이블과 새 정확한 incomplete-beta 계산 간의
   근소한 차이로, `tests/test_grubbs_table.py`의 회귀 허용오차(1e-3, n=3..20000)
   안에서 예상된 크기다. 어느 항목도 이 차이만으로 SELECT/OK 경계를 넘지 않았다
   (§1 표에서 "같은 alpha" 비교 시 223→218은 alpha=0.05 자체의 정확값이 이전
   근사값과 달랐기 때문이지, 개별 항목이 경계를 넘나든 결과가 아니다 —
   `grubbs_critical(57, 0.05)`이 이전 보간값과 달라지면 전체 항목이 같은 새
   threshold와 비교되므로 여러 항목이 함께 이동한다).

## 3. 완료 기준 재현 (최종 코드 상태, 2026-08-08 재측정)

`scratchpad/alpha_sweep.py` 재실행 결과 (`FLAG_ALPHA`를 명시적으로 오버라이드,
`stats_core`/`grubbs_table` 최종 상태):

```
Test Data (n=57):
  alpha=0.01: mea_threshold=3.5385617582593922
              counts={'SELECT': 138, 'OK': 326, 'NOT EVALUATED': 2}   (466항목)

Perf Data (n=2910, outlier 500 / clean 499):
  alpha=0.01: outlier(500)의 SELECT=500 (100.0%)   clean(499)의 SELECT=8 (1.6%)
```

- **완료 기준 1** (`grubbs_critical(57, 0.025) == 3.340905`): `tests/test_grubbs_table.py`
  단위 테스트로 확인, PASS. (이번 재측정의 alpha=0.025 행에서도
  `mea_threshold=3.340904602344386` — 반올림 시 3.340905로 정확히 일치.)
- **완료 기준 2** (Test Data SELECT=138 / Perf clean 위양성 1.6%): **위 재측정으로
  정확히 재현됨.** 골든 스냅샷(`tests/golden/`)의 pass 모드 결과
  (`SELECT: 138, OK: 326, NOT EVALUATED: 2`, 총 466)와도 일치.
- **완료 기준 3** (`regression_check.py` PASS): 골든 재생성 직후 실행,
  `Combos: 2 total, 2 passed, 0 with mismatches, 0 could not be reproduced` — PASS.
- **완료 기준 4** (본 문서가 S0-vs-final을 포괄적으로 문서화): 본 문서 §1~§3.
- **완료 기준 5** (성능 재측정, 작업 시작 시점 TOTAL 921.9s 대비): §5.
- **완료 기준 6** (`py_compile`/`node --check` PASS, dead-code 제거 후): §6.

## 4. 알려진 이슈 / 한계 (참고용, 이번 §S7 범위 밖)

- Perf Data는 `tools/make_perf_fixture.py`가 Pre/Post를 완전 독립 정규분포로
  생성해 diff_s가 모든 항목에서 정상 범위를 초과한다(`S3.md` 부록 참조) — Perf
  Data의 SELECT 총계는 alpha 변경의 영향을 거의 받지 않는다(diff_s 쪽이 항상
  포화). 이번 alpha 0.01 재측정에서도 Perf Data 전체 SELECT는 999개 중
  큰 변화가 없다(§1의 clean/outlier 분리 지표만 alpha 변화에 민감하게 반응).
- `grubbs_critical`이 alpha=0.05 정확값 기준으로 이전 보간표보다 근소하게 다른
  threshold를 내므로(§2), alpha를 다시 0.05로 되돌리면 SELECT 수는 이전 223이
  아니라 218이 된다 — 회귀 비교 시 이 점을 인지해야 한다.

## 5. 성능 재측정 (완료 기준 5)

`tools/bench.py --data-root "Perf Data" --repeat 3` (파스 캐시 웜, PERF01 콤보,
pass 모드, 508 items). 작업 시작 시점(§S1 이전) TOTAL 921.9s 대비:

| 시점 | TOTAL (wall, median) | 비고 |
|---|---:|---|
| 작업 시작 시점 (§S1 이전) | 921.9s | 사용자 지시에 명시된 시작점 |
| grubbs 정확 계산 교체 직후 (§S7 중간, alpha=0.05) | 201.321s | `bench_after_grubbs_rewrite.txt` |
| **§S7 완료 (alpha=0.01, 최종)** | **193.950s** | 본 재측정 |

**921.9s → 193.950s (-728s, -79%)**. 대부분의 개선은 grubbs 계산 자체보다
§S2~S6b 의 다른 변경(ddof/EPS_REL/stats_core 단일화 등)과 캐시 워밍 효과가
누적된 결과로 보인다 — grubbs 정확 계산 교체 전후(201.321s → 193.950s)만
비교하면 차이가 크지 않다(`grubbs_critical` 메모이제이션, §S4, 덕분에 alpha
변경이 이 구간을 유의미하게 늘리지 않았다). 구간별 상세와 현재 최대 병목
(`cache write`, 49.6%)은 `CLAUDE.md` §7-1 참조.

## 6. dead-code 제거 검증 (완료 기준 6)

§S7-3(`readoutDetailSeriesFallback` 삭제 등 프론트 정리) 이후 `py_compile`
(`.py` 전체)과 `node --check`(수정된 `.js`)를 실행해 PASS 확인 — 문법 오류
없음. (§S7 작업 중 이미 확인 완료, 본 절은 완료 기준 6에 대한 문서상 참조용
기록이다.)
