# -*- coding: utf-8 -*-
"""Shared helpers for regression_snapshot.py / regression_check.py / bench.py.

Imports cdf_compare_web.py as a plain module and drives analyze_to_json() /
analyze_fail_to_json() directly -- no HTTP server, no reliance on the module's
server-only globals (CURRENT_APP, CURRENT_PAYLOADS, JOBS, ...).
"""
import os
import re
import sys
import time


def load_web_module():
    """Import cdf_compare_web.py from the project root (parent of tools/)."""
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    import cdf_compare_web as web
    return web


def set_data_root(web, data_root):
    web.DATA_ROOT = os.path.abspath(data_root)


SELECTION_KEYS = ("device", "ver", "lot", "purpose", "item", "readout", "ft_temp")


def iter_selections(web):
    """Enumerate every (device/folder/item/readout/ft_temp) combo under DATA_ROOT."""
    data_root = web.DATA_ROOT
    for device in web.child_dirs(data_root):
        device_path = web.safe_child(data_root, device)
        for folder in web.device_data_folders(device_path):
            base = web.safe_child(device_path, folder["name"])
            try:
                post_dir = web.child_dir_containing(base, "post")
            except ValueError:
                continue
            for item in web.RELIABILITY_ITEMS:
                readouts = web.post_file_readouts(post_dir, item)
                for readout in readouts:
                    ft_temps = web.post_file_ft_temps(post_dir, item, readout)
                    for ft_temp in ft_temps:
                        yield {
                            "device": device,
                            "ver": folder["ver"],
                            "lot": folder["lot"],
                            "purpose": folder["purpose"],
                            "folder": folder["name"],
                            "item": item,
                            "readout": readout,
                            "ft_temp": ft_temp,
                        }


def resolve_files(web, selection):
    sel = {key: selection[key] for key in SELECTION_KEYS}
    return web.resolve_selection_file_set(sel)


def analyze_condition(web, selection, mode, include_pre=True):
    """Run analyze_to_json() / analyze_fail_to_json() for one (condition, mode)."""
    pre_path, post_files, _base = resolve_files(web, selection)
    if mode == "pass":
        post_path = post_files[-1]
        app, payload = web.analyze_to_json(pre_path, post_path, True, None, include_pre)
    elif mode == "fail":
        app, payload = web.analyze_fail_to_json(pre_path, post_files, None, include_pre)
    else:
        raise ValueError(f"Unknown mode: {mode}")
    # Pre-existing bug (see NOTES.md): CdfCompareApp is built via object.__new__(),
    # so tk.Tk.__init__ never runs and `self.tk` is never set. item_to_json() reads
    # getattr(app, "pre_pass_samples", PASS_SAMPLE_IDS_AUTO); if the attribute is
    # missing, tk.Tk's own __getattr__ tries to delegate to the also-missing self.tk
    # and recurses infinitely (RecursionError, not AttributeError -- getattr's
    # default never kicks in). analyze_fail_to_json()'s app never sets this attribute
    # at all, so it still needs the fallback here. analyze_to_json()'s app (via
    # make_app()) now always sets a real value (a set, or None when there is no bin
    # data) -- only backfill when the attribute is genuinely absent, or this
    # unconditionally overwrites that real value with the sentinel and forces
    # item_to_json() to recompute it from scratch for every item (the O(items x
    # pre_records) bug make_app() was just fixed to avoid).
    # NOTE: must check app.__dict__ directly, not hasattr()/getattr() -- those would
    # trigger the exact recursion described above on the fail-mode app.
    if "pre_pass_samples" not in app.__dict__:
        app.pre_pass_samples = web.PASS_SAMPLE_IDS_AUTO
    return app, payload


def select_items_payload(web, app, payload, mode):
    """details of SELECT-ed items only, keyed by item name, in results order."""
    items = {}
    for row in payload.get("results", []):
        if row.get("result") != "SELECT":
            continue
        item = row.get("item")
        if not item or item in items:
            continue
        if mode == "fail":
            source = (payload.get("items") or {}).get(item) or {}
            details = source.get("details", [])
        else:
            details = web.item_to_json(app, item).get("details", [])
        items[item] = {"details": details}
    return items


def snapshot_record(web, app, payload, mode):
    return {
        "results": payload.get("results", []),
        "selected_summary": payload.get("selected_summary", []),
        "over_sigma": payload.get("over_sigma", []),
        "items": select_items_payload(web, app, payload, mode),
    }


