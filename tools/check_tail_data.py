# -*- coding: utf-8 -*-
"""제안된 분포 형상 기반 Tail 판정 로직을 KNOWN02 데이터셋에 그대로 적용해 본다.

툴을 거치지 않고 데이터로그(Room / 1000hrs)만 읽는다 — 제안 로직은 POST 분포
하나만 쓰기 때문이다. 항목마다 기대 판정(정답)과 실제 판정을 대조하고,
마지막에 Near-Spec Zone 폭(W)과 최소 개수(N_min)를 스윕한 표를 찍는다.

사용:
    python tools/check_tail_data.py ["Known Data" 경로]
"""
import csv
import io
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_tail_data import (SCEN, DEVICE, FOLDER, JUDGED, TEMPS, READOUTS,
                            KZ, Z95, W_K, N_MIN, GAP_K, RES_K)

POST_FILE = "KNOWN02_ER01_AAA_K002_ROOM_HTOL_%s.csv" % JUDGED
MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "known02_manifest.json")


def manifest():
    """생성기가 남긴 항목별 정보 (옮긴 Serial, 한계, sigma_core).

    산포 검사에서 "생성기가 손댄 유닛"을 빼려면 이 정보가 필요한데, 그건 build()
    안에서만 정해진다. 검증기가 생성기를 다시 돌릴 수는 없으니 파일로 주고받는다.
    """
    if not os.path.exists(MANIFEST):
        return {}
    with io.open(MANIFEST, encoding="utf-8") as fh:
        return json.load(fh)


def read_condition(root, fname=POST_FILE):
    path = os.path.join(root, DEVICE, FOLDER, "01_Post", fname)
    rows = list(csv.reader(io.open(path, encoding="utf-8")))
    names, lls, uls = rows[46], rows[48], rows[49]
    out = {}
    for i, name in enumerate(names):
        if not name or name in ("Test Name",):
            continue
        vals = []
        for r in rows[52:]:
            txt = r[i] if i < len(r) else ""
            try:
                vals.append(float(txt))
            except ValueError:
                pass
        if not vals:
            continue
        try:
            ll = float(lls[i])
            ul = float(uls[i])
        except ValueError:
            continue
        out[name] = (np.array(vals), ll, ul)
    return out


def audit(root):
    """부가 검증 — 판정은 Room/1000hrs 에만 나야 하고(D 그룹 제외), 산포 변화 양상은
    회차 단조 증가 · Cold < Room < Hot 이어야 한다(배치 유닛은 빼고 본다)."""
    print("\n=== 부가 검증 ===")
    for temp, code in TEMPS:
        for ro in READOUTS:
            f = "KNOWN02_%s_AAA_K002_%s_HTOL_%s.csv" % (code, temp.upper(), ro)
            d = read_condition(root, f)
            other = 0
            for name, (v, ll, ul) in d.items():
                if name.startswith("TLD"):
                    continue        # D 그룹은 설계상 모든 조건에서 이탈한다
                other += int(((v > ul) | (v < ll)).sum())
            want = (temp == "Room" and ro == JUDGED)
            good = (other > 0) == want
            print("  %s %-5s %-8s D그룹 외 Spec Out %d건 %s"
                  % ("OK " if good else "**X**", temp, ro, other,
                     "(판정 조건)" if want else "(0 이 정답)"))

    def sd(fname, name, skip):
        path = os.path.join(root, DEVICE, FOLDER, "01_Post", fname)
        rows = list(csv.reader(io.open(path, encoding="utf-8")))
        i = rows[46].index(name)
        vals = [float(r[i]) for r in rows[52:] if r[1] not in skip and r[i]]
        return float(np.std(vals))

    man = manifest()
    bad_ro = bad_t = 0
    n_ro = 0
    for it in SCEN:
        skip = {str(x) for x in man.get(it["name"], {}).get("serials", [])}
        ro = [sd("KNOWN02_ER01_AAA_K002_ROOM_HTOL_%s.csv" % x, it["name"], skip)
              for x in READOUTS]
        hot = sd("KNOWN02_EH01_AAA_K002_HOT_HTOL_1000hrs.csv", it["name"], skip)
        cold = sd("KNOWN02_EC01_AAA_K002_COLD_HTOL_1000hrs.csv", it["name"], skip)
        # 격자가 sigma 보다 굵은 항목(E/F)은 회차별 산포 증가가 양자화에 묻혀
        # 순서가 뒤집힌다 — 실제 저분해능 항목도 마찬가지라 검사에서 뺀다.
        if it["mode"] != "grid":
            n_ro += 1
            bad_ro += 0 if ro[0] < ro[1] < ro[2] else 1
        bad_t += 0 if cold < ro[2] < hot else 1
    print("  %s 산포 회차 단조 증가 위반 %d / %d  (격자 항목 %d개는 제외 — 양자화에 묻힘)"
          % ("OK " if not bad_ro else "**X**", bad_ro, n_ro, len(SCEN) - n_ro))
    print("  %s 산포 온도 순서(Cold < Room < Hot) 위반 %d / %d"
          % ("OK " if not bad_t else "**X**", bad_t, len(SCEN)))
    continuity(root)


