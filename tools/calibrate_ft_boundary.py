# -*- coding: utf-8 -*-
"""KNOWN03 의 경계 knob 을 툴 실측으로 수렴시킨다.

Grubbs 임계(Mea/Diff)와 스펙 대비 크기는 그 항목 pass 표본에 의존하고, 심은 유닛
자신도 그 표본에 들어간다. 그래서 "z 를 3.92 x R 로 넣으면 비율이 R 이 된다"가
성립하지 않는다 — 넣고, 툴을 돌려 실제 비율을 읽고, 다시 조정하는 수밖에 없다.

한 번 수렴시킨 값은 tools/known03_calib.json 에 남고, 생성기가 그걸 읽으므로
이후에는 재생성만으로 같은 파일이 나온다.

    python tools/calibrate_ft_boundary.py [반복횟수] ["Known Data" 경로]
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.abspath("_automation"))
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("tools"))

import headless                                   # noqa: F401  (tkinter 스텁)
import cdf_compare_web as web
import make_ft_boundary_data as gen
from _regression_lib import analyze_condition

COMBO = {"device": gen.DEVICE, "ver": "KV1-0", "lot": "K003", "purpose": "K01",
         "folder": gen.FOLDER, "item": "HTOL", "readout": gen.JUDGED, "ft_temp": "Room"}
TOL = 0.004          # 목표비 대비 허용 오차
DAMP = 1.0           # 실측이 knob 에 거의 선형으로 반응해 감쇠 없이도 안정적이다


def measure(root):
    """항목별 (Mea_S/임계, Diff_S/임계, 스펙대비크기/tau) 실측치."""
    web.DATA_ROOT = os.path.abspath(root)
    web.clear_analysis_cache() if hasattr(web, "clear_analysis_cache") else None
    out = {}

    app_f, pf = analyze_condition(web, dict(COMBO, mode="fail"), "fail")
    for name, ip in (pf.get("items") or {}).items():
        case = gen.CASE_BY_ITEM.get(name)
        if not case:
            continue
        for d in ip.get("details") or []:
            if str(d.get("sample")) != str(case["serial"]):
                continue
            mt, dt = ip.get("mea_threshold"), ip.get("diff_threshold")
            out.setdefault(name, {}).update({
                "fail_type": d.get("fail_type"),
                "mea_r": abs(d["mea_s"]) / mt if (d.get("mea_s") is not None and mt) else None,
                "diff_r": abs(d["diff_s"]) / dt if (d.get("diff_s") is not None and dt) else None,
            })

    app_p, pp = analyze_condition(web, dict(COMBO, mode="pass"), "pass")
    pp = web.payload_with_items(app_p, pp, "pass", "none")
    rows = {(r.get("item_key") or r["item"]): r for r in (pp.get("results") or [])}
    # reason 은 detail 이 아니라 selected_summary 행에 붙는다.
    reasons = {r["item"]: r.get("reason") for r in (pp.get("selected_summary") or [])}
    for key, row in rows.items():
        name = row.get("item")
        case = gen.CASE_BY_ITEM.get(name)
        if not case:
            continue
        # payload["items"] 는 SELECT 된 항목만 채워진다. 임계 **아래** 항목도 재야
        # 캘리브레이션이 되므로 항목 payload 를 직접 만든다.
        ip = (pp.get("items") or {}).get(key) or web.item_to_json(app_p, name)
        mt, dt = ip.get("mea_threshold"), ip.get("diff_threshold")
        for d in (ip.get("details") or []) + (ip.get("normal_details") or []):
            if str(d.get("sample")) != str(case["serial"]):
                continue
            rec = out.setdefault(name, {})
            if d.get("mea_s") is not None and mt:
                rec["mea_r"] = abs(d["mea_s"]) / mt
            if d.get("diff_s") is not None and dt:
                rec["diff_r"] = abs(d["diff_s"]) / dt
            rec["result"] = d.get("result")
            rec["reason"] = reasons.get(name)
            size = web.spec_relative_size(d, row, ip.get("lower_limit"), ip.get("upper_limit"))
            rec["size_r"] = (size / web.SPEC_GATE_TAU) if size is not None else None
    return out


# 항목별 직전 (knob, 실측비) — 할선법(secant)에 쓴다.
HIST = {}


def _secant(name, axis, knob, got, want, lo, hi):
    """knob 을 한 번 갱신한다.

    처음에는 "실측비가 목표비에 비례한다"는 가정으로 한 걸음 가고, 두 번째부터는
    직전 점과의 할선으로 근을 찾는다. 비례 가정이 안 맞는 축이 있어서 그렇다 —
    예를 들어 Delta 축은 심은 유닛 자신이 diff_sigma 를 키워서 Diff_S 가 포화하고,
    Slight 축은 knob(pre 위치)과 Diff_S 가 반비례한다. 고정 감쇠로는 어떤 축은
    너무 느리고 어떤 축은 발산했다.
    """
    key = (name, axis)
    prev = HIST.get(key)
    HIST[key] = (knob, got)
    if prev and abs(got - prev[1]) > 1e-9 and abs(knob - prev[0]) > 1e-12:
        new = knob + (want - got) * (knob - prev[0]) / (got - prev[1])
    else:
        new = knob * (1 + 0.6 * (want / got - 1)) if got else knob
    # 한 걸음에 너무 멀리 가지 않게 묶는다 (발산 방지)
    span = max(abs(knob) * 0.35, 1e-9)
    new = max(knob - span, min(knob + span, new))
    return max(lo, min(hi, new))


def step(meas):
    """실측 비율을 보고 knob 을 조정한다. 조정한 항목 수와 최대 오차를 돌려준다."""
    changed, worst = 0, 0.0
    for it in gen.ITEMS:
        role, name, tgt = it["role"], it["name"], it["target"]
        if not role or name not in gen.TUNE:
            continue
        m = meas.get(name) or {}
        knob = gen.TUNE[name]

        if role == "Measured + Delta":
            gm, gd = m.get("mea_r"), m.get("diff_r")
            if not gm or not gd:
                continue
            err = max(abs(gm - tgt[0]), abs(gd - tgt[1]))
            worst = max(worst, err)
            if err <= TOL:
                continue
            a = _secant(name, "mea", knob[0], gm, tgt[0], 0.5, 20.0)
            b = _secant(name, "dif", knob[1], gd, tgt[1], 0.05, 12.0)
            gen.TUNE[name] = [a, b]
            changed += 1
            continue

        kind = {"Slight": "diff_r", "Measured": "mea_r", "Delta": "diff_r",
                "TauMea": "size_r", "TauDelta": "size_r"}.get(role)
        if kind is None:
            continue                       # 해석적으로 정해지는 유형 (Excessive/U/N)
        got = m.get(kind)
        if not got:
            continue
        err = abs(got - tgt)
        worst = max(worst, err)
        if err <= TOL:
            continue
        if role == "Slight":
            post_z = (it["ul"] * 1.003 - it["mu"]) / it["sigma"]
            new = _secant(name, "pre", knob, got, tgt, 0.0, post_z - 0.3)
        else:
            new = _secant(name, "z", knob, got, tgt, 0.05, 60.0)
        gen.TUNE[name] = float(new)
        changed += 1
    return changed, worst


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    root = sys.argv[2] if len(sys.argv) > 2 else "Known Data"
    target = os.path.join(root, gen.DEVICE, gen.FOLDER)
    for i in range(rounds):
        gen.build(target)
        meas = measure(root)
        changed, worst = step(meas)
        print("round %d — 조정 %2d 항목 · 최대 오차 %.4f" % (i + 1, changed, worst), flush=True)
        if not changed:
            break
    gen.build(target)
    with io.open(os.path.join("tools", "known03_calib.json"), "w", encoding="utf-8") as fh:
        json.dump(gen.TUNE, fh, ensure_ascii=False, indent=1)
    print("known03_calib.json 저장")


if __name__ == "__main__":
    main()
