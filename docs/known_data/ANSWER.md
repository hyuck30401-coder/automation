# Known Data 정답표

툴 검증용 합성 데이터셋의 **기대 판정**이다. `tools/check_known_data.py` 가 이 표와
툴의 실제 판정을 대조한다. 데이터는 `tools/make_known_data.py` 로 재생성한다
(시드 `20260905` 고정 — 같은 파일이 다시 나온다).

```
python tools/make_known_data.py          # 생성  -> Known Data/
python tools/check_known_data.py         # 대조
```

## 생성 시점 기준 (이 값이 바뀌면 정답도 바뀐다)

| 항목 | 값 |
|---|---|
| 판정 방식 | Grubbs 단일 이상치, `FLAG_ALPHA = 0.01`, ddof=1 |
| Grubbs 임계 (n=217) | 약 4.01 |
| 표시 게이트 | `SPEC_GATE_TAU = 0.05` |
| Marginal 정의 | `fail_type == "Tail"` |
| 생성 시 툴 리비전 | Rev.0.031 |

## 데이터 구성

```
Known Data/KNOWN01/00_KV1-0_K001_K01/
  00_Pre/   ROOM · HOT · COLD                        각 800 유닛 (로트 전체 ListAll)
  01_Post/  ROOM · HOT · COLD × 168hrs·500hrs·1000hrs  각 231 유닛
```

- 시험 항목 **HTOL**, 판정 리드아웃은 마지막 **1000hrs** (168/500 은 추세용)
- **이상 건은 Room 에만**. Hot / Cold 는 fail 0 · Abnormal Pass 0
- 컬럼 43개 = 측정 항목 40 + `DEVICE_ID`(Binnary) + `FT_FAIL_STEP`(FailStep) + `FCLK_MHZ`(MHz)
  - 뒤 3개는 단위 필터(§3-5)로 **제외되는 것이 정답** → 분석 항목 수 **40**
- Pre↔Post 조인은 `DEVICE_ID` (§3-3). Pre 에 DEVICE_ID 중복 5건(마지막 등장 채택)
- **Serial 230 · 231 은 DEVICE_ID 공란** → Pre 매칭 실패.
  툴은 이 유닛을 분석 모집단에서 **제외한다** (`NO PRE SAMPLE` 표시가 아니라 제외).
  Pre 매칭 실측: post_units 243 / matched 241 / unmatched 2
- 1000hrs Room 파일에는 재시험 행이 있다 (§3-4, 같은 파일 안 행 반복) → 총 243행

## Fail 정답 — Room / 1000hrs, 15 유닛

| Serial | 항목 | 기대 `fail_type` | 벤치 검토 |
|---|---|---|---|
| 201 | VOUT_1V8 | `Excessive` | 대상 |
| 202 | ICC_ACTIVE | `Excessive` | 대상 |
| 203 | RPULLUP | `Excessive` | 대상 |
| 204 | VOUT_3V3 | `Slight` | 대상 |
| 205 | ILIM_SET | `Slight` | 대상 |
| 206 | RDSON | `Slight` | 대상 |
| 207 | VREF_BG | `Tail` | **제외 (Marginal)** |
| 208 | ISHDN | `Tail` | **제외 (Marginal)** |
| 209 | GM_EA | `Tail` | **제외 (Marginal)** |
| 210 | VDD_UVLO | `Unstable` | 대상 |
| 211 | ICC_SLEEP | `Unstable` | 대상 |
| 212 | VOS_AMP | `Unstable` | 대상 |
| 213 | VOUT_3V3 | `Intermittent` | 제외 (유닛 회복) |
| 214 | ILIM_SET | `Intermittent` | 제외 (유닛 회복) |
| 215 | RDSON | `Intermittent` | 제외 (유닛 회복) |

`sample_counts` = total 231 · fail 15 · pass 219.

추가로 **Tail 판정 세트 3건**(`186 VPP_MON` · `187 IREF_TRIM` · `188 RDIV_TOP`)이 있다 —
207~209 와 성격은 같지만 fail_type 분류 자체를 따로 검증하려고 항목을 분리했다.
Marginal 게이트는 이 6건 + 경계 `192` = **7건을 접는다**.

