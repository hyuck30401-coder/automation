# -*- coding: utf-8 -*-
"""툴 검증용 Known-answer 데이터셋 생성기.

정답을 미리 아는 합성 데이터를 만든다. 실제 데이터로그 레이아웃(§3-2)과 폴더
규약(§3-1)을 그대로 따르므로, 툴이 이 데이터를 읽고 내는 판정을 ANSWER.md 와
1:1 로 대조할 수 있다.

  시험 항목   HTOL
  Read-out    Pre / 168hrs / 500hrs / 1000hrs   (판정은 마지막 1000hrs)
  FT Temp     Room / Hot / Cold                 (이상 건은 Room 에만)
  Sample      Post 231 유닛, Pre 800 유닛(로트 전체 ListAll)

주의: Slight/Tail/Abnormal Pass 는 Grubbs 임계(표본 분포)로 갈리므로 "값을 넣으면
그 판정이 나온다"가 성립하지 않는다. 생성 -> 판정 -> 조정 루프로 수렴시킨 뒤
그 결과를 ANSWER.md 에 박는다. 시드 고정이라 재생성하면 같은 파일이 나온다.
"""
import io
import math
import os
import sys

import numpy as np

SEED = 20260905
PRE_UNITS = 800
POST_UNITS = 231
TEMPS = [("Room", "ER01"), ("Hot", "EH01"), ("Cold", "EC01")]
READOUTS = ["168hrs", "500hrs", "1000hrs"]
JUDGED = "1000hrs"

DEVICE = "KNOWN01"
FOLDER = "00_KV1-0_K001_K01"

# ── 테스트 항목 정의 ───────────────────────────────────────────────────────────
# rel_sigma : 값 산포 / 평균.  drift_mu/drift_sigma : 회차별 변화율 분포.
# 케이스별로 필요한 성질이 달라 항목마다 다르게 준다 (아래 각 주석 참조).
def _decimals(mu):
    """산포가 표기 자릿수에 뭉개지지 않을 만큼의 소수 자릿수.

    처음에 전 항목을 %.4f 로 썼더니 VOS_AMP(mu=0.015, sigma=7.5e-5) 가 0.0150 하나로
    양자화됐다. 변화율 분포가 이산 격자가 되면서 168hrs 에서 유닛 11대가 가짜 Delta 로
    잡혔다 — 데이터 생성 쪽 결함이지 툴 문제가 아니었다.
    """
    import math
    return max(4, 5 - int(math.floor(math.log10(abs(mu))))) if mu else 4


def item(name, unit, mu, rel_sigma, drift_mu, drift_sigma, spec_k=6.0, role=""):
    sigma = abs(mu) * rel_sigma
    return {
        "name": name, "unit": unit, "mu": mu, "sigma": sigma,
        "ll": mu - spec_k * sigma, "ul": mu + spec_k * sigma,
        "drift_mu": drift_mu, "drift_sigma": drift_sigma, "role": role,
        "dec": _decimals(mu),
    }


