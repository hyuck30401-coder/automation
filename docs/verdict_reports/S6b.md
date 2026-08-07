# §S6b — Intermittent / Unstable 라벨 분리

## 0. 문제

§S6 에서 재시험 이력을 복원하면서, `fail_type_for_detail` 안에 있던 **항목(item)
레벨** flip-flop 분기(`initial_failed` 이고 중간 회차에 그 항목이 spec pass 를
찍은 적 있으면 반환)가 부수적으로 재활성화됐다 (§S6 §3-3 에서 이미 disclosed).
이 분기는 "유닛 전체가 회복했는가"(요청하신 Intermittent 정의, `bin_sequence`
기준)와는 다른 질문("이 항목이 개별적으로 흔들렸는가")에 답하는 로직인데,
둘 다 같은 문자열 `"Intermittent"`를 반환하고 있었다. 실데이터에서 VSTART
Serial 25/62 가 바로 이 케이스 — 두 유닛 다 최종 Bin 이 fail 인데도
"Intermittent"로 잘못 라벨링됐다.

## 1. 구현 내용

### 1-1. `fail_type_for_detail` 분기 분리 + 우선순위 명시 (완료 기준 요구 1, 2)

`unit_recovered` 파라미터(기본값 `False`)를 추가하고, 함수 맨 앞에서 분류
우선순위를 주석으로 명시했다:

```python
def fail_type_for_detail(
    initial_record, history, value, lower_limit, upper_limit, mea_s, diff_s,
    n, sigma, mean, diff_n=None, diff_sigma=None, diff_mean=None,
    mea_threshold=_UNSET, diff_threshold=_UNSET, unit_recovered=False,
):
    # 분류 우선순위(암묵적이던 순서를 명시): Intermittent -> Unstable -> Excessive ->
    # Slight -> Tail. §S6b.
    #   Intermittent: 유닛 레벨. 1회차 fail, 마지막 회차 Bin pass (unit_recovered ==
    #     state["is_intermittent"], bin_sequence 기준) -- 유닛이 최종적으로 살아났으므로
    #     벤치(FA) 대상에서 제외한다.
    #   Unstable: 항목(item) 레벨. 유닛은 최종 fail 이지만 이 항목의 회차별 spec_status 가
    #     fail -> pass -> fail 로 오간다 -- 스펙 경계에서 불안정하다는 신호라 벤치 대상,
    #     오히려 주목해야 한다.
    # 유닛이 회복했다면(unit_recovered) 그게 더 상위 사실이므로 Intermittent 가 우선이고,
    # 이 항목이 개별적으로 flip-flop 했는지는 더 따지지 않는다(Bin pass 는 그 회차의 모든
    # 항목이 스펙 안이라는 뜻이라 항상 참이 된다).
    if unit_recovered:
        return "Intermittent"
    initial_failed = initial_record is not None and spec_status(
        initial_record.get("value"), initial_record.get("lower_limit"), initial_record.get("upper_limit")
    ) in ("low", "high")
    if initial_failed:
        for stage_index, record in history:
            if stage_index == 0:
                continue
            if spec_status(record.get("value"), record.get("lower_limit"), record.get("upper_limit")) == "pass":
                return "Unstable"
    if spec_margin_ratio(value, lower_limit, upper_limit) >= 0.01:
        return "Excessive"
    # ... (이하 Slight/Tail 판정, 변경 없음)
```

유닛 레벨 판정은 이미 §S6 이 계산해 둔 `state["is_intermittent"]`
(`bin_sequence` 기준, 1회차 fail && 마지막 회차 pass)를 그대로 재사용한다 —
새 상태 계산을 추가하지 않았다. 항목 레벨 flip-flop 판정 로직 자체는 §S6 과
동일(메커니즘 변경 없음), 반환 문자열만 `"Intermittent"` → `"Unstable"`로
바뀌었고, `unit_recovered` 가 `False`일 때만 도달한다.

### 1-2. 호출부 wiring

`analyze_fail_to_json`의 항목별 detail 생성 루프에서 이미 스코프에 있는
`state`(= `sample_states[sample]`)로부터 그대로 넘긴다:

```python
"fail_type": fail_type_for_detail(
    initial_record, history, value, lower, upper, mea_s, diff_s,
    n_pass, post_sigma, post_mean,
    diff_n=len(pass_diff_values), diff_sigma=diff_sigma, diff_mean=diff_mean,
    mea_threshold=mea_threshold, diff_threshold=diff_threshold,
    unit_recovered=bool(state.get("is_intermittent")),
),
```