def slugify(*parts):
    text = "__".join(str(part) for part in parts)
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)


# ---- comparison (used by regression_check.py) --------------------------------

_MISSING = object()
_ABS_TOL = 1e-9
_REL_TOL = 1e-12


def values_equal(old, new):
    if old is None or new is None:
        return old is None and new is None
    if isinstance(old, bool) or isinstance(new, bool):
        return old == new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        if isinstance(old, float) or isinstance(new, float):
            fa, fb = float(old), float(new)
            if fa == fb:
                return True
            diff = abs(fa - fb)
            if diff <= _ABS_TOL:
                return True
            denom = max(abs(fa), abs(fb))
            return denom > 0 and diff / denom <= _REL_TOL
        return old == new
    return old == new


def _compare_dict(old, new, path, out):
    for key in sorted(set(old) | set(new)):
        ov = old.get(key, _MISSING)
        nv = new.get(key, _MISSING)
        if ov is _MISSING or nv is _MISSING:
            out.append((path, key, "<missing>" if ov is _MISSING else ov, "<missing>" if nv is _MISSING else nv))
            continue
        if not values_equal(ov, nv):
            out.append((path, key, ov, nv))


def _compare_row_list(old_list, new_list, section, row_label, out):
    if len(old_list) != len(new_list):
        out.append((section, "row_count", len(old_list), len(new_list)))
    for index in range(min(len(old_list), len(new_list))):
        label = row_label(old_list[index], index)
        _compare_dict(old_list[index], new_list[index], f"{section}[{label}]", out)


def compare_records(golden, current, combo_label):
    """Returns a list of (combo_label, path, field, old_value, new_value) mismatches."""
    out = []

    _compare_row_list(
        golden.get("results", []), current.get("results", []),
        "results", lambda row, i: row.get("item", i), out,
    )
    _compare_row_list(
        golden.get("selected_summary", []), current.get("selected_summary", []),
        "selected_summary", lambda row, i: row.get("item", i), out,
    )

    old_over = golden.get("over_sigma", [])
    new_over = current.get("over_sigma", [])
    if len(old_over) != len(new_over):
        out.append(("over_sigma", "row_count", len(old_over), len(new_over)))
    for index in range(min(len(old_over), len(new_over))):
        o, n = old_over[index], new_over[index]
        label = o.get("sample", index)
        if o.get("sample") != n.get("sample"):
            out.append((f"over_sigma[{label}]", "sample", o.get("sample"), n.get("sample")))
        if o.get("items") != n.get("items"):
            out.append((f"over_sigma[{label}]", "items", o.get("items"), n.get("items")))

    old_items = golden.get("items", {})
    new_items = current.get("items", {})
    old_keys = list(old_items.keys())
    new_keys = list(new_items.keys())
    if old_keys != new_keys:
        out.append(("items", "item_keys(order+set)", old_keys, new_keys))
    for item in sorted(set(old_keys) | set(new_keys)):
        _compare_row_list(
            old_items.get(item, {}).get("details", []),
            new_items.get(item, {}).get("details", []),
            f"items/{item}/details",
            lambda row, i: row.get("sample", i),
            out,
        )

    return [(combo_label,) + tup for tup in out]


# ---- instrumentation (used by bench.py) ---------------------------------------

INSTRUMENTED_FUNCS = (
    "read_table",
    "extract_item_records",
    "filter_records_to_last_sample",
    "calculate_results_vectorized",
)


def instrument_segments(web, bucket):
    """Monkeypatch web.<name> for INSTRUMENTED_FUNCS to accumulate elapsed time
    into bucket[name]. Returns a restore() callback."""
    originals = {name: getattr(web, name) for name in INSTRUMENTED_FUNCS}

    def make_wrapper(func, key):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            bucket[key] += time.perf_counter() - start
            return result
        return wrapper

    for name, func in originals.items():
        setattr(web, name, make_wrapper(func, name))

    def restore():
        for name, func in originals.items():
            setattr(web, name, func)

    return restore


def pick_largest_selection(web):
    """Pick the combo whose post file is largest, for a realistic bench target."""
    best = None
    best_size = -1
    for selection in iter_selections(web):
        try:
            _pre_path, post_files, _base = resolve_files(web, selection)
        except Exception:
            continue
        if not post_files:
            continue
        size = os.path.getsize(post_files[-1])
        if size > best_size:
            best_size = size
            best = selection
    if best is None:
        raise RuntimeError("No usable data combo was found under DATA_ROOT.")
    return best
