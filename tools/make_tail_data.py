# -*- coding: utf-8 -*-
"""제안된 "분포 형상 기반 POST Spec-Out Tail 판정" 로직 검증용 데이터셋 (KNOWN02).

기존 Known Data(KNOWN01)는 현재 툴의 판정(Excessive/Slight/Tail/Unstable/
Intermittent + Abnormal Pass)을 검증한다. 이 데이터셋은 그것과 별개로,
새로 제안된 아래 로직의 **각 분기마다 걸리는 데이터와 안 걸리는 데이터**를,
그리고 **임계 바로 양옆의 데이터**를 한 덩어리로 심어 둔 것이다.

  1. Spec Out 존재 확인
  2. Core 분포      Median_core, sigma_core = 1.4826 x MAD   (전 유닛 기준, robust)
                    P95_core = Median_core + 1.6449 x sigma_core
  3. Core in Spec   P95_core < UL   (하한측은 P5_core > LL)   아니면 -> Shift/Broadening
  4. Near-Spec Pass Zone = [UL - W, UL],  W = W_K x sigma_core
                    Near-Spec Pass Count >= N_MIN            미달이면 -> Separated
  5. Gap            Min(Spec Out) - Max(Pass)
  6. Gap_Limit      MAX(GAP_K x sigma_core, RES_K x 측정 분해능)
  7. Gap <= Gap_Limit -> Tail OOS,  아니면 -> Separated OOS

■ 꼬리는 "심는" 게 아니라 "남겨 두는" 것이다 (1차 설계의 실패에서 배운 것)
  처음에는 Near-Spec Zone 안의 Pass 개수를 정확히 맞추려고 그 구간의 자연 유닛을
  치우고 원하는 자리에 점을 심었다. 개수는 정확해졌지만 **모집단 끝과 심은 점 사이에
  1 sigma 넘는 빈 구간**이 생겼다. 그러면 판정 대상인 Gap(0.5 sigma 수준)보다 그 앞의
  공백이 더 커서, 눈으로 보면 "꼬리"가 아니라 "떨어져 나온 덩어리"였다.

  지금 방식은 반대다. 분포를 자르지 않고 **자연 꼬리를 그대로 둔 뒤**,
    - 스펙 한계를 자연 꼬리 바로 위(maxpass + d x sigma_core)에 놓고
    - 최상위 몇 점만 바깥으로 옮겨 Spec Out 으로 만든다
  모집단 -> 점점 성겨지는 꼬리 -> 스펙 한계 -> 이탈 이 끊기지 않고 이어진다.
  n=231 정규 분포에서 상위 순서통계량 간격은 0.2~0.5 sigma 라, 한계(0.5 sigma)와
  같은 척도다 — 이게 이 로직이 성립하는 전제이기도 하다.

  d(한계가 꼬리 끝에서 얼마나 위인가)와 R(= Gap / Gap_Limit)만으로 모든 경계
  케이스가 만들어진다. Near-Spec Pass 개수는 자연 분포가 정하는 대로 두거나,
  d 를 훑어서 원하는 개수가 나오는 지점을 고른다.

구조·레이아웃은 KNOWN01 과 동일(§3-1 폴더 규약, §3-2 데이터로그 레이아웃)이라
툴이 그대로 읽는다. 시드 고정이라 재생성하면 같은 파일이 나온다.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_known_data import write_csv                    # CSV 레이아웃 재사용

SEED = 20260911
PRE_UNITS = 800
POST_UNITS = 231
TEMPS = [("Room", "ER01"), ("Hot", "EH01"), ("Cold", "EC01")]
READOUTS = ["168hrs", "500hrs", "1000hrs"]
JUDGED = "1000hrs"
DEVICE = "KNOWN02"
FOLDER = "00_KV1-0_K002_K01"

# ── 제안 로직 파라미터 (검증기와 공유) ────────────────────────────────────────
KZ = 1.4826          # MAD -> sigma 환산
Z95 = 1.6448536269514722
W_K = 0.5            # Near-Spec Zone 폭 = W_K x sigma_core
N_MIN = 1            # Near-Spec Pass Count 최소 개수
GAP_K = 0.5          # Gap_Limit = MAX(GAP_K x sigma_core, RES_K x 분해능)
RES_K = 3.0

TRUNC_OTHER = 2.3    # 판정 조건이 아닌 회차/온도는 꼬리를 잘라 우발적 이탈을 막는다


def S(name, unit, mu, rel_sigma, group, expect, note, **kw):
    """시나리오 항목 하나.

    연속 꼬리형(mode="tail"):
      n_oos  Spec Out 으로 돌릴 최상위 유닛 수. 0 이면 Normal.
      d      UL = maxpass + d x sigma_core.  None 이면 near 로부터 역산한다.
      near   Near-Spec Zone 안 Pass 목표 개수 (d 를 훑어서 맞춘다).
      R      Gap / Gap_Limit 목표비.  첫 이탈 = maxpass + R x GAP_K x sigma_core.
             Gap = 첫 이탈 - maxpass 이므로 Gap/한계 = R 이 된다.
             이탈이 UL 바깥이어야 하므로 R x GAP_K > d, 즉 **R > 2d** 가 제약이다
             — 이 제약 자체가 조건 4 와 조건 7 이 한 몸이라는 증거다.
      extra  추가 이탈 위치 (maxpass 기준 sigma 배수, 오름차순).
      pile_to Zone 안 Pass 개수를 이 값까지 채운다 (스펙 근처에 소집단이 몰린 경우).
             자연 정규 꼬리로는 n=231 · W=0.5 sigma 에서 2개가 한계라, 그 이상은
             이렇게 이어 붙여야 만들어진다 — 그 사실 자체가 확인 대상이다.
      side   "hi" | "lo" | "both"
    자연형(mode="nat"):  ku 로 UL 위치만 정하고 나머지는 자연 그대로 (Shift 계열).
    격자형(mode="grid"): qk 로 양자화하고 격자 번호로 배치 (분해능 계열).
    """
    d = dict(name=name, unit=unit, mu=mu, sigma=abs(mu) * rel_sigma, group=group,
             expect=expect, note=note, mode="tail", side="hi",
             n_oos=1, d=None, near=None, R=0.8, extra=(), pile_to=0,
             d_lo=None, near_lo=None, R_lo=0.8, extra_lo=(), n_oos_lo=1,
             ku=3.0, qk=0.0, ku_q=0.0, gnear=(), goos=(), offgrid=0.0,
             trunc=3.6, ll=None, ul=None, dec=6)
    d.update(kw)
    d["extra"] = list(d["extra"]); d["extra_lo"] = list(d["extra_lo"])
    d["gnear"] = list(d["gnear"]); d["goos"] = list(d["goos"])
    d["serials"] = []
    return d


# ── 시나리오 ─────────────────────────────────────────────────────────────────
SCEN = [
    # A. Spec Out 없음 -> Normal
    S("TLA1_NORMAL", "V", 1.2000, 0.005, "A", "Normal",
      "꼬리 끝에서 0.30 sigma 위에 한계 — 이탈 0건", n_oos=0, d=0.30),
    S("TLA2_NORM_EDGE", "V", 1.8000, 0.005, "A", "Normal",
      "꼬리 끝이 한계 턱밑(0.02 sigma)까지 왔지만 이탈은 0건", n_oos=0, d=0.02),

    # B. Gap 경계 — 한계는 꼬리 끝 0.10 sigma 위, Gap 비만 바꾼다
    S("TLB1_GAP080", "V",  2.5000, 0.005, "B", "Tail",
      "Gap = 0.80 x 한계", d=0.10, R=0.80),
    S("TLB2_GAP090", "V",  3.3000, 0.005, "B", "Tail",
      "Gap = 0.90 x 한계", d=0.10, R=0.90),
    S("TLB3_GAP096", "V",  5.0000, 0.005, "B", "Tail",
      "Gap = 0.96 x 한계", d=0.10, R=0.96),
    S("TLB4_GAP099", "V",  0.6000, 0.005, "B", "Tail",
      "Gap = 0.99 x 한계 (임계 바로 아래)", d=0.10, R=0.99),
    S("TLB5_GAP101", "mA", 12.5000, 0.005, "B", "Separated",
      "Gap = 1.01 x 한계 (임계 바로 위)", d=0.10, R=1.01),
    S("TLB6_GAP104", "mA",  4.2000, 0.005, "B", "Separated",
      "Gap = 1.04 x 한계", d=0.10, R=1.04),
    S("TLB7_GAP110", "uA", 35.0000, 0.005, "B", "Separated",
      "Gap = 1.10 x 한계", d=0.10, R=1.10),
    S("TLB8_GAP125", "uA",  1.5000, 0.005, "B", "Separated",
      "Gap = 1.25 x 한계", d=0.10, R=1.25),

    # C. Near-Spec Pass Count — 한계 높이(d)를 바꿔 Zone 안 개수를 맞춘다
    S("TLC0_NEAR0", "V", 2.1000, 0.005, "C", "Separated",
      "한계가 꼬리 끝보다 0.60 sigma 위 -> Zone 이 비어 Count 0. "
      "이때 Gap 은 자동으로 한계를 넘는다(두 조건이 같은 양을 본다는 증거)",
      d=0.60, R=1.40),
    S("TLC1_NEAR1", "V", 2.7000, 0.005, "C", "Tail",
      "Zone 안 Pass 1개", near=1, R=0.90),
    S("TLC2_NEAR2", "V", 6.0000, 0.005, "C", "Tail",
      "Zone 안 Pass 2개", near=2, R=0.90),
    S("TLC3_NEAR3", "V", 0.4500, 0.005, "C", "Tail",
      "스펙 근처에 소집단이 몰려 Zone 안 Pass 4개 — 자연 정규 꼬리로는 "
      "n=231 · W=0.5 sigma 에서 2개가 한계라 일부러 이어 붙였다",
      near=2, R=0.90, pile_to=4),
    S("TLC4_ZONE_IN", "V", 1.0000, 0.005, "C", "Tail",
      "꼬리 끝이 UL-0.48 sigma — Zone 안쪽 턱걸이", d=0.48, R=0.98),
    S("TLC5_ZONE_OUT", "V", 1.0500, 0.005, "C", "Separated",
      "꼬리 끝이 UL-0.52 sigma — Zone 바깥 턱걸이 (0.04 sigma 차이로 뒤집힘)",
      d=0.52, R=1.06),

    # D. Core 가 Spec 안에 있는지 (P95_core = Median + 1.6449 sigma_core)
    S("TLD1_CORE_IN", "V", 3.0000, 0.005, "D", "Tail",
      "UL = 1.75 sigma_core > P95_core -> Core 는 Spec 안", mode="nat", ku=1.75),
    S("TLD2_CORE_OUT", "V", 3.6000, 0.005, "D", "Shift",
      "UL = 1.55 sigma_core < P95_core -> Shift/Broadening", mode="nat", ku=1.55),
    S("TLD3_CORE_P02", "V", 0.9000, 0.005, "D", "Tail",
      "UL = 1.68 sigma_core (임계 +2%)", mode="nat", ku=1.68),
    S("TLD4_CORE_M02", "V", 0.7500, 0.005, "D", "Shift",
      "UL = 1.61 sigma_core (임계 -2%)", mode="nat", ku=1.61),

    # E. 분해능이 Gap_Limit 을 지배하는 구간 (Gap_Limit = 3 x 분해능)
    S("TLE1_RES_2Q", "Ohm", 10000.0, 0.005, "E", "Tail",
      "격자 q = 1.25 sigma, 격자 0/1/2/3 이 이어지고 Gap = 2q <= 3q",
      mode="grid", qk=1.25, ku_q=3.5, gnear=[3, 3], goos=[5], trunc=2.0),
    S("TLE2_RES_3Q", "Ohm", 45000.0, 0.005, "E", "Separated",
      "Gap = 3q 로 한계와 정확히 같은데 Separated 로 떨어진다 — 분해능을 '최소 간격'으로 "
      "추정하면 데이터로그 반올림 때문에 항상 q 보다 조금 작게 나오기 때문. 등호 규칙 필요",
      mode="grid", qk=1.25, ku_q=3.5, gnear=[3, 3], goos=[6], trunc=2.0),
    S("TLE3_RES_4Q", "Ohm", 0.0850, 0.005, "E", "Separated",
      "Gap = 4q > 3q", mode="grid", qk=1.25, ku_q=3.5, gnear=[3, 3], goos=[7], trunc=2.0),
    S("TLE5_RES_MIXED", "Ohm", 2200.0, 0.005, "E", "Separated",
      "TLE1 과 분포도 Gap 도 같은데, 격자에서 벗어난 한 쌍(q/4 간격) 때문에 분해능 "
      "추정이 q/4 로 떨어져 한계가 0.75q 가 된다 — 그래프로는 구분 불가",
      mode="grid", qk=1.25, ku_q=3.5, gnear=[3, 3], goos=[5], offgrid=0.25, trunc=2.0),

    # F. MAD = 0 (저분해능이라 중앙값 주변이 한 점에 뭉친 항목)
    S("TLF1_MAD0_NEAR", "V", 0.0150, 0.005, "F", "Separated",
      "sigma_core = 0 -> Zone 폭 0 -> Near-Spec Pass 0개. Gap 은 1q 로 작은데도 탈락",
      mode="grid", qk=1.60, ku_q=2.5, gnear=[2, 2], goos=[3], trunc=2.0),
    S("TLF2_MAD0_FAR", "V", 0.7000, 0.005, "F", "Separated",
      "sigma_core = 0 이고 Gap = 4q > 3q",
      mode="grid", qk=1.60, ku_q=2.5, gnear=[2, 2], goos=[6], trunc=2.0),

    # G. 하한(LL) 측
    S("TLG1_LOW_TAIL", "uA", 20.0000, 0.005, "G", "Tail",
      "하한측 Gap = 0.80 x 한계", side="lo", d_lo=0.10, R_lo=0.80),
    S("TLG2_LOW_SEP", "uA", 55.0000, 0.005, "G", "Separated",
      "하한측 Gap = 1.10 x 한계", side="lo", d_lo=0.10, R_lo=1.10),

    # H. Spec Out 이 여러 개일 때 — 항목 단위 Gap 정의의 사각지대
    S("TLH1_LADDER", "V", 8.0000, 0.005, "H", "Tail",
      "이탈 4건이 꼬리 끝에서 0.5/1.0/1.8/3.0 sigma 로 계단식. 항목 Gap 은 최근접 "
      "1건이 정하므로 +3.0 sigma 짜리까지 전부 Tail 이 된다",
      n_oos=4, d=0.10, R=0.80, extra=[1.0, 1.8, 3.0]),
    S("TLH2_CLUSTER", "V", 2.0000, 0.005, "H", "Separated",
      "이탈 3건이 꼬리 끝에서 1.7~1.9 sigma 에 뭉쳐 있고 모집단과 떨어져 있다",
      n_oos=3, d=0.10, R=3.20, extra=[1.8, 1.9]),
    S("TLH3_BIMODAL", "V", 1.5000, 0.005, "H", "Tail",
      "꼬리에 이어지는 군 3건 + 멀리 떨어진 군 2건이 섞임",
      n_oos=5, d=0.10, R=0.80, extra=[0.68, 0.90, 2.6, 2.8]),

    # I. 상·하한 동시 이탈
    S("TLI1_BOTH", "V", 1.2500, 0.005, "I", "Tail/Separated",
      "상한은 Tail(0.80), 하한은 Separated(1.40) — 최종 분류가 로직에 없다",
      side="both", d=0.10, R=0.80, d_lo=0.10, R_lo=1.40),

    # 정상 항목 — 아무 분기도 안 타야 한다
    S("TLZ1_CLEAN", "V", 2.5000, 0.005, "Z", "Normal", "이탈 없음", n_oos=0, d=0.55),
    S("TLZ2_CLEAN", "V", 1.8000, 0.005, "Z", "Normal", "이탈 없음", n_oos=0, d=0.80),
]

DEVICE_ID_ITEM = {"name": "DEVICE_ID", "unit": "Binnary", "mu": 0.0, "sigma": 0.0,
                  "ll": None, "ul": None, "dec": 0}
EXCLUDED_ITEMS = [
    {"name": "FT_FAIL_STEP", "unit": "FailStep", "mu": 0.0, "sigma": 0.0,
     "ll": None, "ul": None, "dec": 4},
    {"name": "FCLK_MHZ", "unit": "MHz", "mu": 24.0, "sigma": 0.12,
     "ll": 23.0, "ul": 25.0, "dec": 4},
]

# ── 산포 변화 프로파일 (회차 단조 증가 · Cold < Room < Hot) ───────────────────
def build_profile():
    rng = np.random.default_rng(SEED + 77)
    prof = {}
    for it in SCEN + EXCLUDED_ITEMS:
        prof[it["name"]] = {
            "growth": float(rng.uniform(0.08, 0.22)),
            "temp": {"Room": 1.0, "Hot": float(rng.uniform(1.05, 1.15)),
                     "Cold": float(rng.uniform(0.88, 0.96))},
        }
    return prof


PROFILE = build_profile()
FRAC = {"168hrs": 1 / 3.0, "500hrs": 2 / 3.0, "1000hrs": 1.0}


def scale_of(name, temp, readout):
    p = PROFILE.get(name)
    if not p:
        return 1.0
    return p["temp"].get(temp, 1.0) * (1.0 + p["growth"] * FRAC[readout])


def truncated(rng, mu, sigma, size, zmax):
    if sigma == 0:
        return np.full(size, float(mu))
    out = rng.normal(mu, sigma, size)
    for _ in range(80):
        bad = np.abs(out - mu) > zmax * sigma
        if not bad.any():
            break
        out[bad] = rng.normal(mu, sigma, int(bad.sum()))
    return np.clip(out, mu - zmax * sigma, mu + zmax * sigma)


def robust(values):
    v = np.asarray(values, dtype=float)
    med = float(np.median(v))
    return med, KZ * float(np.median(np.abs(v - med)))


def pick_d(pass_vals, maxpass, sc, target, dmax=0.40):
    """Zone 안 Pass 개수가 target 이 되는 d 를 고른다 (UL = maxpass + d x sigma_core).

    d 를 크게 잡으면 한계가 꼬리 끝에서 멀어져 "꼬리가 한계에 못 미치는" 그림이 된다.
    그래서 위쪽을 dmax 로 묶고, 조건을 만족하는 것 중 **가장 작은 d** 를 쓴다.
    """
    hits = []
    for d in np.arange(0.02, dmax + 1e-9, 0.005):
        ul = maxpass + d * sc
        lo = ul - W_K * sc
        cnt = int(((pass_vals >= lo) & (pass_vals <= ul)).sum())
        if cnt == target:
            hits.append(float(d))
    if hits:
        return hits[0]
    # 도달 불가 — 가장 가까운 개수가 나오는 d (모자란 만큼은 pile_to 로 채운다)
    best, bestd = None, 0.10
    for d in np.arange(0.02, dmax + 1e-9, 0.005):
        ul = maxpass + d * sc
        cnt = int(((pass_vals >= ul - W_K * sc) & (pass_vals <= ul)).sum())
        if best is None or abs(cnt - target) < best:
            best, bestd = abs(cnt - target), float(d)
    return bestd


def smooth_tail(col, side, n, cap):
    """꼬리 상위 n 점의 인접 간격을 cap 이하로 눌러 준다.

    n=231 정규 표본에서 최상위 순서통계량 간격은 기댓값이 0.2~0.5 sigma 인데,
    뽑기에 따라 1 sigma 가까이 벌어지기도 한다. 그렇게 되면 "꼬리 끝 한 점이 혼자
    떨어져 있는" 그림이 되어, 정작 판정 대상인 Gap 보다 그 앞 공백이 커진다.
    간격의 **기댓값 범위 안(0.45 sigma)** 으로만 누르는 것이라 꼬리 모양 자체는
    그대로 두면서 우발적인 공백만 없앤다.
    """
    idx = np.argsort(col)
    sel = idx[::-1][:n] if side == "hi" else idx[:n]
    order = sel[::-1]                       # 안쪽부터
    prev = float(col[order[0]])
    for i in order[1:]:
        step = min(abs(float(col[i]) - prev), cap)
        prev = prev + step if side == "hi" else prev - step
        col[i] = prev


# ── 생성 ─────────────────────────────────────────────────────────────────────
def build(root):
    rng = np.random.default_rng(SEED)
    device_ids = ["%d" % (300000000 + i * 7 + 13) for i in range(PRE_UNITS)]
    pre_serials = [200041 + i * 8 for i in range(PRE_UNITS)]
    post_idx = rng.permutation(PRE_UNITS)[:POST_UNITS]
    post_dev = {s: device_ids[post_idx[s - 1]] for s in range(1, POST_UNITS + 1)}

    # 1) Pre
    pre = {}
    for temp, _ in TEMPS:
        r = np.random.default_rng(SEED + (abs(hash(temp)) % 10 ** 6))
        pre[temp] = {it["name"]: truncated(r, it["mu"], it["sigma"], PRE_UNITS,
                                           it.get("trunc", 3.0))
                     for it in SCEN + EXCLUDED_ITEMS}

    # 2) Post 원본. 유닛별 표준정규 벡터는 항목마다 한 번만 뽑아 회차/온도에 걸쳐 쓴다.
    noise = {}
    for it in SCEN + EXCLUDED_ITEMS:
        r = np.random.default_rng(SEED + 991 + (abs(hash(it["name"])) % 10 ** 7))
        noise[it["name"]] = r.normal(0.0, 1.0, POST_UNITS)

    raw = {}
    for temp, _ in TEMPS:
        for readout in READOUTS:
            judged = (temp == "Room" and readout == JUDGED)
            col = {}
            for it in SCEN + EXCLUDED_ITEMS:
                base = np.array([pre[temp][it["name"]][post_idx[s - 1]]
                                 for s in range(1, POST_UNITS + 1)])
                if it in EXCLUDED_ITEMS:
                    col[it["name"]] = base
                    continue
                scale = scale_of(it["name"], temp, readout)
                dev = (base - it["mu"]) * 0.7 + \
                    it["sigma"] * math.sqrt(1.0 - 0.49) * noise[it["name"]]
                target = it["sigma"] * scale
                std = float(np.std(dev)) or target
                dev = dev * (target / std)
                # 판정 조건(Room/1000hrs)은 꼬리를 그대로 둔다 — 꼬리 모양이 핵심이라.
                # 나머지 조건은 잘라서 우발적 Spec Out 을 막는다.
                zmax = it["trunc"] if judged else TRUNC_OTHER
                over = np.abs(dev) > zmax * target
                if over.any():
                    rr = np.random.default_rng(SEED + 5000 + (abs(hash(
                        (it["name"], temp, readout))) % 10 ** 6))
                    dev[over] = np.sign(dev[over]) * target * (
                        zmax - 0.35 * rr.random(int(over.sum())))
                col[it["name"]] = it["mu"] + dev
            raw[(temp, readout)] = col

    # 3) 양자화(측정 분해능) — 전 조합에 같은 격자
    for it in SCEN:
        if not it["qk"]:
            continue
        it["q"] = it["qk"] * it["sigma"] * scale_of(it["name"], "Room", JUDGED)
        for key in raw:
            v = raw[key][it["name"]]
            raw[key][it["name"]] = it["mu"] + np.round((v - it["mu"]) / it["q"]) * it["q"]

    # 4) 판정 조건에서 스펙 한계를 정하고 최상위 몇 점만 바깥으로 옮긴다
    judged_col = raw[("Room", JUDGED)]
    for it in SCEN:
        col = judged_col[it["name"]]
        med, sc = robust(col)
        it["med"], it["sc"] = med, sc
        it["serials"] = []

        if it["mode"] == "nat":
            it["ul"] = med + it["ku"] * sc
            it["ll"] = min(med - 6.0 * sc, float(col.min()) - 0.3 * sc)

        elif it["mode"] == "grid":
            it["ul"] = med + it["ku_q"] * it["q"]
            it["ll"] = med - (it["ku_q"] + 3) * it["q"]
            # 격자 배치 — 자연 최대 격자 바로 위에 이어 붙인다
            free = list(_free_serials(it))
            for g in it["gnear"] + it["goos"]:
                s = free.pop(0); it["serials"].append(s)
                col[s - 1] = med + g * it["q"]
            if it["offgrid"]:
                for val in (med, med + it["offgrid"] * it["q"]):
                    s = free.pop(0); it["serials"].append(s)
                    col[s - 1] = val

        else:   # mode == "tail"
            sc0 = sc
            if it["side"] in ("hi", "both"):
                smooth_tail(col, "hi", it["n_oos"] + 8, 0.45 * sc0)
            if it["side"] in ("lo", "both"):
                smooth_tail(col, "lo", it["n_oos_lo"] + 8, 0.45 * sc0)
            order = np.argsort(col)[::-1]          # 큰 값부터
            # ── 상한측
            if it["side"] in ("hi", "both"):
                k = it["n_oos"]
                mp_idx = int(order[k])
                maxpass = float(col[mp_idx])
                others = np.delete(col, order[:k]) if k else col
                d = it["d"] if it["d"] is not None else pick_d(others, maxpass, sc0, it["near"])
                it["d_used"] = d
                it["ul"] = maxpass + d * sc0
                offs = [it["R"] * GAP_K] + list(it["extra"])
                assert not k or offs[0] > d, (it["name"], "R x GAP_K 가 d 보다 커야 한다")
                for i in range(k):
                    idx = int(order[i])
                    col[idx] = maxpass + offs[i] * sc0
                    it["serials"].append(idx + 1)
                if it["pile_to"]:
                    # Zone 안 개수를 목표까지 채운다 — 자연 꼬리에 이어 붙이는 방식
                    lo = it["ul"] - W_K * sc0
                    have = int(((others >= lo) & (others <= it["ul"])).sum())
                    free = [x for x in _free_serials(it)]
                    span = maxpass - lo
                    need = max(0, it["pile_to"] - have)
                    for j in range(need):
                        sn = free.pop(0); it["serials"].append(sn)
                        col[sn - 1] = maxpass - span * (j + 1) / (need + 1.0)
            else:
                it["ul"] = min(med + 6.0 * sc, float(col.max()) + 0.3 * sc)
            # ── 하한측
            if it["side"] in ("lo", "both"):
                k = it["n_oos_lo"]
                asc = np.argsort(col)
                mp_idx = int(asc[k])
                minpass = float(col[mp_idx])
                others = np.delete(col, asc[:k]) if k else col
                d = it["d_lo"] if it["d_lo"] is not None else \
                    pick_d(-others, -minpass, sc0, it["near_lo"])
                it["d_lo_used"] = d
                it["ll"] = minpass - d * sc0
                offs = [it["R_lo"] * GAP_K] + list(it["extra_lo"])
                assert not k or offs[0] > d, (it["name"], "R_lo x GAP_K 가 d_lo 보다 커야 한다")
                for i in range(k):
                    idx = int(asc[i])
                    col[idx] = minpass - offs[i] * sc0
                    it["serials"].append(idx + 1)
            else:
                it["ll"] = max(med - 6.0 * sc, float(col.min()) - 0.3 * sc)

        span = max(abs(it["ul"] - it["ll"]), abs(it["mu"]) * 1e-6)
        it["dec"] = max(4, int(math.ceil(-math.log10(span / 20000.0))))

    # 4b) 판정 조건이 아닌 회차/온도에서는 스펙 안으로 되접는다.
    #     꼬리를 살리려고 Room/1000hrs 의 절단을 풀었더니, 같은 절단 폭으로는 다른
    #     조건(특히 Hot, 산포가 1.15배)에서 우발적 Spec Out 이 생겼다. 한계에서
    #     0.10 sigma_core 안쪽으로 되접어 "판정은 마지막 회차에만" 을 지킨다.
    for key, col in raw.items():
        if key == ("Room", JUDGED):
            continue
        for it in SCEN:
            if it["mode"] == "nat":
                continue          # D 그룹은 설계상 모든 조건에서 이탈한다
            v = col[it["name"]]
            sc = it["sc"] or (it.get("q") or 1.0)
            hi = it["ul"] - 0.10 * sc
            lo = it["ll"] + 0.10 * sc
            over = v > hi
            v[over] = hi - (v[over] - hi)
            under = v < lo
            v[under] = lo + (lo - v[under])
            if it["qk"]:
                col[it["name"]] = it["mu"] + np.round((v - it["mu"]) / it["q"]) * it["q"]

    # 5) 파일 쓰기
    columns = SCEN[:16] + [DEVICE_ID_ITEM] + SCEN[16:] + EXCLUDED_ITEMS
    written = []
    for temp, code in TEMPS:
        title = "%s_%s_AAA_K002_%s_PRE" % (DEVICE, code, temp.upper())
        rows = []
        for i in range(PRE_UNITS):
            values = {it["name"]: (device_ids[i] if it["name"] == "DEVICE_ID"
                                   else pre[temp][it["name"]][i]) for it in columns}
            rows.append({"serial": pre_serials[i], "bin": 1, "values": values})
        written.append(write_csv(os.path.join(root, "00_Pre", title + ".csv"),
                                 title, columns, rows))

        for readout in READOUTS:
            col = raw[(temp, readout)]
            title = "%s_%s_AAA_K002_%s_HTOL_%s" % (DEVICE, code, temp.upper(), readout)
            rows = []
            for serial in range(1, POST_UNITS + 1):
                values, oos = {}, False
                for it in columns:
                    if it["name"] == "DEVICE_ID":
                        values[it["name"]] = post_dev[serial]
                        continue
                    v = float(col[it["name"]][serial - 1])
                    values[it["name"]] = v
                    ul, ll = it.get("ul"), it.get("ll")
                    if (ul is not None and v > ul) or (ll is not None and v < ll):
                        oos = True
                rows.append({"serial": serial, "bin": 5 if oos else 1, "values": values})
            written.append(write_csv(os.path.join(root, "01_Post", title + ".csv"),
                                     title, columns, rows))

    import json
    manifest = {it["name"]: {"serials": sorted(it["serials"]),
                             "ul": it["ul"], "ll": it["ll"],
                             "sigma_core": it["sc"], "median": it["med"],
                             "d": it.get("d_used", it.get("d")),
                             "d_lo": it.get("d_lo_used", it.get("d_lo"))}
                for it in SCEN}
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "known02_manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return written


_FREE_POOL = {}


def _free_serials(it):
    """항목마다 겹치지 않는 여분 Serial 을 준다 (격자 배치·소집단용)."""
    names = [x["name"] for x in SCEN]
    start = 1 + (names.index(it["name"]) * 7) % 40
    used = set(it["serials"])
    return [s for s in range(start, POST_UNITS + 1) if s not in used]


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Known Data")
    files = build(os.path.join(root, DEVICE, FOLDER))
    print("생성 %d개 · 시나리오 항목 %d" % (len(files), len(SCEN)))
    for path in files:
        print("  %8.1f KB  %s" % (os.path.getsize(path) / 1024, os.path.relpath(path, root)))


if __name__ == "__main__":
    main()
