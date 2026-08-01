# -*- coding: utf-8 -*-
"""Compare today's analysis output against a golden snapshot from regression_snapshot.py.

Exit code 0 = all combos match. Exit code 1 = at least one mismatch or a combo that
could no longer be reproduced (e.g. missing data file).

Comparison rules:
  - string / int fields: exact match
  - float fields: pass if abs(old - new) <= 1e-9 OR abs(old - new) / max(|old|,|new|) <= 1e-12
  - None vs. a real value is always a mismatch
  - item set, item order, results/selected_summary row order and count, and detail
    row order within each SELECT-ed item are all checked

Usage:
    python tools/regression_check.py --data-root "D:\\...\\Reliability Test Data" --golden tests/golden/
"""
import argparse
import json
import os
import sys

from _regression_lib import analyze_condition, load_web_module, set_data_root, snapshot_record, compare_records


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Reliability Test Data root folder")
    parser.add_argument("--golden", default="tests/golden/", help="Folder written by regression_snapshot.py")
    return parser.parse_args()


def combo_label(entry):
    return f"{entry['device']}/{entry['folder']}/{entry['item']}/{entry['readout']}/{entry['ft_temp']}[{entry['mode']}]"


def main():
    args = parse_args()
    web = load_web_module()
    set_data_root(web, args.data_root)

    index_path = os.path.join(args.golden, "index.json")
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    combos = index.get("combos", [])
    if not combos:
        print(f"No combos found in {index_path}. Run regression_snapshot.py first.")
        sys.exit(1)

    all_mismatches = []
    condition_errors = []
    passed = 0

    for entry in combos:
        label = combo_label(entry)
        golden_path = os.path.join(args.golden, entry["file"])
        try:
            with open(golden_path, encoding="utf-8") as fh:
                golden = json.load(fh)
        except OSError as exc:
            condition_errors.append((label, f"cannot read golden file: {exc}"))
            continue

        try:
            app, payload = analyze_condition(web, entry, entry["mode"])
        except Exception as exc:
            condition_errors.append((label, f"analysis failed: {exc}"))
            continue

        current = snapshot_record(web, app, payload, entry["mode"])
        mismatches = compare_records(golden, current, label)
        if mismatches:
            all_mismatches.extend(mismatches)
        else:
            passed += 1

    total = len(combos)
    failed = total - passed - len(condition_errors)
    print(f"Combos: {total} total, {passed} passed, {failed} with mismatches, {len(condition_errors)} could not be reproduced")

    if condition_errors:
        print("\nConditions that could not be reproduced:")
        for label, reason in condition_errors[:20]:
            print(f"  - {label}: {reason}")
        if len(condition_errors) > 20:
            print(f"  ... and {len(condition_errors) - 20} more")

    if all_mismatches:
        print(f"\nFirst {min(20, len(all_mismatches))} of {len(all_mismatches)} field mismatch(es):")
        print(f"{'combo':50s} {'path':30s} {'field':20s} {'old':>20s} {'new':>20s}")
        for combo, path, field, old, new in all_mismatches[:20]:
            print(f"{combo:50s} {path:30s} {field:20s} {str(old):>20s} {str(new):>20s}")

    if all_mismatches or condition_errors:
        print("\nFAIL")
        sys.exit(1)

    print("\nPASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