ITEMS = [
    # Excessive 3건 — 스펙에서 1% 이상(spec_margin_ratio 는 한계값 대비 비율) 벗어남
    item("VOUT_1V8",     "V",  1.800, 0.005, -0.0010, 0.00030, role="Excessive"),
    item("ICC_ACTIVE",  "mA", 12.500, 0.005,  0.0015, 0.00030, role="Excessive"),
    item("RPULLUP",    "Ohm", 10000.0, 0.005, 0.0012, 0.00030, role="Excessive"),
    # Slight 3건 — 스펙 이탈 1% 미만 + Mea_S·Diff_S 둘 다 임계 초과
    #   Pre 는 평균 근처인데 크게 움직여서 막 벗어난 케이스
    item("VOUT_3V3",     "V",  3.300, 0.005, -0.0010, 0.00025, role="Slight"),
    item("ILIM_SET",    "mA",  2.400, 0.005,  0.0012, 0.00025, role="Slight"),
    item("RDSON",      "Ohm",  0.085, 0.005,  0.0015, 0.00025, role="Slight"),
    # Tail 3건 — 스펙 이탈 1% 미만인데 이동량은 집단 범위 안
    #   Pre 부터 이미 규격 끝에 붙어 있다가 평범하게 밀려서 넘어간 케이스
    item("VREF_BG",      "V",  1.200, 0.005, -0.0005, 0.00150, role="Tail"),
    item("ISHDN",       "uA",  1.500, 0.005, -0.0005, 0.00150, role="Tail"),
    item("GM_EA",        "mS",  0.450, 0.005, -0.0005, 0.00150, role="Tail"),
    # Unstable 3건 — 유닛은 최종 fail, 이 항목만 회차 사이 spec pass 를 찍음
    item("VDD_UVLO",     "V",  2.700, 0.005, -0.0008, 0.00030, role="Unstable"),
    item("ICC_SLEEP",   "uA", 35.000, 0.005,  0.0012, 0.00030, role="Unstable"),
    item("VOS_AMP",      "V",  0.015, 0.005,  0.0010, 0.00030, role="Unstable"),
    # Abnormal Pass · Measured 3건 — Pre 부터 집단에서 튀지만 이동은 평범
    item("VOUT_5V0",     "V",  5.000, 0.005, -0.0008, 0.00030, spec_k=12.0, role="Measured"),
    item("VLDO_1V2",     "V",  1.200, 0.005, -0.0008, 0.00030, spec_k=12.0, role="Measured"),
    item("ILEAK_IO",    "uA",  0.800, 0.005,  0.0010, 0.00030, spec_k=12.0, role="Measured"),
    # Abnormal Pass · Delta 3건 — 이동만 유독 큼
    #   값 산포는 넓고(1%) 이동 산포는 아주 좁게(0.02%) 둬야 Diff 축만 걸린다
    item("VSTART",       "V",  2.100, 0.010, -0.0010, 0.00050, role="Delta"),
    item("VCLAMP",       "V",  6.000, 0.010,  0.0010, 0.00050, role="Delta"),
    item("ICC_STBY",    "uA", 55.000, 0.010,  0.0010, 0.00050, role="Delta"),
    # Abnormal Pass · Measured + Delta 3건 — 원래도 튀는데 이동까지 큼
    item("VOUT_1V0",     "V",  1.000, 0.005, -0.0008, 0.00025, spec_k=12.0, role="Measured + Delta"),
    item("IBIAS",       "uA", 20.000, 0.005,  0.0010, 0.00025, spec_k=12.0, role="Measured + Delta"),
    item("RSENSE",     "Ohm",  0.050, 0.005,  0.0012, 0.00025, spec_k=12.0, role="Measured + Delta"),
    # Abnormal Pass 인데 "스펙 대비 이동은 미미" 3건 — 스펙 게이트(tau=5%)에 접혀야 한다.
    #   Mea 축: |값-평균|/스펙폭 = z / (2 x spec_k). spec_k 를 크게(=Cp 가 과한 항목) 잡으면
    #   z 가 임계를 넘어도 스펙 대비로는 미미하다 — R-029 가 겨냥한 바로 그 상황이다.
    item("VBG_TRIM",     "V",  1.250, 0.005, -0.0008, 0.00030, spec_k=60.0, role="Marginal(Measured)"),
    item("IDD_LP",      "uA",  9.000, 0.010,  0.0010, 0.00050, spec_k=30.0, role="Marginal(Delta)"),
    item("VTEMP",        "V",  0.700, 0.005,  0.0010, 0.00025, spec_k=60.0, role="Marginal(Measured + Delta)"),
    # Tail 판정 세트 3건 — 위 207~209(Marginal 세트)와 같은 성격이지만 fail_type 분류
    # 자체를 따로 검증하려고 항목을 분리해 둔다.
    item("VPP_MON",      "V",  8.000, 0.005, -0.0005, 0.00150, role="Tail2"),
    item("IREF_TRIM",   "uA",  6.400, 0.005, -0.0005, 0.00150, role="Tail2"),
    item("RDIV_TOP",   "Ohm", 45000.0, 0.005, -0.0005, 0.00150, role="Tail2"),
    # ── 경계 케이스 ──────────────────────────────────────────────────────────
    # Excessive / 그 외 경계: spec_margin_ratio = |값-한계|/한계 가 1% 인 지점
    item("BND_EXC_IN",   "V",  3.000, 0.005,  0.0010, 0.00030, role="Bnd:Excessive+"),
    item("BND_EXC_OUT",  "V",  3.000, 0.005,  0.0010, 0.00030, role="Bnd:Excessive-"),
    # Slight / Tail 경계: Diff_S 가 Grubbs 임계인 지점 (Mea 는 확실히 초과)
    item("BND_SLT_IN",   "V",  2.000, 0.005,  0.0010, 0.00150, role="Bnd:Slight+"),
    item("BND_SLT_OUT",  "V",  2.000, 0.005,  0.0010, 0.00150, role="Bnd:Slight-"),
    # Abnormal Pass 산포 기준 경계: Mea_S / Diff_S 가 Grubbs 임계인 지점
    item("BND_MEA_IN",   "V",  1.500, 0.005, -0.0008, 0.00030, spec_k=12.0, role="Bnd:Mea+"),
    item("BND_MEA_OUT",  "V",  1.500, 0.005, -0.0008, 0.00030, spec_k=12.0, role="Bnd:Mea-"),
    item("BND_DLT_IN",  "uA", 30.000, 0.010,  0.0010, 0.00300, role="Bnd:Delta+"),
    item("BND_DLT_OUT", "uA", 30.000, 0.010,  0.0010, 0.00300, role="Bnd:Delta-"),
    # Abnormal Pass 스펙 대비 기준 경계: 이동량/스펙폭 = tau(5%) 인 지점
    item("BND_TAU_IN",   "V",  1.800, 0.005, -0.0008, 0.00030, spec_k=60.0, role="Bnd:Tau+"),
    item("BND_TAU_OUT",  "V",  1.800, 0.005, -0.0008, 0.00030, spec_k=60.0, role="Bnd:Tau-"),
    # 정상 항목 (아무것도 안 걸려야 한다)
    item("VOUT_2V5",     "V",  2.500, 0.005, -0.0008, 0.00030),
    item("ICC_BURST",   "mA",  4.200, 0.005,  0.0010, 0.00030),
    item("VTH_COMP",     "V",  0.600, 0.005,  0.0008, 0.00030),
]
CLEAN_ITEMS = [it["name"] for it in ITEMS if not it["role"]]

