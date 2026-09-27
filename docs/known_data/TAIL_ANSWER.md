# KNOWN02 — 분포 형상 기반 Tail 판정 로직 검증용 정답표

`Known Data/KNOWN02/00_KV1-0_K002_K01/` · HTOL · Pre + 168/500/1000hrs · Room/Hot/Cold · Post 231 유닛

생성 `python tools/make_tail_data.py "Known Data"` · 검증 `python tools/check_tail_data.py "Known Data"`
시드 고정. KNOWN01(현재 툴 판정 검증용)과는 별개 디바이스라 서로 간섭하지 않는다.

## 2차 개정 — 꼬리는 심는 게 아니라 남겨 두는 것

1차 데이터는 Near-Spec Zone 안 Pass 개수를 정확히 맞추려고 **그 구간의 자연 유닛을 치우고**
원하는 자리에 점을 심었다. 개수는 맞았지만 모집단 끝과 심은 점 사이에 1 σ 넘는 빈 구간이
생겼다. 판정 대상 Gap(0.5 σ 수준)보다 그 앞 공백이 더 커서, 눈으로 보면 꼬리가 아니라
**떨어져 나온 덩어리**였다. 예: `TLB4_GAP099` 1차 — `… −1.21 −1.20 │ 1.10 공백 │ −0.10 │ 0.48 │ +0.39`

2차는 반대로 한다. 분포를 자르지 않고 **자연 꼬리를 그대로 둔 뒤**,

- 스펙 한계를 자연 꼬리 바로 위(`maxpass + d × σ_core`)에 놓고
- 최상위 몇 점만 바깥으로 옮겨 Spec Out 으로 만든다
- 우발적으로 벌어진 상위 간격만 0.45 σ 이하로 눌러 준다 (정규 꼬리 간격 기댓값 범위 안)

같은 항목 2차 — `… −0.97 −0.88 −0.65 −0.65 −0.37 −0.10 │ 0.49 │ +0.39`.
간격이 0.03 → 0.09 → 0.22 → 0.28 → 0.27 로 이어지다 판정 Gap 0.49 로 넘어간다. 이게 꼬리다.

n=231 정규 표본에서 상위 순서통계량 간격은 0.2~0.5 σ 라, Gap_Limit(0.5 σ)과 같은 척도다 —
이 로직이 성립하는 전제이기도 하다.

## 검증 대상 로직
```
1. Spec Out 존재 확인                 없으면 -> Normal
2. Core 분포      Median_core, sigma_core = 1.4826 x MAD   (전 유닛 기준, robust)
                  P95_core = Median_core + 1.6449 x sigma_core
3. Core in Spec   P95_core < UL   (하한측은 P5_core > LL)   아니면 -> Shift/Broadening OOS
4. Near-Spec Pass Zone = [UL - W, UL],  W = 0.50 x sigma_core
                  Near-Spec Pass Count >= 1           미달이면 -> Separated OOS
5. Gap            Min(Spec Out) - Max(Pass)
6. Gap_Limit      MAX(0.50 x sigma_core, 3 x 측정 분해능)
7. Gap <= Gap_Limit -> Tail OOS,  아니면 -> Separated OOS
```

제안서에 없어 **내가 정한 부분**(합의 필요):

- **Core = 그 항목의 Post 전 유닛**. Pass 유닛만 쓰면 `P95_core < UL` 이 항상 참이라 3번이 무의미해진다.
- **P5/P95 는 표본 백분위가 아니라 적합값** (Median ± 1.6449 σ_core).
- **측정 분해능 = 서로 다른 값들 사이의 최소 간격** (데이터로그에 분해능 항목이 없다).
- **상·하한을 따로 판정**하고 결과를 합쳐 표기 (`Tail/Separated`).

## 정답표


