# NOTES.md — 나중에 할 일 (성능 작업과 분리)

성능 리팩터링 중 발견한 것들을 여기에 적는다. **성능 작업 브랜치에서 고치지 않는다.**
전부 판정 결과를 바꾸므로, 회귀 테스트가 깨지면서 성능 변경의 검증이 불가능해진다.

**P0 없음 (2026-08-08, §S7 완료 시점)** — 기존 P0 두 건(재시험 이력 소실, 통계 정의)
모두 §S2~S7 로 해결되어 "완료/결정됨"으로 이동함. 상세는 `CLAUDE.md` §11 "통계 판정
규칙"과 `docs/verdict_reports/FINAL.md` 참조.

---

## 🟠 P1 — 파서 강건성

| 항목 | 문제 |
|---|---|
| `read_xlsx` | `<row r>` 무시 → 시트 중간 빈 행이 XML 에서 생략되면 아래 행이 위로 당겨져 **메타데이터 행 매칭이 어긋남** |
| `read_xlsx` | 첫 시트만 읽음. `styles.xml` 미파싱(날짜가 serial number 로). `t="b"`/`t="e"` 미지원 |
| `column_name_to_index` (tool:157) | 알파벳 없으면 `-1` 반환 → `values[-1]` 로 **직전 셀 덮어씀**. 유니코드 문자면 index 폭주 |
| `read_shared_strings` (tool:165) | `.//x:t` 가 `<rPh>`(후리가나) 내부까지 수집 → 문자열 오염 |
| `read_csv` (tool:226) | `cp949` 폴백이 거의 모든 바이트를 디코드 → **모지바케가 조용히 통과**. 구분자 감지 없음 |
| `to_float` (tool:20) | 무조건 `replace(",", "")` → `"1,5"` 가 `15` 로 (10배 오차) |
| 아이템명 중복 | `records[item_name] = []` 가 앞 컬럼 레코드를 **통째로 폐기** |
| 포맷 미인식 | `Test Name` 행을 못 찾으면 **경고 없이** legacy 폴백 → 메타데이터·limits 전부 상실 |

> `fast_datalog.py` 에 위 항목들의 수정본이 이미 구현되어 있다. 3단계에서 파서를
> 교체할 때 함께 반영할 수 있으나, **판정 결과가 바뀌는 항목은 별도 커밋으로 분리**할 것.

---

## 🟠 P1 — 계측 장비 센티널 원시값이 통계에 그대로 섞여 들어간다

`Test Data/SM3502Q/00_MVT0-0_1111_111/01_Post/SM3502Q_RR04_AAA_R017_ROOM_HTOL_1000hrs.CSV`
row 185(`Serial #`=75, `Bin`=17)의 `BUCK_SS` 원시 셀 문자열은 `3.40E+36` (스펙
2.1~3.3 mS 대비 압도적으로 큰 값) — 파서가 만든 값이 아니라 **원본 CSV 파일에 그대로
이렇게 적혀 있음**을 직접 셀 단위로 확인함(§S3 후속, 2026-08-06). 참고로 이전 §S3
보고서/가설에서는 "float32 최대값(3.4028235e38)일 것"이라 짐작했지만, 실측 문자열은
`3.40E+36`으로 float32 최댓값보다 정확히 두 자릿수(100배) 작다 — 계측 장비가 float32
최댓값을 그대로 뱉은 것은 아니고, 다른(아직 특정 못 한) 계측/파싱 단계의 실패 코드일
가능성이 높다. 같은 파일 전체를 스캔한 결과 `3.40E+36` 류의 비정상 값은 이 셀
하나뿐(반복되는 고정 센티널 패턴은 아님).

같은 serial(75)에 대해 데이터 행이 4개 중복 존재하고(182~185), 앞의 3개는 `BUCK_SS`
값이 빈칸이며 마지막 행(185)에만 값이 채워져 있다 — `filter_records_to_last_sample`
로직상 이 마지막 행이 실제 분석에 쓰이는 값이다. 이런 손상값이 통계에 섞이면 그
항목의 mean/sigma 전체가 오염된다(§S3 진단: 이 사례는 `post_sigma=0.0742`로 정상
범위였지만, `fail_type`이 스펙 마진비 체크에 먼저 걸려 "Excessive"로 분류되는 경로라
우연히 σ 오염이 겉으로 드러나지 않았을 뿐 — 다른 항목/사례에서는 여전히 위험함).