**Fail 쪽 Marginal 은 정의상 `fail_type == "Tail"` 이다**(R-032, `FAIL_MARGINAL_TYPE`).
따로 심는 유형이 아니라 Tail 이 곧 Marginal 이므로, 위 표의 **207·208·209 세 건이
Marginal 검증 세트**다. `Marginal 제외` 필터를 켜면 정확히 그 3건이 접힌다(실측 확인).

## Abnormal Pass 정답 — Room / 1000hrs, 9 유닛

| Serial | 항목 | 기대 `reason` | 어떻게 만들었나 |
|---|---|---|---|
| 216 | VOUT_5V0 | `Measured` | Pre 부터 +5.2σ, 이동량은 0 |
| 217 | VLDO_1V2 | `Measured` | 〃 |
| 218 | ILEAK_IO | `Measured` | 〃 |
| 219 | VSTART | `Delta` | 값은 평범(+0.45σ), 이동만 집단의 11σ |
| 220 | VCLAMP | `Delta` | 〃 |
| 221 | ICC_STBY | `Delta` | 〃 |
| 222 | VOUT_1V0 | `Measured + Delta` | Pre +3.2σ 에서 +5.4σ 로 이동 |
| 223 | IBIAS | `Measured + Delta` | 〃 |
| 224 | RSENSE | `Measured + Delta` | 〃 |
| 225 | VBG_TRIM | `Measured` | **스펙 대비 미미** — spec_k 60(Cp 과잉), 5.2σ ÷ 120σ = 4.3% |
| 226 | IDD_LP | `Delta` | **스펙 대비 미미** — 0.45σ ÷ 12σ = 3.75% |
| 227 | VTEMP | `Measured + Delta` | **스펙 대비 미미** — max(4.5%, 1.83%) |

SELECT 항목 12 · SELECT 유닛 12. **그 밖의 유닛은 하나도 걸리지 않는 것이 정답.**

### 스펙 대비 기준 / 산포 기준 (Abnormal Pass 쪽 Marginal)

`225·226·227` 은 판정은 SELECT 지만 **스펙 대비 이동량이 tau(5%) 미만**이라
`스펙 대비 기준` 탭에서 접힌다. 즉 **`산포 기준` 탭에서만 보이는 3건**이다.
reason 3종을 하나씩 덮도록 짰다 — 게이트 축(Mea / Delta / 둘 다)이 모두 검증된다.

| 탭 | 보이는 항목 | 접히는 유닛 |
|---|---|---|
| 스펙 대비 기준 (기본) | 12 | 198 · 225 · 226 · 227 |
| 산포 기준 | 16 | — |

`216~224` 는 스펙 대비 크기가 41~46% 로 게이트를 확실히 통과한다.
설계 초기에는 `Delta`(219~221)의 이동량이 3.75% 라 게이트에 걸려 있었다 —
"reason 이 Delta 인 것"과 "스펙 대비 미미한 것"이 같은 유닛이 되어 두 축을 따로
검증할 수 없었다. 그래서 `Delta` 의 이동량을 0.45σ → 0.85σ(7.1%)로 올려 분리했다.

## 앞 회차(168hrs · 500hrs) 정답

fail 0 · Abnormal Pass **7 유닛** — `207 208 209 216 217 218 225`.

`Measured`(216~218, 225)와 `Tail`(207~209)은 **설계상 Pre 시점부터 이미 집단에서 튀는** 유닛이라
스트레스 전부터 통계적 이상치다. 앞 회차에서도 잡히는 것이 옳다. 나머지(`Delta`,
`Measured + Delta`, 모든 Fail 유형)는 마지막 회차에만 나타난다.

## 산포(sigma) 변화

리드아웃이 진행될수록, 그리고 온도에 따라 산포가 달라지는 양상이 데이터에 들어 있다.

```
sigma(항목, 온도, 회차) = sigma_pre x temp_factor(항목, 온도) x (1 + growth(항목) x 진행도)
진행도 = 168hrs 1/3 · 500hrs 2/3 · 1000hrs 1
```

