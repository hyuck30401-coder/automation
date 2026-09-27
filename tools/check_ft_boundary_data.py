# -*- coding: utf-8 -*-
"""KNOWN03(현재 판정 기준 경계 사다리)을 툴에 돌려 기대 판정과 대조한다.

    python tools/check_ft_boundary_data.py ["Known Data" 경로]
"""
import os
import sys

sys.path.insert(0, os.path.abspath("_automation"))
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("tools"))

import headless                                   # noqa: F401
import cdf_compare_web as web
import make_ft_boundary_data as gen
from _regression_lib import analyze_condition
from calibrate_ft_boundary import COMBO, measure


def expected(it):
    """이 항목에 기대하는 결과. (분류, 게이트) — 게이트는 tau 계열에만 쓴다."""
    role, tgt = it["role"], it["target"]
    if role == "Excessive":
        return ("Excessive" if tgt >= 1.0 else "Slight", None)
    if role == "Slight":
        return ("Slight" if tgt > 1.0 else "Tail", None)
    if role == "Unstable":
        return ("Unstable" if tgt < 1.0 else "Tail", None)
    if role == "Intermittent":
        return ("Intermittent" if tgt < 1.0 else "Tail", None)
    if role == "Measured":
        return ("Measured" if tgt > 1.0 else "", None)
    if role == "Delta":
        return ("Delta" if tgt > 1.0 else "", None)
    if role == "Measured + Delta":
        a, b = tgt
        if a > 1 and b > 1:
            return ("Measured + Delta", None)
        if a > 1:
            return ("Measured", None)
        if b > 1:
            return ("Delta", None)
        return ("", None)
    if role == "TauMea":
        return ("Measured", "kept" if tgt > 1.0 else "folded")
    if role == "TauDelta":
        return ("Delta", "kept" if tgt > 1.0 else "folded")
    return ("", None)


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "Known Data")
    web.DATA_ROOT = root
    meas = measure(root)

    # 게이트(스펙 대비 기준)에서 접히는 항목
    app_p, pp = analyze_condition(web, dict(COMBO, mode="pass"), "pass")
    pp = web.payload_with_items(app_p, pp, "pass", "none")
    sg = (pp.get("shift_gate") or {}).get("items") or {}
    folded = set()
    for row in pp.get("selected_summary") or []:
        key = row.get("item_key") or row["item"]
        if sg.get(key, {}).get("folded"):
            folded.add(row["item"])
    selected = {row["item"] for row in (pp.get("selected_summary") or [])}

    print("=== KNOWN03 · 현재 판정 기준 경계 사다리 ===")
    print("%-14s %-8s %7s %8s  %-16s %-16s %s" %
          ("항목", "유형", "목표비", "실측비", "기대", "실제", "게이트"))
    print("-" * 104)
    ok = bad = 0
    for it in gen.ITEMS:
        if not it["role"]:
            continue
        want, want_gate = expected(it)
        m = meas.get(it["name"]) or {}
        role = it["role"]
        if role in ("Excessive", "Slight", "Unstable", "Intermittent"):
            got = m.get("fail_type") or "(없음)"
            ratio = {"Excessive": m.get("mea_r"), "Slight": m.get("diff_r")}.get(role)
        elif role in ("Measured", "Measured + Delta"):
            got = (m.get("reason") or "") if m.get("result") == "SELECT" else ""
            ratio = m.get("mea_r")
        elif role == "Delta":
            got = (m.get("reason") or "") if m.get("result") == "SELECT" else ""
            ratio = m.get("diff_r")
        else:                                        # TauMea / TauDelta
            got = (m.get("reason") or "") if m.get("result") == "SELECT" else ""
            ratio = m.get("size_r")
        gate = ""
        if want_gate:
            gate_got = "folded" if it["name"] in folded else ("kept" if it["name"] in selected else "-")
            gate = "%s (기대 %s)" % (gate_got, want_gate)
            good = (got == want) and (gate_got == want_gate)
        else:
            good = (got == want) or (want == "Tail" and got in ("Tail", "Slight"))
        ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
        tgt = it["target"]
        print("%s %-14s %-8s %7s %8s  %-16s %-16s %s" % (
            "OK " if good else "**X**", it["name"], role[:8],
            ("%.2f/%.2f" % tgt) if isinstance(tgt, tuple) else "%.2f" % tgt,
            ("%.3f" % ratio) if ratio else "-",
            want or "(없음)", got or "(없음)", gate))
    print("-" * 104)
    print("→ 일치 %d / 불일치 %d\n" % (ok, bad))

    print("=== 부가 검증 — 판정은 Room / %s 에만 ===" % gen.JUDGED)
    # Mea 축 경계(M / P / MD)는 Pre 부터 집단에서 튀도록 설계했다 — 스트레스 전부터
    # 통계적 이상치라 앞 회차에서도 Abnormal Pass 로 잡히는 게 정답이다 (KNOWN01 과 동일).
    early_ok = {it["name"] for it in gen.ITEMS
                if it["role"] in ("Measured", "TauMea", "Measured + Delta", "Slight")}
    for temp in ("Room", "Hot", "Cold"):
        for ro in gen.READOUTS:
            if temp == "Room" and ro == gen.JUDGED:
                continue
            _a, p2 = analyze_condition(web, dict(COMBO, ft_temp=temp, readout=ro, mode="fail"), "fail")
            _b, p3 = analyze_condition(web, dict(COMBO, ft_temp=temp, readout=ro), "pass")
            nf = (p2.get("sample_counts") or {}).get("fail")
            names = {r["item"] for r in (p3.get("selected_summary") or [])}
            extra = names - early_ok
            good = (nf == 0 and not extra)
            print("  %s %-5s %-8s fail 유닛 %s · Abnormal Pass %d건%s"
                  % ("OK " if good else "**X**", temp, ro, nf, len(names),
                     "" if not extra else "  기대 밖: %s" % sorted(extra)))


if __name__ == "__main__":
    main()