**이번에 고치지 않음** — 센티널 값 판정 기준(예: 물리적으로 불가능한 범위를 어떻게
정의할지, 또 다른 센티널 값이 있는지)은 Eden 님 확인이 필요해 리스트업만 해둔다.

---

## 🟠 P1 — Grubbs 검정의 masking: 한 항목에 이상치가 여럿이면 서로를 가린다

Grubbs 는 "이상치 1개" 가정의 검정이라, 한 항목에 이상치가 여럿이면 이상치 자신이
sigma 를 부풀려 서로를 가린다(masking).

실측: 3000 유닛 중 1.5%(45개)를 15~40 sigma 로 심었을 때 sigma 가 3.86배 부풀어,
fixed(3.0) 와 grubbs(4.299) 가 거의 동일한 결과를 냈다.

방향은 과소검출이다. 열화가 광범위한 항목일수록 덜 걸린다.

대안: GESD(반복 제거형 ESD) 또는 robust sigma(median/MAD 기반). GESD 는 상한 r 을
정해야 하고 임계값 표가 별도로 필요하다.

**이번 브랜치에서는 고치지 않는다.** 별도 작업으로 판단.

---

## 🟠 P1 — 항목 필터

`unit_is_allowed` (web:4748): 단위 화이트리스트가 V/A/s/Ω 뿐이고 `DISALLOWED` 매칭이
**부분 문자열**이라 다음이 조용히 제외된다.

- `degC`, `Hz`, `W`, `F`, `%`, `dB`, `ppm` 등
- **단위 행이 없는 항목** (`''` → False)
- **하이픈 포함 단위 전부** (`DISALLOWED` 에 `'-'` 가 있음) — `mV-pp` 등

제외 사유가 UI 어디에도 표시되지 않아, 사용자는 항목이 왜 없는지 알 수 없다.
→ 최소한 `payload['excluded_items']` 로 반환해 "단위 미인식으로 N건 제외" 표시.

---

## 🟡 P2 — 보안 / 운영

| 항목 | 내용 |
|---|---|
| CSRF / DNS 리바인딩 | `Handler` 에 Origin/Host/Referer 검증이 **전혀 없음**. `POST /shutdown` 은 바디 없는 단순 요청이라 임의 웹페이지가 툴을 종료시킬 수 있고, `/browse-data-root` 는 서버 PC 에 tkinter 다이얼로그를 띄움 |
| 요청 크기·타임아웃 | 상한 없음. `Content-Length` 만 크게 보내고 바디를 안 보내면 작업자 스레드 영구 블록 |
| `Handler.log_message` | `return None` — **모든 서버 로그 억제**. 현장 문제 재현 시 단서 zero |
| `DATA_ROOT` | 하드코딩. `Browse` 로 바꿔도 **재시작하면 초기화** → `%APPDATA%` 설정 파일로 영속화. **임시 조치**: `CDFTOOL_DATA_ROOT` 환경변수로 덮어쓸 수 있게 함(web:42, 기본값은 그대로 유지) — 근본 해결(설정 파일 영속화)은 아직 미완 |
| `JOBS` | 완료 payload 를 담고 **아무도 지우지 않음** → 장시간 구동 시 메모리 누적 |

---

## ✅ 완료 / 결정됨

- **[해결] 재시험(Retest) 이력 소실로 `Intermittent` 판정 불가 (§S6/S6b, 2026-08-08)** —
  실제 데이터는 같은 파일 안에서 동일 Serial # 행이 재시험마다 반복되는데(fail 유닛
  22개 × 4행), 코드는 "재시험 = 별도 파일" 모델이라 `merged_fail_rows` 가
  `len(files)==1` 에서 즉시 리턴해 파일 내 재시험을 인식하지 못했다 — Bin/측정값 출처가
  어긋나고, 회복 유닛이 `Intermittent` 대신 `Excessive`/`Slight`/`Tail` 로 오분류되어
  벤치(FA) 대상에 잘못 들어갔다. `stage_history_from_records`/`sample_states_from_history`
  로 물리적 행(`row_index`) 기준 이력을 복원해 해결했다(대표 측정값=마지막 회차는
  유지). 복원 과정에서 "유닛 전체 회복"(Intermittent)과 "개별 항목 flip-flop"
  (Unstable, §S6b 신설)이 원래 같은 문자열로 뭉뚱그려져 있던 것도 분리했다. 실데이터
  검증: 22개 fail 유닛 중 Intermittent 0건(회복 케이스가 실제로 없음), Unstable 2건
  (VSTART Serial 25·62). 상세: `CLAUDE.md` §11-7, `docs/verdict_reports/S6.md`,
  `S6b.md`.