### 1-3. UI / Excel (완료 기준 요구 3)

`Spec.-Out Type` 열(웹 UI)과 Excel export 둘 다 `fail_type` 문자열을 허용
목록 없이 그대로 통과시키는 구조라, 새 값 `"Unstable"`도 코드 변경 없이
동일하게 렌더링된다 — 확인만 하고 손대지 않았다.

- 웹 UI: `detailSpecOutType(row)` (`cdf_compare_web.py:3511`) —
  `if (row.fail_type) return row.fail_type;` 로 그대로 반환. 하드코딩된
  `"Intermittent"` 문자열 비교/필터는 JS 쪽에 없음 (벤치 제외는 서버 쪽
  `fail_samples`/`is_intermittent` state 필터로 이미 처리되고, `fail_type`
  문자열 매칭에 의존하지 않는다).
- Excel export: `export_detail_rows()` (`cdf_compare_web.py:7537`) —
  `detail.get("fail_type", "")` 를 그대로 셀에 기록.

## 2. 검증 — 단위 테스트 (합성 픽스처)

`tests/test_retest_history.py`에 신규 유닛 2개(S5, S6) 추가, 3가지 요구
시나리오를 모두 커버:

| 시나리오 | 유닛 | 이력 | 결과 |
|---|---|---|---|
| 유닛 회복 + 항목 flip-flop 동시 (우선순위 검증) | S5 | fail→pass(Bin은 여전히 fail)→fail→**pass(Bin1, 유닛 회복)** | `unit_recovered=True` → **Intermittent** (item flip-flop 은 무시됨) |
| 유닛 최종 fail + 항목 flip-flop (실데이터 Serial 25/62 패턴) | S6 | fail→pass(Bin은 여전히 fail)→fail→**fail(유닛 최종 fail)** | `unit_recovered=False`, 항목 중간 pass 있음 → **Unstable** |
| 유닛 최종 fail + 항목 계속 fail (기존 분류) | S2 (기존 fixture 재사용) | fail→fail→fail | `unit_recovered=False`, 항목 flip-flop 없음 → 기존대로 **Excessive** (Intermittent/Unstable 둘 다 아님을 추가 assert) |

기존 S1/S4(유닛 회복, item flip-flop 없음) 케이스도 `classify()` 헬퍼에
`unit_recovered=bool(state.get("is_intermittent"))`를 넘기도록 갱신해
그대로 Intermittent 로 통과함을 재확인했다.

```
$ python tests/test_retest_history.py
...
PASS: 전부 통과
```
**41개 체크 전부 PASS** (§S6 의 34개 + 이번에 추가/보강된 7개: S5 1개, S6 2개,
S2 "Unstable 아님" 1개, 나머지는 기존 assert 메시지 보강).

`python -m py_compile cdf_compare_web.py cdf_compare_tool.py` 통과 — 문법
오류 없음.

## 3. 검증 — 실데이터 (Test Data, SM3502Q/00_MVT0-0_1111_111/HTOL/1000hrs/Room)

before(§S6 코드, 커밋 `c2a8199`) / after(이번 변경, `unit_recovered` wiring
포함)를 `analyze_fail_to_json` 직접 호출로 비교했다 (git stash 로 이번 변경분만
분리).

### 3-1. VSTART Serial 25, 62 → Unstable (완료 기준 1)

```
SM3502Q|...|VSTART|25 :: Intermittent -> Unstable
SM3502Q|...|VSTART|62 :: Intermittent -> Unstable
```

두 유닛의 전체 이력 (스펙 [3.9, 4.1], 재확인):
```
Serial 25: stage0(FT)=4.101 high(Bin15) -> stage1(Retest1)=4.094 pass(Bin17)
           -> stage2(Retest2)=4.101 high(Bin15) -> stage3(Retest3)=4.101 high(Bin15)
           final_bin='15'  is_intermittent(유닛레벨)=False
Serial 62: stage0(FT)=4.101 high(Bin15) -> stage1(Retest1)=4.101 high(Bin15)
           -> stage2(Retest2)=4.094 pass(Bin17) -> stage3(Retest3)=4.101 high(Bin15)
           final_bin='15'  is_intermittent(유닛레벨)=False
```
둘 다 유닛 레벨 `is_intermittent=False`(최종 Bin=15, fail), 항목 VSTART 값이
중간 회차(Retest1 또는 Retest2)에 한 번 spec pass 를 찍었다가 다시 fail —
정확히 Unstable 정의와 일치.