# 단위 필터(§3-5)로 제외돼야 하는 항목 — 화면에 안 나오는 게 정답이다
EXCLUDED_ITEMS = [
    {"name": "FT_FAIL_STEP", "unit": "FailStep", "mu": 0.0, "sigma": 0.0, "ll": None, "ul": None, "dec": 4},
    # mOhm 은 지금 코드에서 "허용" 이다(CLAUDE.md §3-5 의 제외 목록은 stale). 확실히
    # 제외되는 단위로 골라야 필터 검증이 성립하므로 MHz 를 쓴다.
    {"name": "FCLK_MHZ", "unit": "MHz", "mu": 24.0, "sigma": 0.12, "ll": 23.0, "ul": 25.0, "dec": 4},
]


TRUNCATE_Z = 3.0        # Pre 정상 유닛의 |z| 상한
TRUNCATE_Z_POST = 3.2   # Post 정상 유닛의 |z| 상한 (그 조합의 sigma 기준)


def _normal(rng, mu, sigma, size):
    """|z| <= TRUNCATE_Z 로 잘린 정규분포.

    자르는 이유: known-answer 데이터에 "우연히 생긴 진짜 이상치"가 있으면 안 된다.
    231유닛 x 24항목이면 alpha=0.01 Grubbs 에서 우발적 flag 가 실제로 나왔다(시드 초기
    검증에서 #70 이 VCLAMP 에 걸렸다). 정상 유닛은 확실히 임계(약 4.02) 아래에 두고,
    이상 건은 주입으로만 만든다.
    """
    if sigma == 0:
        return np.full(size, float(mu))
    out = rng.normal(mu, sigma, size)
    for _ in range(64):
        bad = np.abs(out - mu) > TRUNCATE_Z * sigma
        if not bad.any():
            break
        out[bad] = rng.normal(mu, sigma, int(bad.sum()))
    return np.clip(out, mu - TRUNCATE_Z * sigma, mu + TRUNCATE_Z * sigma)


DEVICE_ID_ITEM = {"name": "DEVICE_ID", "unit": "Binnary", "mu": 0.0, "sigma": 0.0,
                  "ll": None, "ul": None, "role": "", "dec": 0}

# ── 심을 케이스 ───────────────────────────────────────────────────────────────
# 유형마다 항목을 따로 준다 — 같은 항목에 이상치를 여러 개 넣으면 Grubbs(단일 이상치
# 검정)에서 서로 가려져(masking) 판정이 흔들린다.
def _cases():
    """Serial 배정. 유형마다 항목을 따로 준다 — 같은 항목에 이상치를 여러 개 넣으면
    Grubbs(단일 이상치 검정)에서 서로 가려져(masking) 판정이 흔들린다."""
    roles = {}
    for it in ITEMS:
        if it["role"]:
            roles.setdefault(it["role"], []).append(it["name"])
    order = [
        # (역할, 시작 Serial)
        ("Excessive", 201), ("Slight", 204), ("Tail", 207), ("Unstable", 210),
        ("Measured", 216), ("Delta", 219), ("Measured + Delta", 222),
        ("Marginal(Measured)", 225), ("Marginal(Delta)", 226),
        ("Marginal(Measured + Delta)", 227),
        ("Tail2", 186),
        ("Bnd:Excessive+", 189), ("Bnd:Excessive-", 190),
        ("Bnd:Slight+", 191), ("Bnd:Slight-", 192),
        ("Bnd:Mea+", 193), ("Bnd:Mea-", 194),
        ("Bnd:Delta+", 195), ("Bnd:Delta-", 196),
        ("Bnd:Tau+", 197), ("Bnd:Tau-", 198),
    ]
    out = []
    for role, start in order:
        for offset, name in enumerate(roles[role]):
            out.append({"serial": start + offset, "kind": role, "item": name})
    # Intermittent 는 유닛 레벨이라 전용 항목이 없다 — Slight 항목을 재사용한다.
    for i, name in enumerate(roles["Slight"]):
        out.append({"serial": 213 + i, "kind": "Intermittent", "item": name})
    return out