- **[해결] 통계 정의 4건 (§S1~S4, 2026-08-05~08-07)** — `sample_std`(이름은 표본
  표준편차인데 실제론 모표준편차) → `stats_core.std_of(ddof=1)` 전환(§S2). 고정
  `FLAG_LIMIT=3`(n 이 작으면 3σ flag 가 수학적으로 불가능, n 이 크면 노이즈로도 대부분
  flag) → `grubbs_critical(n, alpha)` 기반 임계로 전환(§S3). `diff_ratio` 의 부호 반전
  버그(2026-08-05)와 `pre≈0` 폭발 방어 없음(§S4, `EPS_REL` 게이트로 해결) → 완료.
  `safe_ratio`/`sigma`/`mean` 이 "정의 불가"를 `0.0`으로 반환해 진짜 이상치를 가리던
  문제 → `sigma_is_negligible`/`NOT EVALUATED`(§S3) + 0.0 대신 `None`(§S5)으로 해결.
  이 네 가지가 §S7(grubbs 정확 계산 교체, alpha=0.01 전환)의 전제 조건이었다. 상세:
  `CLAUDE.md` §11, `docs/verdict_reports/FINAL.md`.
- **Reliability Type 제거** — 폴더명 규칙이 `순번_Ver_Lot_Purpose` 4토막으로 확정.
  드롭다운 삭제. `Reliability Items`(고정 9종)는 유지. → 0단계 이전 작업으로 수행.
- **재시험 대표값** — 마지막 회차 사용 (현재 동작 유지).
- **회복 유닛** — `Intermittent` 로 분류 (§S6/S6b 로 구현 완료, 위 항목 참조).
- **§U2(e77440c) 이후 fail_type `Tail` → `Slight` 로 바뀐 2건 (2026-08-04, 골든 재생성 시점)**
  — `BUCK_VREF3V_POST` sample=75 (diff_s=-4.99), `VSTART` sample=73 (diff_s=3.58).
  원인: `fail_type_for_detail()`의 `Slight` 분기는 `|mea_s|>3 AND |diff_s|>3`인데, §U2
  이전에는 Pre 조인이 DEVICE_ID 매칭 실패로 `diff_s`가 항상 `None`이라 이 분기 자체에
  도달이 불가능했음. §U2 가 Pre 조인을 복구하면서 이 두 샘플의 `diff_s`가 처음으로
  계산되어, 원래 있었지만 도달 못 하던 분기가 열린 것 — 새 버그 아님. 의미상으로도
  "스펙 살짝 초과 + 통계적으로 유의한 변화" = `Slight` 가 맞는 분류. 골든 스냅샷(commit
  e77440c 이후, 3d1e1e9 기준)은 이 상태로 재생성함 — 나중에 "왜 Slight 지?" 를 추적할
  근거로 여기 남겨둔다.
- **§V5 readoutDetailSeries() 의 diff 프론트 재계산** — mea_s/diff_s 는 백엔드가 계산한
  `m{n}`/`d{n}` 을 읽기만 하고, `diff` 값만 프론트에서 `diffFromPre(preValue, postValue)` 로
  다시 계산한다. payload bytes 를 아끼기 위한 의도적 선택(백엔드가 diff 까지 내려주면 Perf
  Data 기준 +4%p 늘어 +10% 예산을 넘길 수 있었음). diff 는 population 선택에 의존하지 않는
  순수 비율이라 §V5 "backend 단일화" 대상이 아니라고 판단함. `diffFromPre()`는 `diff_ratio()`
  와 정확히 같은 공식을 써야 하며(현재는 `(post-pre)/abs(pre)`, §S4 완료), 어긋나면 pre 음수
  항목에서 그래프 부호가 Detail 테이블과 반대가 된다.
- **§S4 diff 부호 = 값 이동 방향 (내려가면 -, 올라가면 +)** — 열화/개선 판단은 툴이 하지
  않고 엔지니어가 LL/UL 을 보고 한다. 2026-08-05 결정.