### 3-2. Intermittent 건수 (완료 기준 2)

```
before(§S6): {'Excessive': 3, 'Tail': 17, 'Intermittent': 2, 'Slight': 2}
after(§S6b): {'Excessive': 3, 'Tail': 17, 'Unstable': 2,       'Slight': 2}
```
**Intermittent 건수: 0건** — 실데이터 22개 fail 유닛 전부 유닛 레벨 미회복
(§S6 §3-2 에서 이미 확인된 `is_intermittent(유닛레벨)==True: 0/22`와 일관).

### 3-3. Unstable 건수와 목록 (완료 기준 3)

**2건**, 둘 다 항목 VSTART:

| 유닛 | 회차 시퀀스 (값 / spec_status / Bin) |
|---|---|
| Serial 25 | FT: 4.101/high/Bin15 → Retest1: 4.094/**pass**/Bin17 → Retest2: 4.101/high/Bin15 → Retest3: 4.101/high/Bin15 |
| Serial 62 | FT: 4.101/high/Bin15 → Retest1: 4.101/high/Bin15 → Retest2: 4.094/**pass**/Bin17 → Retest3: 4.101/high/Bin15 |

(§3-1 과 동일 데이터, 표로 재정리)

### 3-4. 그 외 fail_type 분류 변화 (완료 기준 4)

before/after 24개 classified detail-row 전체를 diff 했다 — **변경 2건**
(Serial 25, 62), 그 외 전부 동일:
```
changed count: 2
SM3502Q|...|VSTART|25 :: Intermittent -> Unstable
SM3502Q|...|VSTART|62 :: Intermittent -> Unstable
```
Excessive 3건, Tail 17건, Slight 2건 — before/after 완전히 동일한 유닛·값.
**요구하신 "그 외 변화 없음"을 실측으로 확인.**

### 3-5. Pass 모드 무변화 (완료 기준 5)

```
$ python tools/verdict_diff.py --data-root "Test Data" --baseline tests/verdict_base_S6
1. 요약 비교
     SELECT      223 → 223    (+0)
     OK          246 → 246    (+0)
     판정불가          2 → 2      (+0)
2. 판정 전이 행렬: 완전 대각선 (신규/삭제 0)
3. 새로 SELECT 된 항목: 없음
4. SELECT 에서 빠진 항목: 없음
5. 수치가 바뀐 항목: 없음
차이 없음
```
`fail_type`은 `verdict_diff.py`가 추적하는 필드가 아니고 Pass 모드는
`fail_type_for_detail` 경로를 아예 타지 않으므로 당연한 결과지만, 실측으로
재확인했다.

## 4. 완료 기준 답변 (숫자)

1. **VSTART Serial 25, 62 가 Unstable 로 나오는가**: **예.** 둘 다
   `Intermittent → Unstable` (§3-1, §3-3).
2. **Intermittent 건수 (실데이터 0 이어야 한다)**: **0건.** (§3-2)
3. **Unstable 건수와 목록**: **2건**, Serial 25 / 62, 회차 시퀀스는 §3-3 표
   참조.
4. **그 외 fail_type 분류 변화 (없어야 한다)**: **없음.** 24개 classified
   행 중 변경은 정확히 그 2건뿐, Excessive 3 / Tail 17 / Slight 2 는
   before/after 완전 동일 (§3-4).
5. **Pass 모드 무변화**: **예.** SELECT 223→223, OK 246→246, 판정불가 2→2,
   전이 행렬 완전 대각선, "차이 없음" (§3-5).
6. **단위 테스트 결과**: `tests/test_retest_history.py` **41개 체크 전부
   PASS** (§S6 34개 + 신규/보강 7개), `py_compile` 통과 (§2).

## 5. 베이스라인

이번 검증은 §S6 이 저장한 `tests/verdict_base_S6/`를 그대로 재사용했다
(신규 베이스라인 생성 없음 — fail_type 은 verdict_diff 가 추적하는 필드가
아니라서 새 베이스라인이 필요 없었다).
