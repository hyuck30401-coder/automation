# -*- coding: utf-8 -*-
"""제안 Tail 로직의 파라미터(W, N_min)를 실데이터에 스윕한다.

현재 툴 판정(fail_type)과 제안 로직 판정을 같은 조건·같은 항목에서 나란히 놓고,
  - 파라미터별로 Tail(= Marginal 후보)이 몇 건이 되는지
  - 현재 Marginal(fail_type == Tail)과 얼마나 겹치는지
를 센다. 제안 로직은 항목 단위 판정이라, 그 항목의 Spec Out 유닛은 모두 같은 판정을
받는다 — 유닛 수 비교는 그 규칙으로 환산한다.

    python tools/sweep_tail_params.py ["Test Data" 경로]
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath("_automation"))
sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("tools"))

import headless                                   # noqa: F401
import cdf_compare_web as web
from _regression_lib import analyze_condition, iter_selections
from check_tail_data import classify, robust      # 제안 로직 구현체

W_GRID = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
N_GRID = [1, 2, 3, 5]


def collect(root):
    """조건 x 항목마다 (현재 fail_type 집합, 값 배열, 한계) 를 모은다."""
    web.DATA_ROOT = os.path.abspath(root)
    rows = []
    for sel in iter_selections(web):
        try:
            app, pf = analyze_condition(web, dict(sel, mode="fail"), "fail")
        except Exception as exc:                    # 조건에 따라 Pre 가 없을 수 있다
            print("  (건너뜀) %s %s %s — %s" % (sel["item"], sel["readout"], sel["ft_temp"], exc))
            continue
        label = "%s/%s/%s/%s" % (sel["folder"][:12], sel["item"], sel["readout"], sel["ft_temp"])
        for name, ip in (pf.get("items") or {}).items():
            det = [d for d in (ip.get("details") or []) if d.get("fail_type")]
            if not det:
                continue
            # 제안 로직의 Core 는 "그 항목의 전 유닛" 이다. payload 는 이걸 한 곳에
            # 안 주므로 두 조각을 합친다 —
            #   pass_post_values : 유닛 단위 pass 의 이 항목 값
            #   details          : fail 유닛의 이 항목 값 (규격 이탈 행)
            # app.post_records 는 fail 모드에서 비어 있고, pass 모드 것은 pass 유닛만
            # 담고 있어서 둘 다 단독으로는 모집단이 되지 않는다.
            vals = [float(x) for x in (ip.get("pass_post_values") or []) if x is not None]
            vals += [float(d["post_value"]) for d in (ip.get("details") or [])
                     if d.get("post_value") is not None]
            v = np.array(vals)
            ll, ul = ip.get("lower_limit"), ip.get("upper_limit")
            if v.size == 0 or ll is None or ul is None:
                continue
            rows.append({
                "cond": label, "item": name, "v": v, "ll": float(ll), "ul": float(ul),
                "types": [d["fail_type"] for d in det],
                "samples": [str(d["sample"]) for d in det],
            })
        print("  %-46s 항목 %3d · fail 상세 %3d"
              % (label, len(pf.get("items") or {}), sum(len(r["types"]) for r in rows if r["cond"] == label)),
              flush=True)
    return rows


CACHE = "tools/.sweep_cache.pkl"


def load_rows(root):
    """수집은 조건 18개 x 분석이라 몇 분 걸린다 — 한 번 모으면 캐시해 둔다."""
    import pickle
    if os.path.exists(CACHE):
        with open(CACHE, "rb") as fh:
            return pickle.load(fh)
    rows = collect(root)
    with open(CACHE, "wb") as fh:
        pickle.dump(rows, fh)
    return rows


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "Test Data"
    print("=== 수집 ===")
    rows = load_rows(root)
    n_items = len(rows)
    n_units = sum(len(r["types"]) for r in rows)
    print("\nfail 이 있는 (조건 x 항목) %d개 · fail 상세 %d건" % (n_items, n_units))

    cur = {}
    for r in rows:
        for t in r["types"]:
            cur[t] = cur.get(t, 0) + 1
    print("현재 fail_type 분포:", dict(sorted(cur.items(), key=lambda x: -x[1])))
    cur_marginal = cur.get("Tail", 0)
    print("현재 Marginal(= Tail) = %d건 / %d건 (%.1f%%)\n"
          % (cur_marginal, n_units, cur_marginal / n_units * 100))

    # 제안 로직은 Intermittent/Unstable 을 대체하지 않는다 — 이력 기반이라 그대로 둔다.
    # 비교 대상은 Excessive / Slight / Tail 로 분류된 상세뿐이다.
    TARGET = ("Excessive", "Slight", "Tail")
    print("=== W / N_min 스윕 ===")
    print("제안 Tail 로 분류된 상세 건수 (괄호 안은 현재 Tail 과 겹치는 건수)")
    print("        " + "".join("%-18s" % ("N_min=%d" % n) for n in N_GRID))
    best = []
    for w in W_GRID:
        line = "W=%.2f " % w
        for n in N_GRID:
            tail_units = same = 0
            for r in rows:
                got, _info = classify(r["v"], r["ll"], r["ul"], w_k=w, n_min=n)
                is_tail = got.split("/")[0] == "Tail" and "Separated" not in got and "Shift" not in got
                for t in r["types"]:
                    if t not in TARGET:
                        continue
                    if is_tail:
                        tail_units += 1
                        if t == "Tail":
                            same += 1
            line += "%-18s" % ("%3d (%3d)" % (tail_units, same))
            best.append((w, n, tail_units, same))
        print(line)

    print("\n=== 현재 판정 x 제안 판정 교차표 (W=기준값들) ===")
    for w, n in ((0.5, 1), (1.0, 1), (1.5, 1), (2.0, 1), (1.5, 2)):
        tab = {}
        for r in rows:
            got, _ = classify(r["v"], r["ll"], r["ul"], w_k=w, n_min=n)
            g = got.split("/")[0] if "Separated" not in got and "Shift" not in got else \
                ("Shift" if "Shift" in got else "Separated")
            for t in r["types"]:
                if t in TARGET:
                    tab[(t, g)] = tab.get((t, g), 0) + 1
        print("\n  W=%.2f · N_min=%d" % (w, n))
        gs = sorted({k[1] for k in tab})
        print("    %-12s %s" % ("현재\\제안", "".join("%-12s" % g for g in gs)))
        for t in TARGET:
            print("    %-12s %s" % (t, "".join("%-12d" % tab.get((t, g), 0) for g in gs)))


def detail(rows, w=1.0, n=1):
    """권장 파라미터에서 무엇이 어떻게 바뀌는지 구체적으로 본다."""
    from collections import Counter
    shift_items, sep_gap, tail_gap, exc_tail = Counter(), [], [], []
    per_cond = {}
    for r in rows:
        got, info = classify(r["v"], r["ll"], r["ul"], w_k=w, n_min=n)
        g = "Shift" if "Shift" in got else ("Separated" if "Separated" in got else "Tail")
        cnt = per_cond.setdefault(r["cond"], Counter())
        for t in r["types"]:
            cnt[t + "->" + g] += 1
            if t == "Tail" and g == "Shift":
                shift_items[r["item"]] += 1
            gap = info.get("gap_hi", info.get("gap_lo"))
            lim = info.get("limit")
            if gap is not None and lim:
                (sep_gap if g == "Separated" else tail_gap).append(gap / lim)
            if t == "Excessive" and g == "Tail":
                exc_tail.append((r["cond"], r["item"], gap / lim if (gap and lim) else None))
    print("\n=== W=%.2f · N_min=%d 상세 ===" % (w, n))
    print("현재 Tail -> 제안 Shift 가 몰린 항목 top 12:")
    for name, c in shift_items.most_common(12):
        print("   %-32s %3d건" % (name[:32], c))
    import statistics as st
    if sep_gap:
        print("\nGap/한계 분포 — Separated %d건: 중앙 %.2f · 하위10%% %.2f · 상위10%% %.2f"
              % (len(sep_gap), st.median(sep_gap),
                 sorted(sep_gap)[len(sep_gap)//10], sorted(sep_gap)[-max(1,len(sep_gap)//10)]))
    if tail_gap:
        print("Gap/한계 분포 — Tail %d건: 중앙 %.2f · 최대 %.2f"
              % (len(tail_gap), st.median(tail_gap), max(tail_gap)))
    print("\n현재 Excessive 인데 제안 Tail (%d건) — 앞 10건:" % len(exc_tail))
    for c, i, g in exc_tail[:10]:
        print("   %-40s %-28s Gap/한계 %.2f" % (c[:40], i[:28], g or 0))
    print("\n조건별 (현재->제안) 상위:")
    for cond, c in sorted(per_cond.items()):
        tot = sum(c.values())
        cur_t = sum(v for k, v in c.items() if k.startswith("Tail->"))
        new_t = sum(v for k, v in c.items() if k.endswith("->Tail"))
        print("   %-44s fail %4d · Marginal %3d -> %3d" % (cond[:44], tot, cur_t, new_t))


if __name__ != "__main__":
    pass


if __name__ == "__main__":
    main()
    import pickle
    with open(CACHE, "rb") as fh:
        detail(pickle.load(fh), 1.0, 1)