- **[미해결 발견] `readoutDetailSeriesFallback()` 의 ddof=0 프론트 재계산 (§S2 조사 중 발견)**
  — `cdf_compare_web.py` HTML 문자열 내 `readoutDetailSeriesFallback()`(약 3661~3684행)이
  "stale cache" 상황(`series.stats` 가 없을 때, 콘솔에 `has no backend points (stale cache)`
  경고)에서 `mea_s`/`diff_s` 를 클라이언트에서 직접 재계산하는데, 이때 쓰는 `sigmaValue()` →
  `populationStd()`(약 3624~3628행)가 **ddof=0 로 하드코딩**되어 있다. §S2 로 백엔드 판정이
  ddof=1 로 바뀐 뒤에도 이 JS 폴백 경로는 그대로라, stale cache 가 발생하는 드문 경우에 한해
  브라우저가 보여주는 z-score 가 백엔드 판정과 어긋날 수 있다. 위 `§V5` 항목의 "mea_s/diff_s
  는 백엔드가 계산한 값을 읽기만 한다"는 설명은 `series.stats` 가 있는 정상 경로에는 맞지만
  이 폴백 경로에는 적용되지 않는다. **아직 고치지 않음** — HTML 문자열 수정은 §S2 에서
  헤더 라벨 한정으로만 허용되어 로직 변경은 범위 밖. 실제로 이 폴백이 얼마나 자주 발동하는지
  확인 후 별도 단계에서 `ddof=1` 로 맞출지 결정 필요.
- **[발견] `BUCK_SS[fail]` sample 75 는 σ≈0 이 아니라 손상된 원시값이다 (§S3, 2026-08-06)**
  — §S3 착수 배경이었던 가설("σ≈0 이라 3σ 판정이 무의미해지는 사례")을 검증하려고 직접
  뜯어봤더니, 이 샘플의 `post_value=3.4e+36`(스펙 2.1~3.3 mS)은 계측/파싱 단계에서 생긴
  손상값이고 `post_sigma=0.0742`(정상 범위)이라 σ≈0 케이스가 전혀 아니었다. `fail_type`이
  `"Excessive"`로 정확히 분류되는 것도 스펙 마진비 체크가 Grubbs 체크보다 먼저 걸리기
  때문. 항목 단위 `"result"`는 fail 모드에서 "스펙 아웃이 한 번이라도 있으면 SELECT"라는
  무조건 규칙이라 이 항목 자체가 `NOT EVALUATED` 로 바뀌는 일도 없다(설계상 의도된 동작,
  버그 아님). `sigma_is_negligible`/`NOT EVALUATED` 가드 자체는 정상 작동함 — 다만 이
  특정 사례에 적용될 사례가 아니었다는 뜻. 손상값 방어(예: 물리적으로 불가능한 범위의
  원시값을 파싱 단계에서 걸러내는 것)는 §S3 범위 밖의 별개 과제.
- **[발견] `Perf Data` 는 diff_s 가 항상 30~50 대라 Grubbs 임계 상향(3.0→4.3)으로도 항목별
  SELECT 총계가 안 줄어든다 (§S3, 2026-08-06)** — mea_s 만 놓고 보면 Grubbs 도입 효과가
  뚜렷하다(999개 중 mea_s>threshold 인 항목이 999→45로 급감, 의도한 대로 동작). 하지만
  항목별 `"result"`는 mea_s/diff_s 중 하나라도 SELECT 면 SELECT 인데, `diff_s`는 999개
  항목 전부 30~50대 값을 가져서(threshold 4.3보다 한 자리 위) 고정 임계(3.0) 때든 Grubbs
  임계(4.3) 때든 상관없이 전부 SELECT 로 남는다. `tools/make_perf_fixture.py`가 Pre/Post
  값을 항목별로 **완전히 독립적인** `rng.gauss(0.0, 1.0)`로 생성하기 때문으로 보이며(실제
  계측 데이터의 pre/post 상관관계를 흉내내지 않음), diff_s 계산 로직 자체는 §S3 에서
  건드리지 않았고 fixed/grubbs 모드에서 diff_s 값이 동일함을 확인함 — §S3 구현 버그가
  아니라 벤치마크 전용 합성 데이터(회귀 검증에 안 쓰는 이유가 바로 이거)의 성질. 실제
  계측 데이터(Test Data)에서는 SELECT 289→223으로 정상적으로 감소함.