항목마다 크기는 랜덤(시드 고정)이지만 **한 번 뽑으면 끝까지 고정**이라, 회차 순서
(168 < 500 < 1000)와 온도 순서(Cold < Room < Hot)가 **어느 조합에서도 뒤집히지 않는다**.
`check_known_data.py` 가 40항목 전부에 대해 이 두 순서를 검사한다(이상 유닛 제외 기준 —
이상치가 섞이면 표본 sigma 가 그 유닛 때문에 부풀어 순서가 흔들리는데, 그건 실제
데이터에서도 마찬가지라 정상이다).

| 항목 | 1000hrs 성장률 | Hot 배율 | Cold 배율 |
|---|---:|---:|---:|
| `VOUT_1V8` | +13% | x1.21 | x0.80 |
| `ICC_ACTIVE` | +14% | x1.14 | x0.86 |
| `RPULLUP` | +17% | x1.21 | x0.85 |
| `VOUT_3V3` | +21% | x1.13 | x0.81 |
| `ILIM_SET` | +19% | x1.26 | x0.78 |
| `RDSON` | +33% | x1.19 | x0.93 |
| `VREF_BG` | +19% | x1.17 | x0.87 |
| `ISHDN` | +33% | x1.15 | x0.90 |
| … | (40항목 전체는 `SIGMA_PROFILE` 참조) | | |

**산포를 키우는 방식이 판정을 좌우한다.** "전 유닛을 평균 중심으로 균등 확대"하면 값이
튀는 유닛은 변화율도 같이 튀어서 `Measured`(값만 튐)와 `Delta`(이동만 큼)를 분리할 수
없다. 그래서 **독립 잡음을 더하는** 모델을 쓴다 — 스트레스가 유닛마다 다르게 작용해
산포가 늘어나는 실제 양상과도 맞는다.

```
post = pre x (1 + drift) + eps,    eps ~ N(0, sigma_pre x sqrt(scale^2 - 1))
```

drift 와 eps 는 **항목마다 한 번만 뽑아 온도·회차에 걸쳐 재사용**한다. 회차마다 새로
뽑으면 표본 sigma 가 흔들려 순서가 역전되고, 유닛별 T1->T2->T3 추세도 지그재그가 된다.
마지막에 표본 표준편차를 설계값에 정확히 맞추는 공통 배율 보정을 한 번 건다.

**산포 변화 때문에 주입 방식을 세 가지로 나눴다.** sigma 가 커지면 같은 절대값이라도
z-score 는 작아지므로, 케이스마다 무엇을 고정할지가 다르다.

| 방식 | 대상 | 고정하는 것 |
|---|---|---|
| z 기준 | Measured / Delta / M+D / Bnd:Mea± / Bnd:Delta± | `mu + z x sigma(그 조합)` — z 가 보존된다 |
| 스펙 기준 | Excessive / Slight / Tail / Unstable / Intermittent / Bnd:Excessive± / Bnd:Slight± | `UL x (1 + 이탈률)` — 스펙은 sigma 와 무관 |
| 스펙폭 크기 기준 | Marginal(...) / Bnd:Tau± | `mu + 크기 x 스펙폭` — 게이트 판정이 고정된다 |

Delta 계열과 스펙 대비 게이트 계열이 심긴 항목은 성장률을 작게(4~9%) 잡았다.
전자는 추가 잡음이 곧 변화율 산포라 성장률이 크면 Diff_S 가 묻히고, 후자는 sigma 가
커질수록 z 가 Grubbs 임계 아래로 내려가기 때문이다. 나머지 항목은 10~35%.

## 설계 메모

