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
import json
import os
import sys

from _regression_lib import (
    analyze_condition,
    iter_selections,
    load_web_module,
    set_data_root,
    slugify,
    snapshot_record,
)


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
            entries.append({**selection, "mode": mode, "file": filename, "message": payload.get("message", "")})
            produced_any = True
        if produced_any:
            condition_count += 1

    index_path = os.path.join(args.out, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump({"data_root": os.path.abspath(args.data_root), "combos": entries}, fh, ensure_ascii=False, indent=2)

    print(f"Saved {len(entries)} snapshot(s) across {condition_count} condition(s) to {args.out}")
    if not entries:
        sys.exit(1)


if __name__ == "__main__":
    main()