- **[발견] Grubbs 도입으로 `calculate_results_vectorized` 가 2.3배 느려짐 (§S3, 2026-08-06)**
  — `bench.py --data-root "Perf Data" --repeat 3` 재측정 결과 TOTAL(median) 이 209.5s→
  241.2s(+15.1%)로 늘었다. payload 크기·행 수는 SELECT 총계가 안 바뀌어 거의 그대로지만,
  `calculate_results_vectorized` 구간만 27.9s(13.3%)→65.1s(27.0%)로 2.3배 늘었다. 항목마다
  `grubbs_table` 보간으로 임계값을 계산하는 비용(고정 상수 3.0 비교 대신)이 999개 항목 ×
  n≈2910 규모에서 누적된 것으로 보임. §S3 요구 범위 밖이라 최적화하지 않았고 그대로 둠 —
  다음에 이 구간을 만지게 되면(예: `threshold_for` 결과를 n 별로 캐싱) 참고할 것.
- **§S0 `tools/verdict_diff.py` 의 알려진 제약 3가지** (docstring 에도 있지만 다음 세션에서
  놓치기 쉬워 여기에도 남긴다):
  1. fail 모드 `device_id` 는 항상 `None` — `analyze_fail_to_json()` 이 `app.post_records`
     를 `{}` 로 비워두는 게 설계이고, device_id 를 담은 원본 per-sample 레코드는 그 함수
     내부 지역 변수라 payload/app 어디로도 노출되지 않는다. 기존 소스를 고치지 않는 한
     복구 불가.
  2. fail 모드 item 단위는 "스펙 아웃이 한 번이라도 있던 항목"만 존재한다 — pass 모드의
     `app.post_items`/`payload["results"]` 같은 "전체 항목" 개념이 fail 모드엔 없다
     (`analyze_fail_to_json` 자체가 스펙 통과 항목을 결과에 안 담기 때문).
  3. ~~SELECT 임계값은 아직 고정 `FLAG_LIMIT=3` 하나뿐이다. §S3 에서 항목별(n별) Grubbs
     임계로 바뀌면, verdict_diff.py 리포트 4번 항목("SELECT 에서 빠진 항목")의 임계값
     표시를 지금의 단일 숫자에서 항목별 threshold 참조로 넓혀야 한다.~~ **예견대로 발생함
     (§S3, 2026-08-06)**: `docs/verdict_reports/S3.md` 4번 항목이 "현재 임계값=3.0" 이라고
     찍는데 실제로는 항목별 Grubbs 임계(n=57 → 3.1799)가 쓰였다 — 표시만 stale, 판정 로직
     자체는 정확함(전이 행렬로 확인). `verdict_diff.py:344` 의 `getattr(web, "FLAG_LIMIT", 3.0)`
     참조를 항목별 threshold 로 바꾸는 건 여전히 두 파일 편집 범위 밖이라 손대지 않음.
  4. **[발견, 2026-08-10] `tests/verdict_base/` 가 현재 HEAD 대비 stale** — 코드 변경 없이
     그대로 `verdict_diff.py --baseline tests/verdict_base/` 를 돌려도 SELECT 299→143 등
     대량 차이가 난다(§S3 Grubbs 전환 이후 baseline 미갱신으로 추정). Fail 모드 `over_sigma`
     추가 작업 검증 시 `--save` 로 새 baseline 을 즉석 생성해 전/후 비교로 우회함. 이 baseline
     자체를 최신 HEAD 로 재저장할지는 범위 밖이라 결정 필요.

---

## 📝 §1 성능 측정 — bench.py "10배 감소" 기준 미달 사유

**상태**: §1(payload_with_items/save_cached_analysis/progress 슬림화) 구현 완료, regression_check
PASS, API 동작(진행 슬림화·`/item` 지연 로딩) 실 서버로 확인. 단 완료 기준의 "json.dumps 시간·
payload 크기 10배 이상 감소"는 실측 Test Data 로는 **1.5배 수준에 그침** (미달, 사용자 확인 후
그대로 커밋).

**원인 (코드 버그 아님, 이 데이터셋의 특성)**

1. §7 기준선(json.dumps 12.5s / 839MB)은 "항목 1,000×유닛 3,000(26MB CSV)" 스케일 실측이고,
   실제 `Test Data/SM3502Q/00_MVT0-0_1111_111` 콤보는 항목 466개·유닛 145개뿐이라 애초에
   json.dumps 가 0.1초 미만이었음. 절대적인 개선 여지가 크지 않은 규모.