### A. Spec Out 없음 (Normal)

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLA1_NORMAL` | 0 | - | - | - | - | **Normal** | 꼬리 끝에서 0.30 sigma 위에 한계 — 이탈 0건 |
| `TLA2_NORM_EDGE` | 0 | - | - | - | - | **Normal** | 꼬리 끝이 한계 턱밑(0.02 sigma)까지 왔지만 이탈은 0건 |

### B. Gap 경계

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLB1_GAP080` | 1 | 8 | 0.400 | **0.800** | 0.22 | **Tail** | Gap = 0.80 x 한계 |
| `TLB2_GAP090` | 1 | 4 | 0.450 | **0.900** | 0.41 | **Tail** | Gap = 0.90 x 한계 |
| `TLB3_GAP096` | 1 | 2 | 0.480 | **0.960** | 0.51 | **Tail** | Gap = 0.96 x 한계 |
| `TLB4_GAP099` | 1 | 2 | 0.495 | **0.990** | 0.56 | **Tail** | Gap = 0.99 x 한계 (임계 바로 아래) |
| `TLB5_GAP101` | 1 | 2 | 0.505 | **1.010** | 0.48 | **Separated** | Gap = 1.01 x 한계 (임계 바로 위) |
| `TLB6_GAP104` | 1 | 3 | 0.520 | **1.040** | 0.73 | **Separated** | Gap = 1.04 x 한계 |
| `TLB7_GAP110` | 1 | 5 | 0.550 | **1.100** | 0.44 | **Separated** | Gap = 1.10 x 한계 |
| `TLB8_GAP125` | 1 | 1 | 0.625 | **1.250** | 0.89 | **Separated** | Gap = 1.25 x 한계 |

### C. Near-Spec Pass Count 경계

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLC0_NEAR0` | 1 | 0 | 0.700 | **1.400** | 0.45 | **Separated** | 한계가 꼬리 끝보다 0.60 sigma 위 -> Zone 이 비어 Count 0. 이때 Gap 은 자동으로 한계를 넘는다(두 조건이 같은 양을 본다는 증거) |
| `TLC1_NEAR1` | 1 | 2 | 0.450 | **0.900** | 0.38 | **Tail** | Zone 안 Pass 1개 |
| `TLC2_NEAR2` | 1 | 2 | 0.450 | **0.900** | 0.55 | **Tail** | Zone 안 Pass 2개 |
| `TLC3_NEAR3` | 1 | 5 | 0.440 | **0.880** | 0.40 | **Tail** | 스펙 근처에 소집단이 몰려 Zone 안 Pass 4개 — 자연 정규 꼬리로는 n=231 · W=0.5 sigma 에서 2개가 한계라 일부러 이어 붙였다 |
| `TLC4_ZONE_IN` | 1 | 1 | 0.490 | **0.980** | 0.56 | **Tail** | 꼬리 끝이 UL-0.48 sigma — Zone 안쪽 턱걸이 |
| `TLC5_ZONE_OUT` | 1 | 0 | 0.530 | **1.060** | 0.49 | **Separated** | 꼬리 끝이 UL-0.52 sigma — Zone 바깥 턱걸이 (0.04 sigma 차이로 뒤집힘) |

### D. Core 가 Spec 안인가 (P95_core vs UL)

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLD1_CORE_IN` | 7 | 15 | 0.041 | **0.081** | 0.25 | **Tail** | UL = 1.75 sigma_core > P95_core -> Core 는 Spec 안 |
| `TLD2_CORE_OUT` | 6 | - | - | - | 0.14 | **Shift** | UL = 1.55 sigma_core < P95_core -> Shift/Broadening |
| `TLD3_CORE_P02` | 15 | 13 | 0.051 | **0.101** | 0.20 | **Tail** | UL = 1.68 sigma_core (임계 +2%) |
| `TLD4_CORE_M02` | 10 | - | - | - | 0.16 | **Shift** | UL = 1.61 sigma_core (임계 -2%) |

