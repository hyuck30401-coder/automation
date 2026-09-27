# -*- coding: utf-8 -*-
"""현재 툴 판정 기준의 **경계 사다리** 데이터셋 (KNOWN03).

KNOWN01 은 유형마다 "확실히 그 유형인" 건 3개씩과 경계 1쌍씩을 넣어 판정이 맞는지를
본다. 이 데이터셋은 목적이 다르다 — **각 선별 기준의 임계 주변에 여러 단계를 깔아**
"경계에 있는 건이 그래프에서 어느 정도로 보이는지"를 눈으로 확인하려는 것이다.

각 기준마다 임계의 0.90 / 0.96 / 0.99 / 1.01 / 1.04 / 1.10 배 지점에 유닛을 하나씩
심는다. 1 을 넘으면 그 유형으로 잡히고, 밑이면 안 잡힌다.

  Fail 유형
    X  Excessive / (Slight·Tail)   spec_margin_ratio = |값-한계|/|한계| 의 1% 임계
    S  Slight / Tail               Diff_S 의 Grubbs 임계 (Mea_S 는 확실히 초과)
    U  Unstable                    중간 회차에 그 항목이 스펙 안으로 들어오는가 (경계 +-0.1%)
    N  Intermittent                마지막 회차에 유닛이 Bin pass 로 회복하는가 (경계 +-0.1%)
  Abnormal Pass 유형
    M  Measured                    Mea_S 의 Grubbs 임계
    T  Delta                       Diff_S 의 Grubbs 임계
    MD Measured + Delta            두 축 임계의 네 모서리
  게이트
    P  스펙 대비 기준 (Mea 축)     |값-평균|/스펙폭 의 tau(5%) 임계
    Q  스펙 대비 기준 (Delta 축)   |Post-Pre|/스펙폭 의 tau(5%) 임계

Grubbs 임계는 표본(그 항목의 pass 유닛)에 의존해서 "값을 넣으면 그 비율이 나온다"가
성립하지 않는다. tools/calibrate_ft_boundary.py 가 툴을 헤드리스로 돌려 실제
Mea_S / Diff_S / 스펙 대비 크기를 읽고 목표비에 수렴시킨 뒤 known03_calib.json 에
knob 값을 남긴다. 그 파일이 있으면 TUNE 을 덮는다.

레이아웃·폴더 규약은 KNOWN01/02 와 같다(§3-1, §3-2).
"""
import io
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_known_data import write_csv, _normal

SEED = 20260912
PRE_UNITS = 800
POST_UNITS = 231
TEMPS = [("Room", "ER01"), ("Hot", "EH01"), ("Cold", "EC01")]
READOUTS = ["168hrs", "500hrs", "1000hrs"]
JUDGED = "1000hrs"
DEVICE = "KNOWN03"
FOLDER = "00_KV1-0_K003_K01"

TAU = 0.05                      # 스펙 대비 게이트 임계 (SPEC_GATE_TAU)
EXC = 0.01                      # Excessive 임계 (spec_margin_ratio)
LEVELS = [0.90, 0.96, 0.99, 1.01, 1.04, 1.10]
LEVELS4 = [0.90, 0.99, 1.01, 1.10]
TRUNC = 3.0
TRUNC_POST = 3.2


def _decimals(mu):
    return max(4, 5 - int(math.floor(math.log10(abs(mu))))) if mu else 4


def item(name, unit, mu, rel_sigma, drift_mu, drift_sigma, spec_k, role, target, grp=""):
    sigma = abs(mu) * rel_sigma
    return {"name": name, "unit": unit, "mu": mu, "sigma": sigma, "grp": grp,
            "ll": mu - spec_k * sigma, "ul": mu + spec_k * sigma,
            "drift_mu": drift_mu, "drift_sigma": drift_sigma,
            "spec_k": spec_k, "role": role, "target": target,
            "dec": _decimals(mu)}


def tag(r):
    return "%03d" % round(r * 100)


