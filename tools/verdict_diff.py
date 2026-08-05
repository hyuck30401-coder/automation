# -*- coding: utf-8 -*-
"""Compare pass/fail verdicts (SELECT / OK / 판정불가) before and after a code change.

tools/regression_check.py answers "did anything change" and fails (exit 1) on any
byte-level diff -- it exists to prove a *performance* refactor is a pure no-op.
This tool answers a different question: "what changed, and how much." From
통계개선_프롬프트.md §S2 onward, the statistics themselves are being changed on
purpose (ddof, Grubbs threshold, diff_ratio sign/EPS), so regression_check.py is
expected to fail every time -- it can't tell you whether the failure matches what
you intended. verdict_diff.py can: it classifies every item's SELECT/OK/판정불가
result before and after, and reports the transition counts, newly-SELECTed items,
dropped-from-SELECT items, and items whose mea_s moved the most.

Usage:
    # 기준선 저장 (코드 변경 전에 한 번)
    python tools/verdict_diff.py --data-root "...\\Test Data" --save tests/verdict_base/

    # 코드 변경 후 비교
    python tools/verdict_diff.py --data-root "...\\Test Data" --baseline tests/verdict_base/

## 저장 형식
tests/golden/ (regression_snapshot.py) 과 같은 레이아웃이다: index.json 에 조합 목록,
조합별 파일 하나에 그 조합의 item_rows/sample_rows. golden 과 달리 payload 전체가
아니라 판정에 관련된 필드(mea_s, diff_s, result, n, mean, sigma, device_id)만 담아
파일이 훨씬 작다.

## 알려진 제약
- 항목 단위(item_rows)는 pass 모드는 전체 항목(app.post_items, SELECT 여부 무관),
  fail 모드는 selected_summary 에 있는 항목(스펙 fail 이 하나라도 있는 항목)만이다.
  analyze_fail_to_json 자체가 스펙 통과 항목을 결과에 담지 않기 때문에, 이 도구가
  기존 소스를 건드리지 않는 한 fail 모드의 "전체 항목" 개념은 없다.
- 샘플 단위(sample_rows)의 device_id 는 pass 모드만 채워진다. fail 모드는
  analyze_fail_to_json() 이 만드는 app.post_records 가 애초에 비어 있어({}) 그
  경로로는 device_id 를 복구할 수 없다 (fail 모드 결과 자체는 정상, device_id 필드만
  None). 기존 소스를 고치지 않고는 얻을 수 없어 이번 단계에서는 손대지 않는다.
- item 단위 SELECT 판정의 "임계값"은 아직 고정 FLAG_LIMIT(=3) 하나뿐이다 (§S3 에서
  n별 Grubbs 임계로 바뀔 예정). "SELECT 에서 빠진 항목" 리포트의 임계값 표시는 그때
  가서 항목별 threshold 필드를 참조하도록 넓혀야 한다.
"""
import argparse
import json
import os
import sys
from collections import Counter

# Windows 콘솔 기본 코드페이지(cp949)로는 한글 출력이 깨진다. CLAUDE.md "파일 인코딩"
# 지침(UTF-8로 읽고 쓴다)을 표준출력에도 적용한다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from _regression_lib import analyze_condition, iter_selections, load_web_module, set_data_root, slugify


def combo_label(entry):
    return f"{entry['device']}/{entry['folder']}/{entry['item']}/{entry['readout']}/{entry['ft_temp']}[{entry['mode']}]"


def classify_result(result):
    """Collapse the app's many literal result strings into the 3-bucket scheme this
    tool reports on. 'SELECT'/'OK' pass through; everything else (None, 'NO PRE ITEM',
    'NO PRE SAMPLE', and future 'INSUFFICIENT N'/'NOT EVALUATED' from §S3/§S5) is
    '판정불가' -- a verdict was not or could not be reached."""
    if result == "SELECT":
        return "SELECT"
    if result == "OK":
        return "OK"
    return "판정불가"


def select_reason(mea_s, diff_s, flag_limit):
    mea_flag = mea_s is not None and abs(mea_s) > flag_limit
    diff_flag = diff_s is not None and abs(diff_s) > flag_limit
    if mea_flag and diff_flag:
        return "Measured + Delta"
    if mea_flag:
        return "Measured"
    if diff_flag:
        return "Delta"
    return ""