### E. 측정 분해능이 한계를 정하는 구간

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLE1_RES_2Q` | 1 | 2 | 1.349 | **0.667** | 0.33 | **Tail** | 격자 q = 1.25 sigma, 격자 0/1/2/3 이 이어지고 Gap = 2q <= 3q |
| `TLE2_RES_3Q` | 1 | 2 | 2.023 | **1.000** | 0.33 | **Separated** | Gap = 3q 로 한계와 정확히 같은데 Separated 로 떨어진다 — 분해능을 '최소 간격'으로 추정하면 데이터로그 반올림 때문에 항상 q 보다 조금 작게 나오기 때문. 등호 규칙 필요 |
| `TLE3_RES_4Q` | 1 | 2 | 2.698 | **1.333** | 0.33 | **Separated** | Gap = 4q > 3q |
| `TLE5_RES_MIXED` | 1 | 2 | 1.349 | **2.667** | 1.33 | **Separated** | TLE1 과 분포도 Gap 도 같은데, 격자에서 벗어난 한 쌍(q/4 간격) 때문에 분해능 추정이 q/4 로 떨어져 한계가 0.75q 가 된다 — 그래프로는 구분 불가 |

### F. MAD = 0 (저분해능)

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLF1_MAD0_NEAR` | 1 | 0 | - | **0.333** | 0.33 | **Separated** | sigma_core = 0 -> Zone 폭 0 -> Near-Spec Pass 0개. Gap 은 1q 로 작은데도 탈락 |
| `TLF2_MAD0_FAR` | 1 | 0 | - | **1.333** | 0.33 | **Separated** | sigma_core = 0 이고 Gap = 4q > 3q |

### G. 하한(LL) 측

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLG1_LOW_TAIL` | 1 | 4 | 0.400 | **0.800** | 0.53 | **Tail** | 하한측 Gap = 0.80 x 한계 |
| `TLG2_LOW_SEP` | 1 | 5 | 0.550 | **1.100** | 0.30 | **Separated** | 하한측 Gap = 1.10 x 한계 |

### H. Spec Out 다수

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLH1_LADDER` | 4 | 7 | 0.400 | **0.800** | 0.35 | **Tail** | 이탈 4건이 꼬리 끝에서 0.5/1.0/1.8/3.0 sigma 로 계단식. 항목 Gap 은 최근접 1건이 정하므로 +3.0 sigma 짜리까지 전부 Tail 이 된다 |
| `TLH2_CLUSTER` | 3 | 16 | 1.600 | **3.200** | 0.16 | **Separated** | 이탈 3건이 꼬리 끝에서 1.7~1.9 sigma 에 뭉쳐 있고 모집단과 떨어져 있다 |
| `TLH3_BIMODAL` | 5 | 3 | 0.400 | **0.800** | 0.58 | **Tail** | 꼬리에 이어지는 군 3건 + 멀리 떨어진 군 2건이 섞임 |