def continuity(root):
    """꼬리가 모집단에서 스펙 한계까지 끊기지 않고 이어지는가.

    1차 데이터는 Near-Spec 구간을 비우고 점을 심는 바람에, 판정 대상인 Gap 보다
    그 앞의 빈 구간이 더 컸다 — 그러면 로직이 Tail 이라고 해도 그림은 "떨어져 나온
    덩어리"다. 한계 아래 1.5 sigma_core 구간에서 인접 Pass 사이 최대 간격을 재서
    Gap_Limit 과 비교한다. 이 값이 1 근처면 자연 정규 꼬리의 상위 간격과 같은
    수준이라는 뜻이고, 훨씬 크면 꼬리가 끊긴 것이다.
    """
    data = read_condition(root)
    print("\n=== 꼬리 연속성 — 한계 아래 1.5 sigma 구간의 최대 인접 간격 / Gap_Limit ===")
    worst = []
    for it in SCEN:
        v, ll, ul = data[it["name"]]
        got, info = classify(v, ll, ul)
        if "limit" not in info or not info["limit"]:
            continue
        lo_side = "gap_lo" in info and "gap_hi" not in info
        u = np.sort((ll - v) if lo_side else (v - ul))
        keep = u[u <= 0]
        reg = keep[keep >= -1.5 * info["sc"]] if info["sc"] else keep
        if len(reg) < 2:
            continue
        pre = float(np.max(np.diff(reg)))
        worst.append((pre / info["limit"], it["name"], got))
    for r, name, got in sorted(worst, reverse=True):
        mark = "**X**" if r > 1.5 else "OK "
        print("  %s %-16s %5.2f  %s" % (mark, name, r, got))
    bad = [w for w in worst if w[0] > 1.5]
    print("  → 꼬리가 끊긴 항목 %d / %d  (0 이 정답)" % (len(bad), len(worst)))


def robust(v):
    med = float(np.median(v))
    return med, KZ * float(np.median(np.abs(v - med)))


def resolution(v):
    """측정 분해능 추정 — 서로 다른 값들 사이의 최소 간격."""
    u = np.unique(np.round(v, 12))
    if len(u) < 2:
        return 0.0
    return float(np.min(np.diff(u)))


def classify(v, ll, ul, w_k=W_K, n_min=N_MIN, gap_k=GAP_K, res_k=RES_K):
    """제안 로직 그대로. 상·하한을 따로 판정하고 결과를 합쳐 돌려준다."""
    hi = v[v > ul]
    lo = v[v < ll]
    info = {"n_oos_hi": len(hi), "n_oos_lo": len(lo)}
    if len(hi) == 0 and len(lo) == 0:
        return "Normal", info

    med, sc = robust(v)
    res = resolution(v)
    keep = v[(v >= ll) & (v <= ul)]
    if keep.size == 0:
        # 전량 이탈 — Core 자체가 스펙 밖이다. 꼬리를 따질 게 없다.
        info.update({"med": med, "sc": sc, "res": res})
        return "Shift", info
    lim = max(gap_k * sc, res_k * res)
    info.update({"med": med, "sc": sc, "res": res, "limit": lim,
                 "p95": med + Z95 * sc, "p5": med - Z95 * sc})

    verdicts = []
    if len(hi):
        if info["p95"] >= ul:
            verdicts.append("Shift")
        else:
            W = w_k * sc
            near = keep[keep >= ul - W]
            gap = float(np.min(hi) - np.max(keep))
            info.update({"near_hi": len(near), "gap_hi": gap, "W": W})
            if len(near) < n_min:
                verdicts.append("Separated")
            else:
                verdicts.append("Tail" if gap <= lim else "Separated")
    if len(lo):
        if info["p5"] <= ll:
            verdicts.append("Shift")
        else:
            W = w_k * sc
            near = keep[keep <= ll + W]
            gap = float(np.min(keep) - np.max(lo))
            info.update({"near_lo": len(near), "gap_lo": gap, "W": W})
            if len(near) < n_min:
                verdicts.append("Separated")
            else:
                verdicts.append("Tail" if gap <= lim else "Separated")
    return "/".join(verdicts), info