# ── 항목 = 시나리오 하나 ──────────────────────────────────────────────────────
# 같은 항목에 이상치를 둘 이상 넣으면 Grubbs(단일 이상치 검정)에서 서로 가려진다.
ITEMS = []
BASE = {
    # (rel_sigma, drift_mu, drift_sigma, spec_k)
    "X": (0.005, -0.0010, 0.00025, 6.0),    # 값도 이동도 크게 -> Mea·Diff 둘 다 초과
    "S": (0.005, -0.0010, 0.00150, 6.0),    # Diff 축을 pre 위치로 조절할 수 있게 넓게
    "U": (0.005, -0.0008, 0.00030, 6.0),
    "N": (0.005, -0.0008, 0.00030, 6.0),
    "M": (0.005, -0.0008, 0.00030, 12.0),   # 값만 튀고 이동은 평범
    "T": (0.010, 0.0010, 0.00050, 6.0),     # 값 산포는 넓고 이동 산포는 좁게
    "D": (0.005, 0.0010, 0.00025, 12.0),    # MD 코너용
    "P": (0.005, -0.0008, 0.00030, 60.0),   # Cp 과잉 -> Mea 축이 스펙 대비로는 미미
    "Q": (0.010, 0.0010, 0.00050, 30.0),    # Delta 축 tau 경계
    "Z": (0.005, -0.0008, 0.00030, 6.0),
}
# 한 그룹 안의 여러 단계는 **같은 항목 특성(mu·sigma·drift)** 을 쓴다. 그래야 단계
# 사이의 물리량(이탈률·이동률·편차)을 그대로 비교할 수 있다 — mu 가 다르면 "한 칸
# 차이가 몇 %인가" 가 항목마다 달라져 표가 의미를 잃는다.
GROUP_MU = {"X": 1.2, "S": 3.3, "U": 2.5, "N": 2.5, "M": 5.0, "T": 0.6,
            "D": 12.5, "P": 4.2, "Q": 35.0, "Z": 1.5}
GROUP_UNIT = {"X": "V", "S": "V", "U": "V", "N": "V", "M": "V", "T": "mA",
              "D": "mA", "P": "V", "Q": "uA", "Z": "V"}


def add(prefix, base_key, role, target):
    rel, dmu, dsig, k = BASE[base_key]
    ITEMS.append(item(prefix, GROUP_UNIT[base_key], GROUP_MU[base_key],
                      rel, dmu, dsig, k, role, target, base_key))


for r in LEVELS:
    add("X_EXC_" + tag(r), "X", "Excessive", r)
for r in LEVELS:
    add("S_SLT_" + tag(r), "S", "Slight", r)
add("U_UNS_IN", "U", "Unstable", 0.999)
add("U_UNS_OUT", "U", "Unstable", 1.001)
add("N_INT_IN", "N", "Intermittent", 0.999)
add("N_INT_OUT", "N", "Intermittent", 1.001)
for r in LEVELS:
    add("M_MEA_" + tag(r), "M", "Measured", r)
for r in LEVELS:
    add("T_DLT_" + tag(r), "T", "Delta", r)
for a, b in ((1.05, 1.05), (1.05, 0.95), (0.95, 1.05), (0.95, 0.95)):
    add("MD_%s_%s" % (tag(a), tag(b)), "D", "Measured + Delta", (a, b))
for r in LEVELS4:
    add("P_TAUM_" + tag(r), "P", "TauMea", r)
for r in LEVELS4:
    add("Q_TAUD_" + tag(r), "Q", "TauDelta", r)
add("Z_CLEAN1", "Z", "", 0)
add("Z_CLEAN2", "Z", "", 0)

CLEAN_ITEMS = [it["name"] for it in ITEMS if not it["role"]]

EXCLUDED_ITEMS = [
    {"name": "FT_FAIL_STEP", "unit": "FailStep", "mu": 0.0, "sigma": 0.0,
     "ll": None, "ul": None, "dec": 4},
    {"name": "FCLK_MHZ", "unit": "MHz", "mu": 24.0, "sigma": 0.12,
     "ll": 23.0, "ul": 25.0, "dec": 4},
]
DEVICE_ID_ITEM = {"name": "DEVICE_ID", "unit": "Binnary", "mu": 0.0, "sigma": 0.0,
                  "ll": None, "ul": None, "dec": 0}

# 시나리오마다 전용 Serial 하나. 190 부터 순서대로.
CASES = [{"serial": 190 + i, "item": it["name"], "role": it["role"], "target": it["target"]}
         for i, it in enumerate(ITEMS) if it["role"]]
