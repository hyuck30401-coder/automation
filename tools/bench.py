# -*- coding: utf-8 -*-
"""Segment-level profiler for one condition's analysis pipeline.

Times: read_table / extract_item_records / filter_records_to_last_sample /
calculate_results_vectorized / payload_with_items / json.dumps / cache write.
Runs the pipeline --repeat times (default 3) and reports the median per segment.

By default it auto-picks the combo with the largest post data file under
--data-root. Pass --device/--ver/--type/--lot/--purpose/--item/--readout/--ft-temp
to pin a specific combo instead.

Usage:
    python tools/bench.py --data-root "D:\\...\\Reliability Test Data"
    python tools/bench.py --data-root <path> --mode fail --repeat 5
"""
import argparse
import json
import os
import statistics
import sys
import tempfile
import time

from _regression_lib import (
    analyze_condition,
    instrument_segments,
    load_web_module,
    pick_largest_selection,
    set_data_root,
    SELECTION_KEYS,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", required=True, help="Reliability Test Data root folder")
    parser.add_argument("--mode", choices=["pass", "fail"], default="pass")
    parser.add_argument("--repeat", type=int, default=3)
    for key in SELECTION_KEYS:
        parser.add_argument(f"--{key.replace('_', '-')}", default=None)
    return parser.parse_args()


def selection_from_args(args):
    values = {key: getattr(args, key) for key in SELECTION_KEYS}
    if all(values.values()):
        values["folder"] = ""
        return values
    return None


def run_once(web, selection, mode, segment_bucket):
    web.RECORD_CACHE.clear()
    restore = instrument_segments(web, segment_bucket)
    t_start = time.perf_counter()
    try:
        app, payload = analyze_condition(web, selection, mode)
    finally:
        restore()

    t_payload_start = time.perf_counter()
    payload = web.payload_with_items(app, payload, mode, "none")
    t_payload_end = time.perf_counter()

    body = json.dumps(payload, ensure_ascii=False)
    t_dumps_end = time.perf_counter()

    original_cache_dir = web.CACHE_DIR
    with tempfile.TemporaryDirectory() as tmp_dir:
        web.CACHE_DIR = tmp_dir
        t_cache_start = time.perf_counter()
        try:
            web.save_cached_analysis("bench-run", dict(payload))
        finally:
            web.CACHE_DIR = original_cache_dir
    t_cache_end = time.perf_counter()

    timings = {
        "payload_with_items": t_payload_end - t_payload_start,
        "json.dumps": t_dumps_end - t_payload_end,
        "cache write": t_cache_end - t_cache_start,
        "total": t_cache_end - t_start,
    }
    stats = {
        "payload_bytes": len(body.encode("utf-8")),
        "item_count": len(payload.get("items", {})),
        "detail_rows": sum(len(v.get("details", [])) for v in payload.get("items", {}).values()),
    }
    return timings, stats


def main():
    args = parse_args()
    web = load_web_module()
    set_data_root(web, args.data_root)

    selection = selection_from_args(args)
    if selection is None:
        print("No full selection given on the command line, auto-picking the largest combo under --data-root...")
        selection = pick_largest_selection(web)
    print(f"Selection: {selection['device']}/{selection.get('folder', '')}/{selection['item']}/"
          f"{selection['readout']}/{selection['ft_temp']} mode={args.mode}")

    segment_names = ("read_table", "extract_item_records", "filter_records_to_last_sample", "calculate_results_vectorized")
    other_names = ("payload_with_items", "json.dumps", "cache write", "total")
    samples = {name: [] for name in segment_names + other_names}
    stats = None

    for run_index in range(max(1, args.repeat)):
        bucket = {name: 0.0 for name in segment_names}
        timings, run_stats = run_once(web, selection, args.mode, bucket)
        for name in segment_names:
            samples[name].append(bucket[name])
        for name in other_names:
            samples[name].append(timings[name])
        stats = run_stats
        print(f"  run {run_index + 1}/{args.repeat}: total {timings['total']:.3f}s")

    medians = {name: statistics.median(values) for name, values in samples.items()}
    total_median = medians["total"]

    print()
    print(f"{'segment':32s} {'seconds':>10s} {'% of total':>10s}")
    for name in segment_names + ("payload_with_items", "json.dumps", "cache write"):
        seconds = medians[name]
        pct = (seconds / total_median * 100) if total_median else 0.0
        print(f"{name:32s} {seconds:10.3f} {pct:9.1f}%")
    print(f"{'TOTAL (wall, median)':32s} {total_median:10.3f}")

    print()
    print(f"payload bytes: {stats['payload_bytes']:,}")
    print(f"item count: {stats['item_count']}")
    print(f"total detail rows: {stats['detail_rows']}")


if __name__ == "__main__":
    main()