def expected_reason(kind):
    """Abnormal Pass 의 기대 reason. Marginal(...) 은 게이트에서만 갈리고 reason 은 같다."""
    return kind[len("Marginal("):-1] if kind.startswith("Marginal(") else kind


CASES = _cases()
FAIL_KINDS = ("Excessive", "Slight", "Tail", "Unstable", "Intermittent")
NO_PRE_SERIALS = [230, 231]        # DEVICE_ID 를 비워 NO PRE SAMPLE 경로를 태운다
DUP_PRE_COUNT = 5                  # Pre 에 DEVICE_ID 중복 (마지막 등장 채택, §3-3)

# (pre_z, post_z) — 그 항목 표본표준편차의 몇 배로 놓을지.
# n=231 · alpha=0.01 의 Grubbs 임계는 약 4.02 다. 확실히 넘기거나 확실히 밑돌게 잡는다.
#   Excessive  스펙 이탈 >= 1%(한계값 대비)
#   Slight     이탈 < 1% + Mea·Diff 둘 다 초과  -> 평균에서 크게 이동
#   Tail       이탈 < 1% + 이동은 평범          -> 원래 규격 끝에 붙어 있던 유닛
#   Measured   Pre 부터 튀고 이동은 0           -> Diff 축은 안 걸린다
#   Delta      값은 평범, 이동만 큼             -> Mea 축은 안 걸린다
TUNE = {
    "Excessive":        (0.0, 9.0),
    "Slight":           (0.0, 6.4),
    # Tail 의 pre_z 는 두 조건을 동시에 만족해야 한다: 1000hrs 이동량이 집단 범위 안이
    # 되도록 6.4 에 충분히 가깝고(안 그러면 Diff 축도 걸려 Slight 가 된다), 168/500hrs
    # 에서는 규격(6.0σ) 안에 남을 것(안 그러면 앞 회차에서 이미 fail 이 된다).
    "Tail":             (5.92, 0.0),   # post 는 SPEC_BASED 가 정한다
    "Unstable":         (0.0, 7.5),
    "Intermittent":     (0.0, 8.0),
    "Measured":         (5.2, 5.2),
    # 이동량/스펙폭 = post_z / (2 x spec_k). spec_k=6 이면 post_z 0.45 -> 3.75% 로
    # 스펙 게이트(5%)에 걸려버린다. 0.85 -> 7.1% 로 올려 "산포 기준에서만 보이는 건"과
    # 겹치지 않게 한다. Mea_S 는 0.85 라 여전히 Diff 축만 걸린다.
    "Delta":            (0.0, 2.50),
    "Measured + Delta": (2.0, 7.0),   # 산포 확대 잡음보다 이동이 확실히 커야 Diff 축이 걸린다
    # 아래 3건은 판정은 그대로 SELECT 이고, "스펙 대비 기준" 탭에서만 접힌다.
    "Marginal(Measured)":          (5.2, 5.2),    # 5.2 / 120 = 4.3% < 5%
    "Marginal(Delta)":             (0.0, 2.50),   # 2.5 / 60 = 4.2% < 5%
    "Marginal(Measured + Delta)":  (3.2, 5.4),    # max(4.5%, 1.83%) < 5%
    "Tail2":            (5.92, 0.0),   # 207~209 와 같은 방식
    # ── 경계 ──
    # spec_margin_ratio 는 쓰인 값과 한계값만으로 정해진다(표본과 무관) -> 해석적으로 계산.
    #   UL = mu(1 + 6 x rel_sigma) = 1.03 mu.  ratio r 이면 post_z = (1.03(1+r) - 1)/0.005
    "Bnd:Excessive+":   (0.0, 8.163),             # r = 1.05%  -> Excessive
    "Bnd:Excessive-":   (0.0, 7.957),             # r = 0.95%  -> Excessive 아님
    # tau 경계도 해석적: Mea 축 size = post_z / (2 x spec_k) = post_z / 120
    "Bnd:Tau+":         (6.24, 6.24),             # 5.2% -> 스펙 대비 기준에서 유지
    "Bnd:Tau-":         (5.76, 5.76),             # 4.8% -> 접힘
    # 아래 4쌍은 Grubbs 임계(표본 sigma 에 의존)에 걸리므로 캘리브레이션으로 맞춘다.
    # 초기값일 뿐이고 tools/known_data_calib.json 이 있으면 그 값이 우선한다.
    # Slight/Tail 경계는 Diff_S 로 갈린다 -> pre 위치(pre_z)를 캘리브레이션한다.
    "Bnd:Slight+":      (4.20, 0.0),
    "Bnd:Slight-":      (5.85, 0.0),
    "Bnd:Mea+":         (4.20, 4.20),
    "Bnd:Mea-":         (3.85, 3.85),
    "Bnd:Delta+":       (0.0, 1.35),
    "Bnd:Delta-":       (0.0, 1.20),
}