def item_rows_for_combo(web, app, payload, mode):
    """item -> {item, n, mean, sigma, mea_s, diff_s, result}."""
    rows = {}
    if mode == "pass":
        for row in payload.get("results", []):
            item = row.get("item")
            if not item or item in rows:
                continue
            rows[item] = {
                "item": item,
                "n": row.get("n_post"),
                "mean": row.get("post_mean"),
                "sigma": row.get("post_sigma"),
                "mea_s": row.get("mea_s"),
                "diff_s": row.get("diff_s"),
                "result": row.get("result"),
            }
    else:
        # analyze_fail_to_json only reports items with >=1 spec-fail sample; there is
        # no per-item mea_s/diff_s max in selected_summary, so derive it from details.
        for item, item_payload in payload.get("items", {}).items():
            details = item_payload.get("details", [])
            mea_s_vals = [d.get("mea_s") for d in details if d.get("mea_s") is not None]
            diff_s_vals = [d.get("diff_s") for d in details if d.get("diff_s") is not None]
            summary_row = next((r for r in payload.get("selected_summary", []) if r.get("item") == item), {})
            rows[item] = {
                "item": item,
                "n": summary_row.get("n"),
                "mean": summary_row.get("avg"),
                "sigma": summary_row.get("stdev"),
                "mea_s": max(mea_s_vals, key=abs) if mea_s_vals else None,
                "diff_s": max(diff_s_vals, key=abs) if diff_s_vals else None,
                "result": "SELECT",
            }
    return rows


def sample_rows_for_combo(web, app, payload, mode):
    """(item, sample) -> {item, sample, device_id, mea_s, diff_s, result}."""
    rows = {}
    if mode == "pass":
        for item in sorted(app.post_items):
            item_json = web.item_to_json(app, item)
            raw_records = app.post_records.get(item, [])
            for index, detail in enumerate(item_json.get("details", [])):
                device_id = raw_records[index].get("device_id", "") if index < len(raw_records) else ""
                rows[(item, detail.get("sample"))] = {
                    "item": item,
                    "sample": detail.get("sample"),
                    "device_id": device_id,
                    "mea_s": detail.get("mea_s"),
                    "diff_s": detail.get("diff_s"),
                    "result": detail.get("result"),
                }
    else:
        for item, item_payload in payload.get("items", {}).items():
            for detail in item_payload.get("details", []):
                rows[(item, detail.get("sample"))] = {
                    "item": item,
                    "sample": detail.get("sample"),
                    "device_id": None,
                    "mea_s": detail.get("mea_s"),
                    "diff_s": detail.get("diff_s"),
                    "result": detail.get("result"),
                }
    return rows


def build_records(web, combos):
    """Run analyze_condition() for every (selection, mode) combo and collect
    item/sample verdict rows keyed by (combo_label, item[, sample])."""
    item_index = {}
    sample_index = {}
    errors = []
    for entry in combos:
        label = combo_label(entry)
        try:
            app, payload = analyze_condition(web, entry, entry["mode"])
        except Exception as exc:
            errors.append((label, str(exc)))
            continue
        for item, row in item_rows_for_combo(web, app, payload, entry["mode"]).items():
            item_index[(label, item)] = row
        for (item, sample), row in sample_rows_for_combo(web, app, payload, entry["mode"]).items():
            sample_index[(label, item, sample)] = row
    return item_index, sample_index, errors


# ---- save -----------------------------------------------------------------------