CASE_BY_SERIAL = {c["serial"]: c for c in CASES}
CASE_BY_ITEM = {c["item"]: c for c in CASES}

# ── knob 초기값 ──────────────────────────────────────────────────────────────
# Grubbs 임계는 n=231 에서 약 3.92. 아래는 "목표비 x 3.92" 근처의 첫 추정이고,
# calibrate_ft_boundary.py 가 툴 실측으로 수렴시킨다.
G0 = 3.92


def initial_tune():
    tune = {}
    for it in ITEMS:
        role, tgt = it["role"], it["target"]
        if role == "Excessive":
            tune[it["name"]] = EXC * tgt                     # 스펙 이탈률 (해석적)
        elif role == "Slight":
            # pre 위치. 크게 잡을수록 이동량이 작아져 Diff_S 가 내려간다.
            tune[it["name"]] = 6.0 - 2.2 * tgt
        elif role in ("Unstable", "Intermittent"):
            tune[it["name"]] = tgt                           # 한계 대비 배수 (해석적)
        elif role == "Measured":
            tune[it["name"]] = G0 * tgt
        elif role == "Delta":
            tune[it["name"]] = 2.50 * tgt
        elif role == "Measured + Delta":
            tune[it["name"]] = [G0 * tgt[0], 2.0 * tgt[1]]   # [post_z, pre 하향폭]
        elif role == "TauMea":
            tune[it["name"]] = 2 * it["spec_k"] * TAU * tgt  # z = 120 x 0.05 x R
        elif role == "TauDelta":
            tune[it["name"]] = 2 * it["spec_k"] * TAU * tgt  # z = 60 x 0.05 x R
    return tune


TUNE = initial_tune()
_CALIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known03_calib.json")
if os.path.exists(_CALIB):
    with io.open(_CALIB, encoding="utf-8") as _fh:
        for _k, _v in json.load(_fh).items():
            if _k in TUNE:
                TUNE[_k] = _v

# ── 산포 변화 프로파일 ────────────────────────────────────────────────────────
def build_profile():
    rng = np.random.default_rng(SEED + 77)
    prof = {}
    for it in ITEMS + EXCLUDED_ITEMS:
        # 같은 그룹은 산포 프로파일도 공유한다. 안 그러면 성장률이 항목마다 달라
        # 변화율 산포가 20% 씩 벌어지고, 단계 사이 물리량 비교가 무의미해진다.
        key = it.get("grp") or it["name"]
        if key in prof:
            prof[it["name"]] = prof[key]
            continue
        diff_side = it.get("role") in ("Delta", "TauDelta", "TauMea", "Measured + Delta")
        lo, hi = (0.04, 0.09) if diff_side else (0.10, 0.30)
        prof[key] = prof[it["name"]] = {
            "growth": float(rng.uniform(lo, hi)),
            "temp": {"Room": 1.0,
                     "Hot": float(rng.uniform(1.06, 1.14) if diff_side else rng.uniform(1.06, 1.26)),
                     "Cold": float(rng.uniform(0.88, 0.95) if diff_side else rng.uniform(0.80, 0.94))},
        }
    return prof


PROFILE = build_profile()
FRAC = {"168hrs": 1 / 3.0, "500hrs": 2 / 3.0, "1000hrs": 1.0}


def scale_of(name, temp, readout):
    p = PROFILE.get(name)
    return 1.0 if not p else p["temp"].get(temp, 1.0) * (1.0 + p["growth"] * FRAC[readout])


_NOISE = {}
_GRP_OF = {it["name"]: it.get("grp") for it in ITEMS}


def unit_noise(name):
    """같은 그룹이면 같은 유닛 잡음 벡터를 쓴다 — 단계 사이 차이가 '심은 유닛' 하나만
    되도록. 그래야 0.99 와 1.01 을 나란히 놓고 비교할 수 있다."""
    grp = _GRP_OF.get(name)
    name = grp or name
    if name not in _NOISE:
        r = np.random.default_rng(SEED + 991 + (abs(hash(name)) % 10 ** 7))
        _NOISE[name] = {"drift": _normal(r, 0.0, 1.0, POST_UNITS),
                        "extra": _normal(r, 0.0, 1.0, POST_UNITS)}
    return _NOISE[name]