# 스펙 기준으로 넣는 케이스: 값을 "한계값 대비 이탈률" 로 직접 정한다.
# sigma 가 회차/온도마다 달라져도 스펙은 고정이므로 이쪽은 산포 변화에 영향을 안 받는다.
# (z 기준 케이스는 sigma_scale 을 곱해 z 를 보존한다 — 아래 post_values 참조)
SPEC_BASED = {
    "Excessive":      0.0150,    # 한계값 대비 1.5% 이탈 -> Excessive (>= 1%)
    "Bnd:Excessive+": 0.0105,    # 1.05% -> Excessive
    "Bnd:Excessive-": 0.0095,    # 0.95% -> Excessive 아님
    "Slight":         0.0020,    # 0.2% 이탈 + 크게 이동 -> Slight
    "Bnd:Slight+":    0.0020,
    "Bnd:Slight-":    0.0020,
    "Tail":           0.0020,    # 0.2% 이탈 + 이동은 평범 -> Tail
    "Tail2":          0.0020,
    "Unstable":       0.0060,
    "Intermittent":   0.0080,
}

# 스펙폭 대비 "이동/이탈 크기" 로 직접 넣는 케이스. spec_relative_size 가 이 값이 된다.
SIZE_BASED = {
    "Marginal(Measured)":         0.043,   # < tau(5%) -> 스펙 대비 기준에서 접힘
    "Marginal(Measured + Delta)": 0.045,
    "Bnd:Tau+":                   0.052,   # > tau -> 유지
    "Bnd:Tau-":                   0.048,   # < tau -> 접힘
}

# 캘리브레이션 결과(있으면 TUNE 을 덮는다). tools/calibrate_known_data.py 가 쓴다.
_CALIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known_data_calib.json")
if os.path.exists(_CALIB):
    import json
    with io.open(_CALIB, encoding="utf-8") as _fh:
        for _k, _v in json.load(_fh).items():
            if _k not in TUNE:
                continue
            TUNE[_k] = (float(_v[0]), float(_v[1])) if isinstance(_v, (list, tuple)) \
                else (TUNE[_k][0], float(_v))


# ── 산포(sigma) 변화 프로파일 ────────────────────────────────────────────────
# 리드아웃이 진행될수록, 그리고 온도에 따라 산포가 달라지는 양상을 데이터에 넣는다.
#   sigma(항목, 온도, 회차) = sigma_pre x temp_factor(항목, 온도) x (1 + growth(항목) x 진행도)
# 항목마다 크기는 랜덤이지만 **한 번 뽑으면 고정**이라, 회차 순서(168<500<1000)와
# 온도 순서(예: 이 항목은 항상 Hot > Room > Cold)가 어느 조합에서도 뒤집히지 않는다.
#
# 산포를 키우는 방식이 중요하다. "전 유닛을 평균 중심으로 균등 확대"하면 값이 튀는
# 유닛은 변화율도 같이 튀게 되어 Measured(값만 튐) / Delta(이동만 큼) 를 분리할 수
# 없다. 그래서 **독립 잡음을 더하는** 모델을 쓴다 — 스트레스가 유닛마다 다르게 작용해
# 산포가 늘어나는 실제 양상과도 맞는다.
#   post = pre x (1 + drift) + eps,   eps ~ N(0, sigma_pre x sqrt(scale^2 - 1))
#
# Diff 축에 기대는 케이스(Delta 계열)가 심긴 항목은 이 추가 잡음이 곧 변화율 산포라
# 성장률을 작게 잡아야 판정이 유지된다. 그래서 항목군별로 범위를 다르게 준다.
# 산포 변화에 민감한 케이스가 심긴 항목 — 성장률을 작게 준다.
#   Delta 계열: 추가 잡음이 곧 변화율 산포라, 성장률이 크면 Diff_S 가 묻힌다.
#   스펙 대비 게이트 계열: 스펙 기준 크기를 고정하면 sigma 가 커질수록 z 가 작아져
#                          Grubbs 임계 아래로 내려간다.
DIFF_SENSITIVE = ("Delta", "Marginal(Delta)", "Bnd:Delta+", "Bnd:Delta-",
                  "Marginal(Measured)", "Marginal(Measured + Delta)",
                  "Bnd:Tau+", "Bnd:Tau-")