- **정상 유닛은 `|z| <= 3.0` 으로 잘라서 생성한다.** 231유닛 × 24항목이면 alpha=0.01
  Grubbs 에서 우발적 flag 가 실제로 나온다(초기 시드에서 #70 이 VCLAMP 에 걸렸다).
  known-answer 데이터에 "우연한 진짜 이상치"가 있으면 안 되므로 정상 표본을 잘라 두고
  이상 건은 주입으로만 만든다.
- **유형마다 항목을 따로 준다.** 같은 항목에 이상치를 여러 개 넣으면 Grubbs(단일 이상치
  검정)에서 서로 가려져(masking) 판정이 흔들린다.
- **소수 자릿수는 항목 크기에 맞춘다.** 전 항목을 `%.4f` 로 쓰면 VOS_AMP(mu=0.015,
  sigma=7.5e-5) 가 한 값으로 뭉개져 변화율이 이산 격자가 되고, 168hrs 에서 유닛 11대가
  가짜 `Delta` 로 잡힌다.
- **케이스 유닛의 앞 회차 값은 결정적으로 둔다**(평범한 유닛과 같은 이동량, 난수 없음).
  난수를 남기면 규격 끝에 붙여 둔 Tail 유닛이 회차마다 규격을 넘나들어 정답표가 흔들린다.

## 이 데이터로 드러난 문서 오류

- `CLAUDE.md` §3-5 는 `mOhm` 을 단위 필터 제외 목록에 넣어 두었으나, 현재 코드
  (`unit_is_allowed`)는 `mOhm` 을 **허용**한다. 확실히 제외되는 단위가 필요해
  `MHz` 로 바꿔 픽스처를 구성했다.


## 경계 케이스 — 선별 기준 바로 옆

각 기준선마다 **바로 위 / 바로 아래 한 쌍**을 넣었다. 부등호 방향과 임계값 계산이
맞는지 확인하는 용도다.

| Serial | 항목 | 기준선 | 위치 | 기대 결과 |
|---|---|---|---|---|
| 189 | BND_EXC_IN | `spec_margin_ratio` = 1% | 1.05% | `Excessive` |
| 190 | BND_EXC_OUT | 〃 | 0.95% | `Slight` (Excessive 아님) |
| 191 | BND_SLT_IN | Diff_S = Grubbs 임계 | 임계의 1.14배 | `Slight` |
| 192 | BND_SLT_OUT | 〃 | 임계의 0.90배 | `Tail` (→ Marginal 로 접힘) |
| 193 | BND_MEA_IN | Mea_S = Grubbs 임계 | 임계의 1.11배 | Abnormal Pass `Measured` |
| 194 | BND_MEA_OUT | 〃 | 임계의 0.91배 | **안 걸림** |
| 195 | BND_DLT_IN | Diff_S = Grubbs 임계 | 임계의 1.04배 | Abnormal Pass `Delta` |
| 196 | BND_DLT_OUT | 〃 | 임계의 0.95배 | **안 걸림** |
| 197 | BND_TAU_IN | 이동량/스펙폭 = tau(5%) | 5.2% | 스펙 대비 기준에서 **유지** |
| 198 | BND_TAU_OUT | 〃 | 4.8% | 스펙 대비 기준에서 **접힘** |

**189·190 과 197·198 은 해석적으로 결정된다** — 쓰인 값과 한계값만으로 정해져
표본과 무관하다. 반면 **191~196 은 Grubbs 임계가 표본 sigma 에 의존**하고, 주입한
이상치 자신이 그 sigma 를 부풀리는 되먹임이 있어 "z 를 4.2 로 넣으면 4.2 가 나온다"가
성립하지 않는다. 그래서 `tools/calibrate_known_data.py` 가 생성 → 실측 → 보정을
반복해 임계선 양쪽 1~15% 안에 앉힌다. 결과는 `tools/known_data_calib.json` 에 남는다.

```
python tools/calibrate_known_data.py     # 경계 재수렴 (판정 기준을 바꿨을 때만)
```

**alpha 나 tau 를 바꾸면 191~196 의 정답이 달라진다.** 그때는 캘리브레이션을 다시 돌리고
이 표의 배율을 갱신해야 한다. 189·190·197·198 은 그대로다(tau 를 바꾸면 197·198 만 바뀐다).

## 전체 집계 (Room / 1000hrs)

```
sample_counts   total 231 · fail 22 · pass 212
Fail 상세       22 유닛   (Excessive 4 · Slight 4 · Tail 7 · Unstable 3 · Intermittent 3, 경계 포함)
Abnormal Pass   16 항목 / 16 유닛   (스펙 대비 기준에서는 12)
Marginal 접힘   7건
스펙 대비 접힘  4건 (198 · 225 · 226 · 227)
```
