# NOTES.md — 나중에 할 일 (성능 작업과 분리)

성능 리팩터링 중 발견한 것들을 여기에 적는다. **성능 작업 브랜치에서 고치지 않는다.**
전부 판정 결과를 바꾸므로, 회귀 테스트가 깨지면서 성능 변경의 검증이 불가능해진다.

---

## 🔴 P0 — 재시험(Retest) 이력 소실로 `Intermittent` 판정 불가

**상태**: 실측 확인 완료. 사용자 요구사항 확정됨.
**상세**: `CLAUDE.md` §4-b 참조.

### 요약

실제 데이터는 **같은 파일 안에서 동일 Serial # 행이 반복**되는 형태다
(fail 유닛 22개가 각각 4행 = 초기 + 재시험 3회). 그런데 코드는 "재시험 = 별도 파일"
모델이라 `merged_fail_rows` 가 `len(files)==1` 에서 즉시 리턴하고, 파일 내 재시험을
인식하지 못한다.

결과적으로 Bin 은 첫 회차, 측정값은 마지막 회차가 채택되어 **출처가 어긋나고**,
회복 유닛(1회차 fail → 마지막 Bin1)이 `Intermittent` 가 아니라
`Excessive`/`Slight`/`Tail` 로 **오분류되어 벤치(FA) 대상에 잘못 들어간다.**

### 확정된 요구사항

1. 대표 측정값 = **마지막 회차** (현재 동작 유지, 변경 없음)
2. 회복 유닛 = **`Intermittent`** 으로 분류하고 벤치 대상에서 제외

### 고칠 방향

```python
# 같은 파일 내에서 Serial # 기준으로 등장 순서를 보존한 회차 이력을 만든다
history[sample] = [{"bin": ..., "items": {...}, "spec_fail": ...}, ...]

대표값        = history[sample][-1]
bin_sequence  = [h["bin"] for h in history[sample]]
is_intermittent = (not bin_is_pass(bin_sequence[0])) and bin_is_pass(bin_sequence[-1])
```

파일 기반 stage 병합(`merged_fail_rows`)은 다른 사업장 데이터 대비 그대로 두고,
그 위에 "파일 내 재시험" 단계를 하나 더 얹는 방식이 안전하다.

### 검증 방법

- 회복 케이스가 있는 Post 파일을 확보한 뒤(현재 샘플에는 0건), 해당 유닛이
  `Intermittent` 로 나오고 `Need Bench` 대상에서 빠지는지 확인
- 회귀 스냅샷은 이 작업 후 **새로 만든다** (기존 스냅샷과 달라지는 것이 정상)

---

## 🔴 P0 — 통계 정의

| 항목 | 문제 | 조치 방향 |
|---|---|---|
| `sample_std` (tool:43) | 이름은 sample std 인데 실제로는 **모표준편차** (`np.std()` ddof=0 / `statistics.pstdev`) | `ddof` 파라미터화. Excel STDEV·JMP 와 √(n/(n−1)) 배 차이라 재현 불가 |
| `FLAG_LIMIT = 3` (tool:17) | 모표준편차 기준 max\|z\| ≤ √(n−1) 이라 **n ≤ 10 이면 3σ flag 가 수학적으로 불가능**. 반대로 n=3,000 이면 순수 노이즈로도 99.7% 가 flag (실측) | `n < 11` → `INSUFFICIENT N` 표시. 이후 Grubbs/GESD 또는 FDR 보정 |
| Pass/Fail σ 정의 불일치 | Pass 는 `vector_stats`, Fail 은 `sample_std` — 구현이 별개라 경계 동작이 이미 갈라짐 | `stats_core.py` 로 단일화 |
| `diff_ratio` (tool:75) | 분모가 **부호 있는** `pre_value` → pre 가 음수면 열화/개선 부호 반전. `pre ≈ 0` 폭발 방어 없음 | 분모를 `abs(pre)` + 상대 임계 도입 + 절대 shift 병기 |
| `safe_ratio`/`sigma`/`mean` | 분모 0·빈 데이터·n<2 에서 `0.0` 반환 → "정의 불가"가 "정상"으로 둔갑. **σ=0 항목은 어떤 이상치도 절대 flag 안 됨** | `None` 반환 + UI 에 `N/A` / `NOT EVALUATED` |

**§1(payload details 축소)과의 연결**: §1(payload details 축소) 효과는 (전체 항목 수 ÷ SELECT
항목 수)가 상한이다. Test Data 실측: 466 ÷ 295 = 1.58배 (측정 1.5배). SELECT 비율 63%는 3σ 고정
임계의 위양성 때문이며(n=145), 임계를 표본 크기에 맞게 고치면 SELECT 비율이 떨어져 §1 효과도
함께 커진다. → 통계 임계 수정은 정확성 과제이자 성능 과제다.

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

- **Reliability Type 제거** — 폴더명 규칙이 `순번_Ver_Lot_Purpose` 4토막으로 확정.
  드롭다운 삭제. `Reliability Items`(고정 9종)는 유지. → 0단계 이전 작업으로 수행.
- **재시험 대표값** — 마지막 회차 사용 (현재 동작 유지).
- **회복 유닛** — `Intermittent` 로 분류 (별도 작업 필요, 위 P0 참조).
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
  Data 기준 +4%p 늘어 +10% 예산을 넘길 수 있었음). diff 는 post/pre−1 순수 비율이라 population
  선택에 의존하지 않아 §V5 "backend 단일화" 대상이 아니라고 판단함. 단 §S4 에서 `diff_ratio`
  분모가 `abs(pre)` 로 바뀌면 `diffFromPre()`(cdf_compare_web.py:3632)도 반드시 같이 고쳐야
  한다 — 안 그러면 pre 음수 항목에서 그래프 부호가 Detail 테이블과 어긋난다.

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