GROWTH_RANGE = {"diff": (0.04, 0.09), "other": (0.10, 0.35)}
TEMP_RANGE = {"Hot": (1.06, 1.30), "Cold": (0.78, 0.94), "Room": (1.0, 1.0)}
TEMP_RANGE_DIFF = {"Hot": (1.06, 1.14), "Cold": (0.88, 0.95), "Room": (1.0, 1.0)}


def build_sigma_profile():
    rng = np.random.default_rng(SEED + 77)
    prof = {}
    for it in ITEMS + EXCLUDED_ITEMS:
        diff_side = it.get("role") in DIFF_SENSITIVE
        lo, hi = GROWTH_RANGE["diff" if diff_side else "other"]
        table = TEMP_RANGE_DIFF if diff_side else TEMP_RANGE
        prof[it["name"]] = {
            "growth": float(rng.uniform(lo, hi)),
            "temp": {t: (1.0 if t == "Room" else float(rng.uniform(*table[t]))) for t, _ in TEMPS},
        }
    return prof


SIGMA_PROFILE = build_sigma_profile()


_NOISE_CACHE = {}


def unit_noise(name, temp):
    """항목 x 온도마다 고정된 표준정규 벡터 (회차가 바뀌어도 같은 벡터를 쓴다)."""
    # 온도와 회차에 걸쳐 같은 벡터를 쓴다. 온도마다 새로 뽑으면 표본 sigma 가 흔들려
    # 온도 순서(Cold < Room < Hot)가 항목의 절반쯤에서 뒤집힌다 — 배율 차이가 표본
    # 오차(231 유닛에서 약 +-4.6%)에 묻히기 때문이다. 물리적으로도 "그 유닛이 얼마나
    # 열화했나"는 측정 온도와 무관한 하나의 값이므로 이쪽이 자연스럽다.
    # 결과: sigma 는 sigma_pre x temp_factor x (1 + growth x 진행도) 를 정확히 따라간다.
    if name not in _NOISE_CACHE:
        r = np.random.default_rng(SEED + 991 + (abs(hash(name)) % 10 ** 7))
        _NOISE_CACHE[name] = {"drift": _normal(r, 0.0, 1.0, POST_UNITS),
                              "extra": _normal(r, 0.0, 1.0, POST_UNITS)}
    return _NOISE_CACHE[name]


def sigma_scale(name, temp, frac):
    """그 조합에서 sigma 가 Pre 대비 몇 배인지."""
    prof = SIGMA_PROFILE.get(name)
    if not prof:
        return 1.0
    return prof["temp"].get(temp, 1.0) * (1.0 + prof["growth"] * frac)


# ── CSV 쓰기 (§3-2 레이아웃 그대로) ───────────────────────────────────────────
META_ROWS = 46      # 1~46행은 로그 메타. 11행에 "Test Name" 라벨을 또 둔다(디코이).
LEAD = ["Site #", "Serial #", "Bin", "XCoord", "YCoord"]


def _fmt(it, value):
    if it["name"] == "DEVICE_ID":
        return str(value)
    if it["unit"] == "FailStep":
        return "0"
    return "%.*f" % (it["dec"], float(value))


