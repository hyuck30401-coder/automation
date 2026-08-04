# -*- coding: utf-8 -*-
"""Save today's analysis output as a golden snapshot for regression_check.py.

Calls cdf_compare_web.analyze_to_json() / analyze_fail_to_json() directly for every
(condition, mode) combo found under --data-root. Does NOT start an HTTP server and
does not touch any of cdf_compare_web's server-only globals.

Usage:
    python tools/regression_snapshot.py --data-root "D:\\...\\Reliability Test Data" --out tests/golden/
    python tools/regression_snapshot.py --data-root <path> --out tests/golden/ --limit 20
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime

from _regression_lib import (
    analyze_condition,
    iter_selections,
    load_web_module,
    set_data_root,
    slugify,
    snapshot_record,
)


def combo_label(entry):
    return f"{entry['device']}/{entry['folder']}/{entry['item']}/{entry['readout']}/{entry['ft_temp']}[{entry['mode']}]"


def sha256_of_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def combo_stats(record):
    items = record.get("items", {})
    item_count = len(items)
    select_count = len(record.get("selected_summary", []))
    detail_rows = [row for item in items.values() for row in item.get("details", [])]
    fail_type_counter = Counter(row.get("fail_type", "") or "" for row in detail_rows)
    return {
        "item_count": item_count,
        "select_count": select_count,
        "detail_count": len(detail_rows),
        "fail_type_counts": dict(sorted(fail_type_counter.items())),
    }


def current_git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        return out.stdout.strip()
    except Exception:
        return "(git rev-parse 실패 - 커밋 정보 없음)"


def write_manifest(out_dir, snapshot_files, combo_summaries, data_root):
    manifest_path = os.path.join(out_dir, "MANIFEST.txt")
    lines = []
    lines.append("# tests/golden/MANIFEST.txt - 골든 스냅샷 출처 기록")
    lines.append("# regression_snapshot.py 가 재생성 시마다 자동 갱신한다 (변경 사유 칸은 사람이 직접 채운다)")
    lines.append("")
    lines.append(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"git commit: {current_git_commit()}")
    lines.append(f"데이터 루트: {os.path.abspath(data_root)}")
    lines.append("")
    lines.append("## 골든 파일")
    lines.append(f"{'파일명':60s} {'sha256':64s} {'바이트':>10s}")
    for filename, sha256, size in snapshot_files:
        lines.append(f"{filename:60s} {sha256:64s} {size:>10d}")
    lines.append("")
    lines.append("## 조합별 요약")
    lines.append(f"{'조합':60s} {'항목수':>6s} {'SELECT수':>8s} {'detail행수':>10s}  fail_type 분포")
    for label, stats in combo_summaries:
        lines.append(
            f"{label:60s} {stats['item_count']:>6d} {stats['select_count']:>8d} "
            f"{stats['detail_count']:>10d}  {stats['fail_type_counts']}"
        )
    lines.append("")
    lines.append("## 직전 재생성 대비 변경 사유 (사람이 적는 칸)")
    lines.append("- (여기에 이번 재생성 사유를 적을 것)")
    lines.append("")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return manifest_path


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Reliability Test Data root folder")
    parser.add_argument("--out", default="tests/golden/", help="Output folder for the golden snapshot")
    parser.add_argument("--limit", type=int, default=0, help="Max number of conditions to process (0 = no limit)")
    return parser.parse_args()


def main():
    args = parse_args()
    web = load_web_module()
    set_data_root(web, args.data_root)

    os.makedirs(args.out, exist_ok=True)

    entries = []
    combo_summaries = []
    condition_count = 0
    for selection in iter_selections(web):
        if args.limit and condition_count >= args.limit:
            break
        produced_any = False
        for mode in ("pass", "fail"):
            try:
                app, payload = analyze_condition(web, selection, mode)
            except Exception as exc:
                print(f"[skip] {selection['device']}/{selection['folder']}/{selection['item']}/"
                      f"{selection['readout']}/{selection['ft_temp']} mode={mode}: {exc}", file=sys.stderr)
                continue
            record = snapshot_record(web, app, payload, mode)
            filename = slugify(
                selection["device"], selection["folder"], selection["item"],
                selection["readout"], selection["ft_temp"], mode,
            ) + ".json"
            out_path = os.path.join(args.out, filename)
            with open(out_path, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
            entry = {**selection, "mode": mode, "file": filename, "message": payload.get("message", "")}
            entries.append(entry)
            combo_summaries.append((combo_label(entry), combo_stats(record)))
            produced_any = True
        if produced_any:
            condition_count += 1

    index_path = os.path.join(args.out, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump({"data_root": os.path.abspath(args.data_root), "combos": entries}, fh, ensure_ascii=False, indent=2)

    snapshot_files = []
    for entry in entries:
        path = os.path.join(args.out, entry["file"])
        snapshot_files.append((entry["file"], sha256_of_file(path), os.path.getsize(path)))
    snapshot_files.append(("index.json", sha256_of_file(index_path), os.path.getsize(index_path)))

    manifest_path = write_manifest(args.out, snapshot_files, combo_summaries, args.data_root)

    print(f"Saved {len(entries)} snapshot(s) across {condition_count} condition(s) to {args.out}")
    print(f"Wrote {manifest_path}")
    if not entries:
        sys.exit(1)


if __name__ == "__main__":
    main()