def do_save(web, args):
    combos = []
    for selection in iter_selections(web):
        for mode in ("pass", "fail"):
            combos.append({**selection, "mode": mode})

    item_index, sample_index, errors = build_records(web, combos)

    os.makedirs(args.save, exist_ok=True)
    entries = []
    by_combo_items = {}
    by_combo_samples = {}
    for (label, item), row in item_index.items():
        by_combo_items.setdefault(label, {})[item] = row
    for (label, item, sample), row in sample_index.items():
        by_combo_samples.setdefault(label, []).append(row)

    seen_labels = set()
    for entry in combos:
        label = combo_label(entry)
        if label in seen_labels:
            continue
        if label not in by_combo_items and label not in by_combo_samples:
            continue  # this combo failed to analyze; not saved
        seen_labels.add(label)
        item_rows = sorted(by_combo_items.get(label, {}).values(), key=lambda r: r["item"])
        sample_rows = sorted(by_combo_samples.get(label, []), key=lambda r: (r["item"], str(r["sample"])))
        filename = slugify(entry["device"], entry["folder"], entry["item"], entry["readout"], entry["ft_temp"], entry["mode"]) + ".json"
        with open(os.path.join(args.save, filename), "w", encoding="utf-8") as fh:
            json.dump({"item_rows": item_rows, "sample_rows": sample_rows}, fh, ensure_ascii=False, indent=2)
        entries.append({**entry, "file": filename})

    with open(os.path.join(args.save, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"data_root": os.path.abspath(args.data_root), "combos": entries}, fh, ensure_ascii=False, indent=2)

    total_items = len(item_index)
    total_samples = len(sample_index)
    print(f"Saved {len(entries)} combo(s), {total_items} item-row(s), {total_samples} sample-row(s) to {args.save}")
    if errors:
        print(f"\n{len(errors)} combo(s) could not be analyzed (not saved):")
        for label, reason in errors[:20]:
            print(f"  - {label}: {reason}")
    if not entries:
        sys.exit(1)
    sys.exit(0)


# ---- compare --------------------------------------------------------------------

def load_baseline(path):
    index_path = os.path.join(path, "index.json")
    if not os.path.isfile(index_path):
        print(f"baseline이 없다 ({index_path}). --save 로 먼저 만들어라.")
        sys.exit(1)
    with open(index_path, encoding="utf-8") as fh:
        index = json.load(fh)
    combos = index.get("combos", [])
    item_index = {}
    sample_index = {}
    for entry in combos:
        label = combo_label(entry)
        file_path = os.path.join(path, entry["file"])
        with open(file_path, encoding="utf-8") as fh:
            record = json.load(fh)
        for row in record.get("item_rows", []):
            item_index[(label, row["item"])] = row
        for row in record.get("sample_rows", []):
            sample_index[(label, row["item"], row["sample"])] = row
    return combos, item_index, sample_index


def summary_lines(before_items, after_items):
    before_counts = Counter(classify_result(row.get("result")) for row in before_items.values())
    after_counts = Counter(classify_result(row.get("result")) for row in after_items.values())
    lines = ["1. 요약 비교"]
    for bucket in ("SELECT", "OK", "판정불가"):
        b, a = before_counts.get(bucket, 0), after_counts.get(bucket, 0)
        lines.append(f"     {bucket:8s} {b:6d} → {a:<6d} ({a - b:+d})")
    return lines


def transition_matrix_lines(before_items, after_items):
    labels = ("OK", "SELECT", "판정불가", "(신규)", "(삭제)")
    matrix = Counter()
    keys = set(before_items) | set(after_items)
    for key in keys:
        b = classify_result(before_items[key].get("result")) if key in before_items else "(신규)"
        a = classify_result(after_items[key].get("result")) if key in after_items else "(삭제)"
        matrix[(b, a)] += 1
    lines = ["", "2. 판정 전이 행렬 (행=변경 전, 열=변경 후)"]
    header = " " * 10 + "".join(f"{col:>10s}" for col in labels)
    lines.append(header)
    for row_label in labels:
        cells = "".join(f"{matrix.get((row_label, col), 0):>10d}" for col in labels)
        lines.append(f"  {row_label:8s}{cells}")
    return lines


def top_new_select_lines(before_items, after_items, flag_limit, top_n=20):
    lines = ["", f"3. 새로 SELECT 된 항목 상위 {top_n}개 (mea_s 내림차순)"]
    rows = []
    for key, row in after_items.items():
        if classify_result(row.get("result")) != "SELECT":
            continue
        before_row = before_items.get(key)
        if before_row is not None and classify_result(before_row.get("result")) == "SELECT":
            continue
        mea_s = row.get("mea_s")
        rows.append((key, row, mea_s))
    rows.sort(key=lambda t: abs(t[2]) if t[2] is not None else -1, reverse=True)
    if not rows:
        lines.append("     (없음)")
    for (label, item), row, mea_s in rows[:top_n]:
        reason = select_reason(row.get("mea_s"), row.get("diff_s"), flag_limit)
        lines.append(f"     {label}/{item}  mea_s={mea_s}  diff_s={row.get('diff_s')}  reason={reason}")
    return lines