2. `selected_summary`(SELECT 항목)가 466개 중 295개(63%)로 이례적으로 많음. `payload_with_items`
   가 SELECT 항목만 만들어도 SELECT 자체가 압도적 다수라 절감폭이 작음. 이건 위 "P0 — 통계 정의"의
   `FLAG_LIMIT=3` 문제(n 작으면 3σ flag 가 수학적으로 불가능한 반대급부로, 실측 규모에서는 노이즈만
   으로도 다수가 flag)와 같은 뿌리로 보임 — 성능 브랜치 범위 밖이라 손대지 않음.
3. `save_cached_analysis` 가 §1 프롬프트 4번 지시대로 SELECT 되지 않은 나머지 항목의 상세도 전부
   디스크에 캐시하므로(`/item` 지연 로딩용), `payload_with_items` 가 덜어낸 계산 비용이 캐시 쓰기
   단계로 옮겨갈 뿐 없어지지 않음. 실측(같은 콤보, stash 전/후 비교): TOTAL 12.404s → 13.743s로
   총 처리시간은 오히려 소폭 증가. **체감 속도 개선은 §4(요약 먼저 push) 없이는 안 됨.**

**실측 수치 (Test Data, item 466/selected 295, repeat 3 median)**

| 구간 | 전 | 후 |
|---|---:|---:|
| json.dumps | 0.094s | 0.061s |
| payload bytes | 7,743,985 | 4,989,494 |
| payload_with_items | 8.108s | 4.985s |
| cache write | 0.768s | 5.286s |
| TOTAL | 12.404s | 13.743s |

**§7 기준선 규모(1,000×3,000)의 실 데이터가 확보되면** 그 경로로 bench.py 를 재실행해 10배 기준
재검증 권장.

---

## 📝 §2 성능 측정 — 파싱 캐시 콜드/웜 실측 및 bench.py 계측 사각지대

**같은 조건(SM3502Q/MVT0-0/1111/111/HTOL/1000hrs/Room) 연속 2회 분석**
(analyze_condition 단독 측정, 서버 미기동, 함수 직접 호출):
콜드(파싱 캐시 미스) 5.475s → 웜(파싱 캐시 히트) 4.6875s, **1.17배**.
pass+fail 동시 실행 시 Pre/Post 각각 정확히 1회씩만 실제 파싱됨(read_table 실호출 횟수로 확인,
중복 파싱 없음).

1.17배가 낮아 보이는 이유는 파싱 캐싱 효과가 작아서가 아니라, 측정 범위(analyze_condition 전체)에
`payload_with_items`(~4.6s, SELECT 항목 상세)와 `save_cached_analysis`(~4~4.5s, 비-SELECT 포함 전
항목 상세 디스크 캐시 — §1 항목 참조)처럼 파싱과 무관하고 캐싱으로 줄지 않는 구간이 함께 섞여
희석됐기 때문. 같은 프로세스 안에서 콜드→웜을 구간별로 나눠 측정(bench.py 표준 4구간 +
`load_parse_cache`/`raw_item_records` 추가 계측)하면:

| 구간 | 콜드 | 웜 | 차이 |
|---|---:|---:|---:|
| read_table | 0.1327s | 0.0000s | 0.1327s |
| extract_item_records | 2.0251s | 0.0000s | 2.0251s |
| filter_records_to_last_sample | 0.0021s | 0.0017s | 0.0004s |
| calculate_results_vectorized | 0.1067s | 0.1111s | -0.0044s |
| load_parse_cache | 0.0002s | 0.9212s | -0.9211s |
| raw_item_records(전체) | 2.7253s | 0.9215s | 1.8038s |
| analyze_condition(전체) | 3.8830s | 1.8469s | 2.0361s |