def main():
    root = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "Known Data")
    data = read_condition(root)

    print("=== 제안 로직 기준값:  W = %.2f x sigma_core · N_min = %d · "
          "Gap_Limit = MAX(%.2f x sigma_core, %g x 분해능) ===\n" % (W_K, N_MIN, GAP_K, RES_K))
    head = "%-4s %-16s %-16s %-16s %4s %4s %9s %9s %s"
    print(head % ("", "항목", "기대", "실제", "이탈", "근처", "Gap", "한계", "설명"))
    print("-" * 150)
    ok = bad = 0
    detail = []
    for it in SCEN:
        name = it["name"]
        if name not in data:
            print("  **X** %s 열을 못 찾음" % name)
            bad += 1
            continue
        v, ll, ul = data[name]
        got, info = classify(v, ll, ul)
        good = (got == it["expect"])
        ok, bad = (ok + 1, bad) if good else (ok, bad + 1)
        n_oos = info["n_oos_hi"] + info["n_oos_lo"]
        near = info.get("near_hi", info.get("near_lo", "-"))
        gap = info.get("gap_hi", info.get("gap_lo"))
        print(head % ("OK " if good else "**X**", name, it["expect"], got,
                      n_oos, near,
                      ("%.5g" % gap) if gap is not None else "-",
                      ("%.5g" % info["limit"]) if "limit" in info else "-",
                      it["note"]))
        detail.append((it, info, got))
    print("-" * 150)
    print("→ 일치 %d / 불일치 %d  (총 %d 항목)\n" % (ok, bad, len(SCEN)))

    # ── Gap 비 (Gap / Gap_Limit) — 임계 주변 밀집도를 보여 준다 ──────────────
    print("=== Gap / Gap_Limit — 1.0 이 임계 ===")
    rows = []
    for it, info, got in detail:
        gap = info.get("gap_hi", info.get("gap_lo"))
        if gap is None or "limit" not in info or info["limit"] == 0:
            continue
        rows.append((gap / info["limit"], it["name"], got))
    for ratio, name, got in sorted(rows):
        bar = "#" * max(1, int(round(ratio * 30)))
        print("  %6.3f  %-16s %-12s %s" % (ratio, name, got, bar))

    # ── 파라미터 스윕 ───────────────────────────────────────────────────────
    print("\n=== W / N_min 스윕 — 각 칸은 (Tail, Separated, Shift, Normal) 항목 수 ===")
    print("        " + "".join("%-22s" % ("N_min=%d" % n) for n in (1, 2, 3, 5)))
    for w in (0.5, 1.0, 1.5, 2.0, 3.0):
        line = "W=%.1f  " % w
        for n in (1, 2, 3, 5):
            cnt = {"Tail": 0, "Separated": 0, "Shift": 0, "Normal": 0}
            for it in SCEN:
                if it["name"] not in data:
                    continue
                v, ll, ul = data[it["name"]]
                got, _ = classify(v, ll, ul, w_k=w, n_min=n)
                for part in got.split("/"):
                    cnt[part] = cnt.get(part, 0) + 1
            line += "%-22s" % ("%2d/%2d/%2d/%2d" % (cnt["Tail"], cnt["Separated"],
                                                    cnt["Shift"], cnt["Normal"]))
        print(line)

    print("\n=== Near-Spec Pass Count — W 를 키우면 몇 개가 잡히는가 ===")
    print("  %-16s %s" % ("항목", "".join("%-9s" % ("W=%.1f" % w)
                                          for w in (0.5, 1.0, 1.5, 2.0, 3.0))))
    for it in SCEN:
        if it["name"] not in data:
            continue
        v, ll, ul = data[it["name"]]
        if not ((v > ul).any() or (v < ll).any()):
            continue
        med, sc = robust(v)
        keep = v[(v >= ll) & (v <= ul)]
        cells = []
        for w in (0.5, 1.0, 1.5, 2.0, 3.0):
            if (v > ul).any():
                cells.append(int((keep >= ul - w * sc).sum()))
            else:
                cells.append(int((keep <= ll + w * sc).sum()))
        print("  %-16s %s" % (it["name"], "".join("%-9d" % c for c in cells)))

    audit(root)


if __name__ == "__main__":
    main()