def top_dropped_select_lines(before_items, after_items, flag_limit, top_n=20):
    lines = ["", f"4. SELECT 에서 빠진 항목 상위 {top_n}개 (이전 mea_s 내림차순, 현재 임계값={flag_limit})"]
    rows = []
    for key, row in before_items.items():
        if classify_result(row.get("result")) != "SELECT":
            continue
        after_row = after_items.get(key)
        if after_row is not None and classify_result(after_row.get("result")) == "SELECT":
            continue
        mea_s = row.get("mea_s")
        rows.append((key, row, after_row, mea_s))
    rows.sort(key=lambda t: abs(t[3]) if t[3] is not None else -1, reverse=True)
    if not rows:
        lines.append("     (없음)")
    for (label, item), before_row, after_row, mea_s in rows[:top_n]:
        after_mea_s = after_row.get("mea_s") if after_row else None
        after_diff_s = after_row.get("diff_s") if after_row else None
        lines.append(f"     {label}/{item}  이전 mea_s={mea_s} diff_s={before_row.get('diff_s')}"
                      f"  →  현재 mea_s={after_mea_s} diff_s={after_diff_s}")
    return lines


def top_changed_mea_s_lines(before_items, after_items, top_n=20):
    lines = ["", f"5. 수치가 바뀐 항목 상위 {top_n}개 (mea_s 변화량 순)"]
    rows = []
    for key in set(before_items) & set(after_items):
        b = before_items[key].get("mea_s")
        a = after_items[key].get("mea_s")
        if b is None or a is None:
            continue
        delta = a - b
        if abs(delta) <= 1e-9:
            continue
        rows.append((key, b, a, delta))
    rows.sort(key=lambda t: abs(t[3]), reverse=True)
    if not rows:
        lines.append("     (없음)")
    for (label, item), b, a, delta in rows[:top_n]:
        lines.append(f"     {label}/{item}  mea_s {b:.4f} → {a:.4f}  ({delta:+.4f})")
    return lines


def do_compare(web, args):
    combos, before_items, before_samples = load_baseline(args.baseline)
    after_items, after_samples, errors = build_records(web, combos)

    report_lines = []
    if errors:
        report_lines.append(f"{len(errors)} combo(s) could not be reproduced:")
        for label, reason in errors[:20]:
            report_lines.append(f"  - {label}: {reason}")
        report_lines.append("")

    flag_limit = getattr(web, "FLAG_LIMIT", 3.0)

    report_lines += summary_lines(before_items, after_items)
    report_lines += transition_matrix_lines(before_items, after_items)
    report_lines += top_new_select_lines(before_items, after_items, flag_limit)
    report_lines += top_dropped_select_lines(before_items, after_items, flag_limit)
    report_lines += top_changed_mea_s_lines(before_items, after_items)

    identical = (before_items == after_items) and (before_samples == after_samples)
    report_lines.append("")
    report_lines.append("차이 없음" if identical else "차이 있음 (위 리포트 참조)")

    for line in report_lines:
        print(line)

    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)) or ".", exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write("\n".join(report_lines) + "\n")
        print(f"\n리포트 저장: {args.report}")

    sys.exit(0 if identical else 1)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", required=True, help="Reliability Test Data root folder")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--save", metavar="DIR", help="현재 코드의 판정 결과를 baseline 으로 저장")
    group.add_argument("--baseline", metavar="DIR", help="이 baseline 과 현재 코드 결과를 비교")
    parser.add_argument("--report", metavar="FILE", help="--baseline 비교 리포트를 텍스트 파일로도 저장 (예: docs/verdict_reports/S2.md)")
    return parser.parse_args()


def main():
    args = parse_args()
    web = load_web_module()
    set_data_root(web, args.data_root)
    if args.save:
        do_save(web, args)
    else:
        do_compare(web, args)


if __name__ == "__main__":
    main()