### I. 상·하한 동시 이탈

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLI1_BOTH` | 2 | 9 | 0.400 | **0.800** | 0.33 | **Tail/Separated** | 상한은 Tail(0.80), 하한은 Separated(1.40) — 최종 분류가 로직에 없다 |

### Z. 정상 항목

| 항목 | 이탈 | Zone 안 Pass | Gap (σ) | Gap/한계 | 꼬리 최대간격/한계 | 정답 | 설명 |
|---|---|---|---|---|---|---|---|
| `TLZ1_CLEAN` | 0 | - | - | - | - | **Normal** | 이탈 없음 |
| `TLZ2_CLEAN` | 0 | - | - | - | - | **Normal** | 이탈 없음 |

전 항목 `tools/check_tail_data.py` 에서 **34 / 34 일치**. 부가 검증도 전부 통과:
판정은 Room/1000hrs 에만 (D 그룹 제외), 산포 회차 단조 증가 · 온도 순서 Cold < Room < Hot,
**꼬리가 끊긴 항목 0건**(꼬리 최대간격 / Gap_Limit 가 1.5 를 넘는 항목 없음).

## 임계(Gap / Gap_Limit = 1.0) 주변 밀집도
```
   0.081  TLD1_CORE_IN     Tail
   0.101  TLD3_CORE_P02    Tail
   0.333  TLF1_MAD0_NEAR   Separated
   0.667  TLE1_RES_2Q      Tail
   0.800  TLH3_BIMODAL     Tail
   0.800  TLI1_BOTH        Tail/Separated
   0.800  TLH1_LADDER      Tail
   0.800  TLB1_GAP080      Tail
   0.800  TLG1_LOW_TAIL    Tail
   0.880  TLC3_NEAR3       Tail
   0.900  TLC2_NEAR2       Tail
   0.900  TLB2_GAP090      Tail
   0.900  TLC1_NEAR1       Tail
   0.960  TLB3_GAP096      Tail
   0.980  TLC4_ZONE_IN     Tail
   0.990  TLB4_GAP099      Tail
   1.000  TLE2_RES_3Q      Separated
   1.010  TLB5_GAP101      Separated
   1.040  TLB6_GAP104      Separated
   1.060  TLC5_ZONE_OUT    Separated
   1.100  TLG2_LOW_SEP     Separated
   1.100  TLB7_GAP110      Separated
   1.250  TLB8_GAP125      Separated
   1.333  TLE3_RES_4Q      Separated
   1.333  TLF2_MAD0_FAR    Separated
   1.400  TLC0_NEAR0       Separated
   2.667  TLE5_RES_MIXED   Separated
   3.200  TLH2_CLUSTER     Separated