**bench.py 계측 사각지대**: `tools/_regression_lib.py` 의 `INSTRUMENTED_FUNCS` 에 `load_parse_cache`
(디스크 npz+pickle 로드 + 레코드 역직렬화)가 빠져 있음. 웜 실행에서도 이 구간이 0.92s 나 걸리는데
bench.py 표준 4구간 표에는 전혀 안 잡혀 `read_table`+`extract_item_records` 만 0 이 되는 걸 보고
"파싱이 3.06s(=0.13+2.93, 단발 콜드 측정치) 통째로 없어졌다"고 오인하기 쉬움. 실제로 콜드→웜에서
없어지는 건 `raw_item_records` 기준 1.80s(디스크 캐시 로드 비용 0.92s 는 여전히 남음) 뿐이라,
이 사각지대를 모르면 파싱 캐싱 효과를 과대평가하게 된다. → bench.py 에 `load_parse_cache` 계측
추가 권장(성능 브랜치 범위 밖이라 이번엔 손대지 않음).

read_table 실호출 횟수(Pre/Post 구분): 콜드 pre=1·post=1, 웜 pre=0·post=0
(디스크 캐시가 완전히 대체함, 실측 확인).

---

## ✅ 완료 — `pre_pass_samples` 센티널 재계산 버그 (payload_with_items 94% → 8%)

**상태**: 수정 완료, `Test Data`/`Perf Data` 양쪽 regression_check PASS.

### 원인

`make_app()` (web.py, `analyze_to_json` 경로) 이 `app.pre_pass_samples` 에
`PASS_SAMPLE_IDS_AUTO` 센티널을 그대로 넣어뒀다. `pre_cdf_values_for_item()` 이
이 센티널을 만나면 `pass_sample_ids_from_records(pre_records)`(Pre 전 항목 × 전
레코드 순회)를 실행하는데, 이게 `item_to_json()` 을 통해 **항목마다** 반복 호출됐다
— 항목 수 × pre 레코드 수 규모 재계산.

**수정**: `make_app()` 에서 `app.pre_pass_samples` 를 pre/post 필터링 뒤 **한 번만**
실제 값으로 채움 (`pass_sample_ids_from_records(app.pre_records) if include_pre else
None`). `None` 은 "bin 데이터 없음 = 필터 안 함"이라는 유효값이라 센티널과 구분해
그대로 저장.

### 벤치마크 하네스에도 같은 패턴이 숨어 있었음

`tools/_regression_lib.py` 의 `analyze_condition()` 이 `analyze_to_json()` 리턴 직후
`app.pre_pass_samples` 를 **무조건** 센티널로 재덮어쓰고 있었다 (`analyze_fail_to_json()`
의 app 은 이 속성 자체가 없어 `tk.Tk.__getattr__` 무한재귀 방지용으로 필요했던 코드).
그래서 위 소스 수정 후 `bench.py` 를 돌려도 하네스가 즉시 되돌려놔서 개선이 측정되지
않았다 (1차 재측정: `payload_with_items` 951.637s, 수정 전 866.651s 와 사실상 동일 —
이 시점엔 원인 미상으로 기록만 하고 넘어갈 뻔함). `app.__dict__` 에 이미 값이 있을 때만
건너뛰도록 수정(`hasattr()` 은 같은 재귀를 다시 유발하므로 `"pre_pass_samples" not in
app.__dict__` 로 직접 확인)한 뒤에야 실제 효과가 드러남.

### 실측 (Perf Data, 항목 999 · Post 유닛 3,000 · Pre 유닛 9,000, repeat 1)

| 구간 | 수정 전 (하네스 버그로 가려짐) | 수정 후 |
|---|---:|---:|
| payload_with_items | 951.637s (93.4%) | **4.740s (8.0%)** |
| calculate_results_vectorized | 12.330s | 6.679s |
| json.dumps | 10.424s | 9.403s |
| cache write | 28.784s | 25.791s |
| **TOTAL** | **1019.301s** | **59.609s** |

`payload_with_items` 약 200배, TOTAL 약 17배 감소. `Test Data`/`Perf Data` 양쪽
regression_check PASS (판정 결과 불변 확인, 순수 성능 수정).

새 병목은 `cache write`(25.8s, 43.3%) → `json.dumps`(9.4s, 15.8%) →
`calculate_results_vectorized`(6.7s, 11.2%) 순으로 이동. 이번 작업 범위 밖이라
손대지 않음.

---

## 🟡 P3 — 기능 판단 필요 (사용자 결정 대기)