COLUMNS = ITEMS[:20] + [DEVICE_ID_ITEM] + ITEMS[20:] + EXCLUDED_ITEMS


def build(root):
    rng = np.random.default_rng(SEED)
    device_ids = ["%d" % (400000000 + i * 7 + 13) for i in range(PRE_UNITS)]
    pre_serials = [300041 + i * 8 for i in range(PRE_UNITS)]
    post_idx = rng.permutation(PRE_UNITS)[:POST_UNITS]
    post_dev = {s: device_ids[post_idx[s - 1]] for s in range(1, POST_UNITS + 1)}

    def pre_values(temp):
        r = np.random.default_rng(SEED + (abs(hash(temp)) % 10 ** 6))
        vals, seen = {}, {}
        for it in ITEMS + EXCLUDED_ITEMS:
            key = it.get("grp") or it["name"]
            if key not in seen:
                seen[key] = _normal(r, it["mu"], it["sigma"], PRE_UNITS)
            vals[it["name"]] = np.array(seen[key])
        if temp != "Room":
            return vals
        for case in CASES:
            it = next(x for x in ITEMS if x["name"] == case["item"])
            knob = TUNE[it["name"]]
            idx = post_idx[case["serial"] - 1]
            if case["role"] == "Slight":
                vals[it["name"]][idx] = it["mu"] + knob * it["sigma"]
            elif case["role"] == "Measured":
                vals[it["name"]][idx] = it["mu"] + knob * it["sigma"]
            elif case["role"] == "Measured + Delta":
                vals[it["name"]][idx] = it["mu"] + (knob[0] - knob[1]) * it["sigma"]
            elif case["role"] == "TauMea":
                vals[it["name"]][idx] = it["mu"] + knob * it["sigma"]
            elif case["role"] in ("Delta", "TauDelta"):
                # Pre 를 평균에 고정한다. 안 그러면 이동량이 "그 유닛의 Pre 가 어디였나"
                # 라는 난수에 지배당해서 knob 을 움직여도 Diff_S 가 따라오지 않는다
                # (캘리브레이션이 하한에 붙어 버린 원인이었다).
                vals[it["name"]][idx] = it["mu"]
        return vals

    def post_values(temp, readout, pre):
        frac = FRAC[readout]
        vals = {}
        for it in COLUMNS:
            if it["name"] == "DEVICE_ID":
                continue
            base = np.array([pre[it["name"]][post_idx[s - 1]] for s in range(1, POST_UNITS + 1)])
            if it in EXCLUDED_ITEMS:
                vals[it["name"]] = base
                continue
            n = unit_noise(it["name"])
            drift = it["drift_mu"] + it["drift_sigma"] * n["drift"]
            moved = base * (1.0 + drift * frac)
            scale = scale_of(it["name"], temp, readout)
            if scale > 1.0:
                moved = moved + it["sigma"] * math.sqrt(scale * scale - 1.0) * n["extra"]
            elif scale < 1.0:
                moved = it["mu"] + (moved - it["mu"]) * scale
            std0 = float(np.std(moved)) or (it["sigma"] * scale)
            lim = TRUNC_POST * std0
            moved = np.clip(moved, it["mu"] - lim, it["mu"] + lim)
            std1 = float(np.std(moved)) or std0
            vals[it["name"]] = it["mu"] + (moved - it["mu"]) * (it["sigma"] * scale / std1)
        if temp != "Room":
            return vals
        for case in CASES:
            it = next(x for x in ITEMS if x["name"] == case["item"])
            knob = TUNE[it["name"]]
            i = case["serial"] - 1
            role = case["role"]
            sig = it["sigma"] * scale_of(it["name"], temp, readout)
            if readout != JUDGED:
                # 앞 회차는 평범한 유닛과 같은 이동만 준다 (판정은 마지막 회차에서만)
                vals[it["name"]][i] = pre[it["name"]][post_idx[i]] * (1.0 + it["drift_mu"] * frac)
                continue
            if role == "Excessive":
                vals[it["name"]][i] = it["ul"] * (1.0 + knob)
            elif role == "Slight":
                vals[it["name"]][i] = it["ul"] * 1.003
            elif role in ("Unstable", "Intermittent"):
                vals[it["name"]][i] = it["ul"] * 1.006     # 1회차(FT) 는 항상 이탈
            elif role == "Measured":
                vals[it["name"]][i] = it["mu"] + knob * sig
            elif role == "Delta":
                vals[it["name"]][i] = it["mu"] + knob * sig
            elif role == "Measured + Delta":
                vals[it["name"]][i] = it["mu"] + knob[0] * sig
            elif role in ("TauMea", "TauDelta"):
                vals[it["name"]][i] = it["mu"] + knob * sig
        return vals

    def row_for(serial, vals, override=None, bin_value=1):
        values = {it["name"]: (post_dev[serial] if it["name"] == "DEVICE_ID"
                               else vals[it["name"]][serial - 1]) for it in COLUMNS}
        if override:
            values.update(override)
        return {"serial": serial, "bin": bin_value, "values": values}

    FAIL_ROLES = ("Excessive", "Slight", "Unstable", "Intermittent")
    written = []
    for temp, code in TEMPS:
        pre = pre_values(temp)
        title = "%s_%s_AAA_K003_%s_PRE" % (DEVICE, code, temp.upper())
        rows = []
        for i in range(PRE_UNITS):
            values = {it["name"]: (device_ids[i] if it["name"] == "DEVICE_ID"
                                   else pre[it["name"]][i]) for it in COLUMNS}
            rows.append({"serial": pre_serials[i], "bin": 1, "values": values})
        written.append(write_csv(os.path.join(root, "00_Pre", title + ".csv"), title, COLUMNS, rows))

        for readout in READOUTS:
            vals = post_values(temp, readout, pre)
            title = "%s_%s_AAA_K003_%s_HTOL_%s" % (DEVICE, code, temp.upper(), readout)
            rows = []
            for serial in range(1, POST_UNITS + 1):
                case = CASE_BY_SERIAL.get(serial) if temp == "Room" else None
                if case is None:
                    rows.append(row_for(serial, vals))
                    continue
                it = next(x for x in ITEMS if x["name"] == case["item"])
                clean = next(x for x in ITEMS if x["name"] == CLEAN_ITEMS[0])
                role = case["role"]
                if role in ("Unstable", "Intermittent"):
                    # 회차(파일)가 아니라 **같은 파일 안의 반복 행**이 재시험 단계다 (§3-4).
                    # 그래서 이 두 유형은 마지막 회차 파일에 행 3개로 만든다.
                    if readout != JUDGED:
                        rows.append(row_for(serial, vals))
                    elif role == "Unstable":
                        mid = {it["name"]: it["ul"] * TUNE[it["name"]]}
                        if TUNE[it["name"]] < 1.0:
                            # 그 항목은 스펙 안 -> 유닛이 계속 fail 이도록 다른 항목을 떨군다
                            mid[clean["name"]] = clean["ul"] * 1.02
                        rows.append(row_for(serial, vals, bin_value=5))
                        rows.append(row_for(serial, vals, bin_value=5, override=mid))
                        rows.append(row_for(serial, vals, bin_value=5))
                    else:   # Intermittent
                        last = {it["name"]: it["ul"] * TUNE[it["name"]]}
                        recovered = TUNE[it["name"]] < 1.0
                        rows.append(row_for(serial, vals, bin_value=5))
                        rows.append(row_for(serial, vals, bin_value=5))
                        rows.append(row_for(serial, vals, bin_value=1 if recovered else 5,
                                            override=last))
                elif role in FAIL_ROLES and readout == JUDGED:
                    rows.append(row_for(serial, vals, bin_value=5))
                else:
                    rows.append(row_for(serial, vals))
            written.append(write_csv(os.path.join(root, "01_Post", title + ".csv"),
                                     title, COLUMNS, rows))
    return written


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Known Data")
    files = build(os.path.join(root, DEVICE, FOLDER))
    print("생성 %d개 · 항목 %d · 경계 케이스 %d (Serial %d~%d)"
          % (len(files), len(ITEMS), len(CASES), CASES[0]["serial"], CASES[-1]["serial"]))


if __name__ == "__main__":
    main()