def write_csv(path, title, items, rows):
    """rows: [{serial, bin, values{item: 값}}] — 순서대로 쓴다(재시험 행 반복 허용)."""
    width = len(LEAD) + 1 + len(items)

    def blank():
        return [""] * width

    out = []
    for i in range(META_ROWS):
        line = blank()
        if i == 0:
            line[0], line[1], line[2] = "S", "HTOL", title
        elif i == 2:
            line[0], line[1] = "Report Generated by", "ETS Datalog Converter"
        elif i == 8:
            line[0], line[1] = "Reporting Station", "GMTEST"
        elif i == 10:
            line[0], line[1] = "Test Name", title      # 디코이 — 파서가 47행을 골라야 한다
        out.append(line)

    def meta(label, pick):
        line = blank()
        line[0] = label
        for j, it in enumerate(items):
            line[len(LEAD) + 1 + j] = pick(it)
        return line

    out.append(meta("Test Name", lambda it: it["name"]))
    out.append(meta("Test Number", lambda it: "%d.%d" % (items.index(it) // 10 + 1, items.index(it) % 10 + 1)))
    out.append(meta("Lower Limit", lambda it: "" if it["ll"] is None else "%.*f" % (it["dec"], it["ll"])))
    out.append(meta("Upper Limit", lambda it: "" if it["ul"] is None else "%.*f" % (it["dec"], it["ul"])))
    out.append(meta("Units", lambda it: it["unit"]))
    header = blank()
    header[: len(LEAD)] = LEAD
    out.append(header)
    for row in rows:
        line = blank()
        line[0] = str((row["serial"] - 1) % 4 + 1)
        line[1] = str(row["serial"])
        line[2] = str(row["bin"])
        line[3] = line[4] = "N/A"
        for j, it in enumerate(items):
            line[len(LEAD) + 1 + j] = _fmt(it, row["values"][it["name"]])
        out.append(line)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        for line in out:
            fh.write(",".join(line) + "\n")
    return path


# ── 생성 ─────────────────────────────────────────────────────────────────────
CASE_BY_SERIAL = {c["serial"]: c for c in CASES}
COLUMNS = ITEMS[:12] + [DEVICE_ID_ITEM] + ITEMS[12:] + EXCLUDED_ITEMS   # DEVICE_ID 는 중간 열


def build(root):
    rng = np.random.default_rng(SEED)
    device_ids = ["%d" % (200000000 + i * 7 + 13) for i in range(PRE_UNITS)]
    pre_serials = [str(100041 + i * 8) for i in range(PRE_UNITS)]
    post_idx = rng.permutation(PRE_UNITS)[:POST_UNITS]        # 시험 투입 231 유닛
    post_dev = {s: device_ids[post_idx[s - 1]] for s in range(1, POST_UNITS + 1)}
    for s in NO_PRE_SERIALS:
        post_dev[s] = ""                                       # DEVICE_ID 공란 → NO PRE SAMPLE

    def pre_values(temp):
        r = np.random.default_rng(SEED + (abs(hash(temp)) % 10 ** 6))
        vals = {}
        for it in ITEMS:
            vals[it["name"]] = _normal(r, it["mu"], it["sigma"], PRE_UNITS)
        for it in EXCLUDED_ITEMS:
            vals[it["name"]] = _normal(r, it["mu"], it["sigma"], PRE_UNITS)
        if temp == "Room":     # 이상 건은 Room 에만 — Pre 부터 튀어야 하는 유형이 있다
            for case in CASES:
                pre_z = TUNE[case["kind"]][0]
                it = next(x for x in ITEMS if x["name"] == case["item"])
                vals[it["name"]][post_idx[case["serial"] - 1]] = it["mu"] + pre_z * it["sigma"]
        return vals

    def post_values(temp, readout, pre):
        frac = {"168hrs": 1 / 3.0, "500hrs": 2 / 3.0, "1000hrs": 1.0}[readout]
        r = np.random.default_rng(SEED + (abs(hash((temp, readout))) % 10 ** 6))
        vals = {}
        for it in COLUMNS:
            if it["name"] == "DEVICE_ID":
                continue
            base = np.array([pre[it["name"]][post_idx[s - 1]] for s in range(1, POST_UNITS + 1)])
            if it in EXCLUDED_ITEMS:
                vals[it["name"]] = base
                continue
            # 회차마다 난수를 새로 뽑으면 (a) 표본 sigma 가 흔들려 회차 순서가 역전되고
            # (b) 유닛별 T1->T2->T3 추세가 지그재그가 된다. 온도x항목마다 표준정규 벡터를
            # 한 번만 뽑아 두고 회차에서는 크기만 키운다 — 산포 변화가 정확히 단조가 되고
            # 유닛별 추세도 매끄럽게 이어진다.
            unit = unit_noise(it["name"], temp)
            drift = it["drift_mu"] + it["drift_sigma"] * unit["drift"]
            moved = base * (1.0 + drift * frac)
            scale = sigma_scale(it["name"], temp, frac)
            if scale > 1.0:
                extra = it["sigma"] * math.sqrt(max(scale * scale - 1.0, 0.0))
                moved = moved + extra * unit["extra"]
            elif scale < 1.0:
                moved = it["mu"] + (moved - it["mu"]) * scale
            # (1) 꼬리 절단 — 산포가 커지면 우발적 SELECT(임계 약 3.99)나 스펙 이탈이 생긴다.
            # (2) 표본 표준편차를 설계값(sigma x scale)에 정확히 맞춘다. drift 도 산포에
            #     기여하는데 그 크기가 항목마다 달라, 맞춰주지 않으면 온도 순서가
            #     항목의 3분의 1쯤에서 뒤집힌다. 마지막 보정은 전 유닛 공통 배율이라
            #     "누가 튀는가 / 누가 유독 움직였나" 구조는 그대로 남는다.
            std0 = float(np.std(moved)) or (it["sigma"] * scale)
            lim = TRUNCATE_Z_POST * std0
            moved = np.clip(moved, it["mu"] - lim, it["mu"] + lim)
            std1 = float(np.std(moved)) or std0
            vals[it["name"]] = it["mu"] + (moved - it["mu"]) * (it["sigma"] * scale / std1)
        if temp == "Room":
            for case in CASES:
                it = next(x for x in ITEMS if x["name"] == case["item"])
                idx = case["serial"] - 1
                if readout != JUDGED:
                    # 앞 회차는 평범한 유닛과 같은 이동만 준다 (난수 없음 — 정답표 안정)
                    vals[it["name"]][idx] = pre[it["name"]][post_idx[idx]] * (1.0 + it["drift_mu"] * frac)
                    continue
                size = SIZE_BASED.get(case["kind"])
                if size is not None:
                    width = (it["ul"] - it["ll"])
                    vals[it["name"]][idx] = it["mu"] + size * width
                    continue
                ratio = SPEC_BASED.get(case["kind"])
                if ratio is not None:
                    # 스펙 기준: 상한을 ratio 만큼 넘긴 값
                    vals[it["name"]][idx] = it["ul"] * (1.0 + ratio)
                else:
                    # Grubbs 기준: 그 조합의 sigma 로 z 를 보존한다
                    sig = it["sigma"] * sigma_scale(it["name"], temp, frac)
                    vals[it["name"]][idx] = it["mu"] + TUNE[case["kind"]][1] * sig
        return vals

    def row_for(serial, vals, override=None, bin_value=None):
        values = {it["name"]: (post_dev[serial] if it["name"] == "DEVICE_ID"
                               else vals[it["name"]][serial - 1]) for it in COLUMNS}
        if override:
            values.update(override)
        return {"serial": serial, "bin": bin_value if bin_value is not None else 1, "values": values}

    written = []
    for temp, code in TEMPS:
        pre = pre_values(temp)
        title = "%s_%s_AAA_K001_%s_PRE" % (DEVICE, code, temp.upper())
        rows = []
        for i in range(PRE_UNITS):
            values = {it["name"]: (device_ids[i] if it["name"] == "DEVICE_ID" else pre[it["name"]][i])
                      for it in COLUMNS}
            rows.append({"serial": pre_serials[i], "bin": 1, "values": values})
        for i in range(DUP_PRE_COUNT):        # DEVICE_ID 중복 (마지막 등장 채택)
            rows.append(dict(rows[i * 37]))
        for row in rows:                      # Pre 의 Serial # 은 6자리 체계 (§3-3)
            row["serial"] = int(row["serial"]) if str(row["serial"]).isdigit() else row["serial"]
        written.append(write_csv(os.path.join(root, "00_Pre", title + ".csv"), title, COLUMNS, rows))

        for readout in READOUTS:
            vals = post_values(temp, readout, pre)
            title = "%s_%s_AAA_K001_%s_HTOL_%s" % (DEVICE, code, temp.upper(), readout)
            rows = []
            for serial in range(1, POST_UNITS + 1):
                case = CASE_BY_SERIAL.get(serial) if (temp == "Room" and readout == JUDGED) else None
                if case is None:
                    rows.append(row_for(serial, vals))
                    continue
                kind, target = case["kind"], case["item"]
                it = next(x for x in ITEMS if x["name"] == target)
                clean = next(x for x in ITEMS if x["name"] == CLEAN_ITEMS[0])
                if kind == "Unstable":
                    # 1회차 fail -> 2회차 그 항목만 pass(다른 항목이 fail) -> 마지막 fail
                    rows.append(row_for(serial, vals, bin_value=5))
                    rows.append(row_for(serial, vals, bin_value=5, override={
                        target: it["mu"], clean["name"]: clean["mu"] + 9 * clean["sigma"]}))
                    rows.append(row_for(serial, vals, bin_value=5))
                elif kind == "Intermittent":
                    # 1회차 fail -> 마지막 회차 Bin 1 로 회복(전 항목 스펙 안).
                    # 회복값을 mu 로 두면 "이동량 0" 이 되어 집단(전부 drift_mu 만큼 이동)
                    # 대비 Diff_S 가 튀어 Abnormal Pass 로도 걸린다. 평범한 유닛과 같은
                    # 이동을 준다 — 회복했다는 사실 말고는 아무것도 특이하지 않게.
                    typical = pre[target][post_idx[serial - 1]] * (1.0 + it["drift_mu"])
                    rows.append(row_for(serial, vals, bin_value=5))
                    rows.append(row_for(serial, vals, bin_value=5))
                    rows.append(row_for(serial, vals, bin_value=1, override={target: typical}))
                elif kind in FAIL_KINDS:
                    rows.append(row_for(serial, vals, bin_value=5))
                else:
                    rows.append(row_for(serial, vals))          # Abnormal Pass 는 Bin 1
            written.append(write_csv(os.path.join(root, "01_Post", title + ".csv"), title, COLUMNS, rows))
    return written


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Known Data")
    target = os.path.join(root, DEVICE, FOLDER)
    files = build(target)
    print("생성 %d개" % len(files))
    for path in files:
        print("  %8.1f KB  %s" % (os.path.getsize(path) / 1024, os.path.relpath(path, root)))


if __name__ == "__main__":
    main()