- **[발견, W3-1] `.summary-panel`(Abnormal Shift Items 표)이 두 해상도 모두에서 데이터 행 0개** —
  지정된 6개 CSS(특히 `.panel min-height 260→150px`)만 정확히 적용한 결과, 범위 밖인
  `.summary-panel{flex:1 1 0}` vs `.detail-panel{flex:2 1 0}` 비율과 summary-panel 내부
  크롬(제목+Fail/Pass 탭+항목/샘플 서브탭+sticky 헤더)이 축소된 높이 예산을 거의 다 소진해
  tbody 가 들어갈 공간이 남지 않음(table-wrap 실측 높이 ~40px). 1920×1080/1600×900,
  조건 영역 접힘/펼침 4가지 조합 모두 동일 증상. flex 비율 조정 없이는 해결 불가 → 사용자 결정 필요.

- **[발견, W3] Fail 모드 total_analysis payload 는 `item_counts` 를 채우지 않는다** —
  `analyze_total_combo()` 에서 `item_counts` 설정이 pass 모드 분기(`else`)에만 있고 Fail
  모드 분기엔 없음. 시험 항목 탭의 "0건 탭 접기"(W3-6)는 `item_counts` 부재 시 아무것도
  접지 않게(모든 탭 표시) 만들어 안전하게 우회했지만, 근본적으로 Fail 탭에서는 항목별
  select/total 배지 자체가 빈 채로 남는다. §5-6 범위 밖이라 이번엔 고치지 않음.

- **Reliability Items 가 파일을 보지 않는다** — `RELIABILITY_ITEMS` 고정 9종을 항상 반환해서,
  Post 폴더에 HTOL 파일밖에 없어도 HAST/TC 를 고를 수 있고 고르면 Read-out 이 빈 채로 막힌다.
  → Post 파일명에서 실제 존재하는 항목만 뽑도록 바꿀지 결정 필요.

| 항목 | 내용 |
|---|---|
| **Wafer Map** | `waferPositionForSample` 이 샘플번호 mod 12 로 만든 **가짜 좌표**. 모든 다이를 "Good" 으로 칠하는데 범례에는 "Fail/Good/Edge/No Die" 라고 표시됨 → 실제 X/Y Coord 를 쓸 것인지, 아니면 오독 방지를 위해 숨길 것인지. **데이터에 XCoord/YCoord 컬럼이 실제로 존재함** |
| **PPF 차트** | 실측 분포가 아니라 정규분포 가정 PDF 곡선만 그림. 이름과 내용이 불일치 |
| **Fail 오버레이** | `selectedFailItemData()` 가 `return null` 스텁 → 관련 시각화 60여 줄이 죽어 있음. 되살릴지 삭제할지 |
| **`needBench` 체크박스** | 메모리에만 존재. 새로고침으로 소실, 서버 전송 없음, Raw Export 미포함. **triage 결론이 휘발됨** → 영속화하거나 UI 에서 제거 |
| **미구현 화면** | Dashboard / ISO 26262 / 8D Report / Settings — 사이드바에만 있고 내용 없음. 로드맵에 남길지 내릴지 |
| **`empirical_cdf`** | 플로팅 포지션 `i/n` → 최상위 점이 항상 100% 라 확률지·분포적합 불가. Median rank `(i−0.3)/(n+0.4)` 권장 |

---

## 데이터 관련 메모

- 조건 폴더명은 **언더바 3개**(`순번_Ver_Lot_Purpose`). 예) `00_MVT0-0_1111_111`
  (Reliability Type 필드를 제거하는 작업을 0단계 이전에 완료한 상태 기준)
- Post 파일명은 `..._<온도코드>_..._<신뢰성항목>_<리드아웃>.csv` 형식.
  온도코드는 `RR`/`ER`=Room, `RH`/`EH`=Hot, `RC`/`EC`=Cold. **`RT` 는 인식 안 됨.**
- 확장자 대문자(`.CSV`)는 정상 처리된다.
- 검증용 데이터에 **회복 케이스(1회차 fail → 마지막 Bin1)가 0건**이다.
  `Intermittent` 작업 전에 회복 케이스가 있는 파일을 확보해야 한다.

### 회귀 검증 범위 (regression_check.py)
골든 스냅샷은 payload 의 results / selected_summary / over_sigma / items 4개 키만 저장한다.
summary_counts / sample_counts / item_counts / excluded_items 는 비교 대상이 아니다.
→ 요약 스트립 숫자와 시험항목 탭 배지가 깨져도 regression_check 는 PASS 한다.
   해당 값은 화면 확인 또는 별도 스냅샷 항목 추가로 검증해야 한다. (P3 백로그)