```
## 이 데이터셋으로 드러난 로직 설계 구멍

**1. 조건 4(Near-Spec Count)와 조건 7(Gap)은 한 몸이다.**
스펙 한계를 꼬리 끝에서 `d × σ_core` 위에 두면, Spec Out 은 반드시 한계 바깥이므로
`Gap ≥ d × σ_core` 다. 즉 **Gap/한계 ≥ 2d** 가 항상 성립한다. 한편 Zone 안 Pass 개수는
`d > 0.5` 이면 무조건 0 이다. 그래서 "Count 0" 과 "Gap 이 한계 초과" 는 같은 조건의
다른 표현이다 — `TLC0_NEAR0`(d=0.60)과 `TLC5_ZONE_OUT`(d=0.52)이 둘 다 두 조건에
동시에 걸리는 게 그 증거다. 두 관문을 독립으로 쓰려면 기준 길이를 달리 잡아야 한다
(예: W = 1.5 σ_core, Gap_Limit = 0.5 σ_core).

**2. Gap 이 항목당 하나라, Spec Out 이 여러 개면 가장 가까운 1건이 전부를 대표한다.**
`TLH1_LADDER` 는 이탈 4건이 꼬리 끝에서 +0.5 / +1.0 / +1.8 / +2.9 σ 로 놓여 있고
인접 간격이 0.40 → 0.60 → 0.80 → 1.20 σ 로 계속 벌어진다. 그런데 항목 Gap 은
최근접 1건이 정한 0.40 σ 하나뿐이라 **4건 전부 Tail** 이 된다.
유닛별로 갈라내려면 정렬 후 **인접 gap 을 걸어 올라가며** 끊기는 지점을 찾아야 한다.
정답표의 `꼬리 최대간격/한계` 열이 그 판단에 쓸 수 있는 값이다.

**3. 가장 가까운 Pass 가 모집단에 붙어 있는지를 로직이 확인하지 않는다.**
1차 데이터가 우연히 드러낸 구멍이다. 스펙 턱밑에 점 하나만 떠 있으면 그 점이 뒤의
이탈값을 Separated → Tail 로 구제해 준다. 2차 데이터는 꼬리를 연속으로 만들어
이 상황을 없앴지만, **로직 자체는 여전히 그 검사를 안 한다**. 2번의 인접 gap walk 를
도입하면 1·2·3번이 한 규칙으로 해결된다.

**4. 측정 분해능 추정이 단 한 쌍에 무너진다.**
`TLE1_RES_2Q` 와 `TLE5_RES_MIXED` 는 분포도 Gap 도 똑같다. 차이는 E5 에 격자에서 벗어난
값 한 쌍(q/4 간격)이 있다는 것뿐인데, "최소 간격" 추정이 q → q/4 로 떨어지면서
한계가 3q → 0.75q 가 되고 판정이 Tail → Separated 로 뒤집힌다.
분해능은 최소 간격이 아니라 **간격들의 최빈값/중앙값**으로 잡아야 한다.

**5. `Gap = 3 × 분해능` 인 데이터는 등호인데도 항상 Separated 로 떨어진다.**
`TLE2_RES_3Q`. 데이터로그가 값을 반올림해 저장하므로 추정 분해능은 언제나 실제 격자 q
보다 조금 작게 나오고 `Gap <= Gap_Limit` 의 등호가 성립하지 않는다. 허용 오차가 필요하다.

**6. MAD = 0 인 항목은 Gap 이 아무리 작아도 무조건 Separated 다.**
`TLF1_MAD0_NEAR` 는 Gap 이 1q(한계 3q 의 1/3)인데도 탈락한다. σ_core = 0 → Zone 폭 0
→ Count 0 이기 때문이다. Zone 폭을 `MAX(W × σ_core, 분해능)` 으로 바꾸는 예외가 필요하다.

**7. 조건 3(Core in Spec)은 사실상 "이탈률 5% 이상이면 Shift" 와 같은 말이다.**
`P95_core < UL` 이 깨지려면 UL 이 Median + 1.645 σ_core 안쪽이어야 하고, 그 지점은 이미
이탈률 5% 를 넘는 지점이다. D 그룹의 이탈 건수(6~15건)가 그 뜻이다.

**8. 상·하한 동시 이탈의 최종 분류가 로직에 없다.** `TLI1_BOTH` 참조.

**9. 자연 정규 꼬리에서 W = 0.5 σ_core 의 Zone 안 Pass 개수는 1~3개가 한계다.**
2차 데이터의 B/C 그룹에서 실측된 값이 1~8개인데, 8개는 상위 간격이 유독 촘촘했던 항목이고
대부분 2~5개다. `TLC3_NEAR3` 처럼 4개 이상을 만들려면 스펙 근처에 소집단을 따로 이어
붙여야 했다. **N_min 을 3 이상으로 올리면 정상적인 꼬리도 상당수 탈락한다.**

## 남은 작업

- `W`, `N_min`, `Gap_Limit` 을 **실제 Test Data** 에 스윕해 현재 `Tail` 판정과의 일치율을
  보고 파라미터를 확정할 것 (이 데이터셋은 로직이 설계대로 도는지를 보는 용도다).
- Gap 을 항목 단위 → **유닛 단위 인접 gap** 으로 바꾼 v2 프로토타입.
- 기존 우선순위(Intermittent > Unstable > Excessive > Slight > Tail) 안에서의 위치 확정.
- 판정 변경이므로 CLAUDE.md §5-1 대상 — 별도 브랜치 + 골든 재생성.

## 참고 — 데이터 성질

- 판정은 **Room / 1000hrs** 에만 난다. 나머지 8개 조건은 Spec Out 0건
  (D 그룹은 분포 자체가 밀린 설정이라 모든 조건에서 이탈한다).
- 산포 변화: 회차 단조 증가, 온도 순서 Cold < Room < Hot — 전 항목 성립.
  격자 항목(E/F)은 산포 증가가 양자화에 묻혀 회차 검사에서 제외한다 (실제 저분해능
  항목도 마찬가지다).
- `FT_FAIL_STEP`(FailStep) / `FCLK_MHZ`(MHz) 는 단위 필터로 빠지는 디코이 열,
  `DEVICE_ID`(Binnary) 는 Pre↔Post 조인 키.
- `tools/known02_manifest.json` 에 항목별 이동 Serial · 한계 · σ_core 가 남는다.
