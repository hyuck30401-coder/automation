# -*- coding: utf-8 -*-
"""
fast_datalog.py — CDF Compare Tool 속도 개선용 데이터로그 로더/분석기 (Rev.2)

핵심 원칙
  1) 전 항목은 **컬럼형 numpy 배열**로 처리한다. record-dict 를 만들지 않는다.
  2) record-dict / details 는 **SELECT 된 항목에만** 필요할 때 만든다.
  3) 파싱 결과는 (경로, mtime, size) 키로 **디스크에 캐시**한다.
  4) Pre↔Post 조인은 **DEVICE_ID** 기준이다. Serial # 가 아니다.

Rev.2 변경점
  - DEVICE_ID 컬럼을 이름으로 찾아 행별 식별자로 보관하고, 분석 항목에서는 제외
  - Pre↔Post 조인 키를 device_id 로 (없으면 sample 로 폴백)
  - Pre 에 같은 device_id 가 여러 번 나오면 마지막 등장을 채택
  - 매칭 통계(match_summary)를 반환해 조용한 실패를 막음

기존 코드와의 접점
  - extract_item_records(table) 대체 → read_datalog(path)
  - calculate_results_vectorized(app) 대체 → analyze(pre, post)
  - item_to_json(app, item) 대체 → details_for(pre, post, item)
  - 기존 구조가 꼭 필요한 곳 → materialize_records(ds, items=[...])

의존성: numpy 뿐 (기존과 동일)
"""

import csv
import hashlib
import math
import os
import pickle
import re
import zipfile
from xml.etree import ElementTree as ET

import numpy as np

__all__ = [
    "Dataset", "read_datalog", "analyze", "details_for",
    "materialize_records", "match_summary", "clear_disk_cache",
    "ID_ITEM_NAMES", "FLAG_LIMIT",
]

FLAG_LIMIT = 3.0
CACHE_VERSION = 2

# Test Name 행에서 이 이름을 가진 컬럼은 '측정값'이 아니라 '유닛 식별자'로 취급한다.
# 나중에 이름이 늘어날 수 있으므로 튜플로 둔다.
ID_ITEM_NAMES = ("DEVICE_ID",)

_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_META_NAMES = frozenset({
    "ycoord", "sample", "bin", "xcoord", "site",
    "serial#", "sampleno", "serial", "site#",
})


# ---------------------------------------------------------------- 유틸

def _text(v):
    return "" if v is None else str(v).strip()


def _norm(v):
    return re.sub(r"[\s_\-:.#()]", "", _text(v).lower())


def _to_float(v):
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
    except ValueError:
        try:
            f = float(s.replace(",", ""))
        except ValueError:
            return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------- 파일 읽기

def _read_csv(path):
    with open(path, "rb") as fh:
        head = fh.read(4)
    encodings = ("utf-16",) if head[:2] in (b"\xff\xfe", b"\xfe\xff") \
        else ("utf-8-sig", "cp949", "latin-1")
    last = None
    for enc in encodings:
        try:
            with open(path, newline="", encoding=enc) as fh:
                sample = fh.read(64 * 1024)
                fh.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
                except csv.Error:
                    dialect = csv.excel
                return list(csv.reader(fh, dialect))
        except UnicodeDecodeError as exc:
            last = exc
    raise last


def _read_xlsx(path):
    """iterparse 스트리밍 + 생략된 빈 행을 r= 기준으로 복원."""
    with zipfile.ZipFile(path) as zf:
        shared = _read_shared_strings(zf)
        target = _first_sheet_path(zf)
        table, cells, cur = [], {}, 0
        with zf.open(target) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                tag = el.tag.rsplit("}", 1)[-1]
                if tag == "c":
                    ci = _col_index(el.attrib.get("r", ""))
                    cells[len(cells) if ci is None else ci] = _cell_value(el, shared)
                    el.clear()
                elif tag == "row":
                    r = int(el.attrib.get("r", cur + 1))
                    while cur + 1 < r:
                        table.append([])
                        cur += 1
                    w = (max(cells) + 1) if cells else 0
                    table.append([cells.get(i, "") for i in range(w)])
                    cells, cur = {}, r
                    el.clear()
    return table


def _cell_value(el, shared):
    t = el.attrib.get("t", "")
    if t == "inlineStr":
        node = el.find(".//x:t", _NS)
        return "" if node is None else (node.text or "")
    node = el.find("x:v", _NS)
    raw = "" if node is None else (node.text or "")
    if t == "s" and raw:
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return ""
    if t == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw                                    # t="e"(#N/A 등)는 원문 보존


def _read_shared_strings(zf):
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall("x:si", _NS):
        direct = si.findall("x:t", _NS)           # rPh(후리가나) 제외
        if not direct:
            direct = [t for r in si.findall("x:r", _NS) for t in r.findall("x:t", _NS)]
        out.append("".join(n.text or "" for n in direct))
    return out


def _first_sheet_path(zf):
    wb = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    sheet = wb.find("x:sheets/x:sheet", _NS)
    if sheet is None:
        raise ValueError("XLSX 파일에 워크시트가 없습니다.")
    rid = sheet.attrib.get(
        "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    for rel in rels.findall(
            "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        if rel.attrib.get("Id") == rid:
            t = rel.attrib.get("Target", "").lstrip("/")
            return t if t.startswith("xl/") else "xl/" + t
    raise ValueError("워크시트 관계를 찾을 수 없습니다.")


def _col_index(ref):
    letters = "".join(c for c in (ref or "") if "A" <= c.upper() <= "Z")
    if not letters:
        return None                               # 원본의 -1 반환 버그 회피
    idx = 0
    for c in letters.upper():
        idx = idx * 26 + (ord(c) - ord("A")) + 1
    return idx - 1


# ---------------------------------------------------------------- 데이터셋

class Dataset(object):
    """항목당 float64 배열 1개 + 메타 1벌. record-dict 를 만들지 않는다."""

    __slots__ = ("items", "samples", "ids", "bins", "sites", "path", "warnings")

    def __init__(self, items, samples, ids, bins, sites, path="", warnings=None):
        self.items = items        # {item: {'values': ndarray, 'rows': ndarray|None, ...}}
        self.samples = samples    # [str] Serial # — 화면 표시용
        self.ids = ids            # [str] DEVICE_ID — 조인용 (없으면 전부 "")
        self.bins = bins          # [str] | None
        self.sites = sites        # [str] | None
        self.path = path
        self.warnings = warnings or []

    # --- 조인 ---------------------------------------------------

    def has_ids(self):
        return any(self.ids) if self.ids else False

    def key_list(self, prefer_id=True):
        """행별 조인 키. DEVICE_ID 가 있으면 그것, 없으면 Serial #."""
        if prefer_id and self.has_ids():
            return self.ids
        return self.samples

    def key_index(self, prefer_id=True):
        """조인 키 → 행 인덱스. 같은 키가 여러 번이면 **마지막 등장**을 채택."""
        keys = self.key_list(prefer_id)
        out = {}
        for i, k in enumerate(keys):
            if k:
                out[k] = i
        return out

    def values_full(self, item):
        """행 수만큼 길이를 맞춘 배열(결측은 nan). 인덱스 오정렬 방지."""
        d = self.items.get(item)
        if d is None:
            return None
        out = np.full(len(self.samples), np.nan)
        rows = d["rows"]
        out[np.arange(d["values"].size) if rows is None else rows] = d["values"]
        return out


def _parse_column(col):
    """열 전체 일괄 파싱. 전부 숫자면 C 레벨 map 으로 초고속."""
    try:
        return list(map(float, col)), None
    except ValueError:
        pass
    vals, idx = [], []
    for i, s in enumerate(col):
        try:
            v = float(s)
        except (ValueError, TypeError):
            continue
        if math.isfinite(v):
            vals.append(v)
            idx.append(i)
    return vals, idx


def _find_row(table, labels):
    t = {_norm(x) for x in labels}
    for i, row in enumerate(table):
        if any(_norm(c) in t for c in row):
            return i
    return None


def _find_name_row(table, dh):
    """A열이 Test Name 인 행 중 비어있지 않은 셀이 가장 많은 행."""
    best, best_n = None, 0
    for i in range(dh):
        row = table[i]
        if not row or _norm(row[0]) not in ("testname", "testitem", "itemname"):
            continue
        n = sum(1 for v in row if _text(v))
        if n > best_n:
            best, best_n = i, n
    return best


def _find_col(row, labels):
    t = {_norm(x) for x in labels}
    for c, v in enumerate(row):
        if _norm(v) in t:
            return c
    return None


def _build(table, path=""):
    warnings = []
    dh = _find_row(table, ("site #", "site", "serial #", "serial"))
    if dh is None:
        raise ValueError("데이터 헤더 행(Serial #/Site #)을 찾지 못했습니다.")
    tn = _find_name_row(table, dh)
    if tn is None:
        warnings.append("'Test Name' 행을 찾지 못해 헤더 행 라벨을 항목명으로 사용합니다.")

    name_row = table[tn] if tn is not None else []
    header = table[dh]

    def meta_row(*labels):
        for lb in labels:
            t = _norm(lb)
            for i in range(dh - 1, -1, -1):
                if table[i] and _norm(table[i][0]) == t:
                    return table[i]
        return []

    tn_row = meta_row("Test Number")
    u_row = meta_row("Unit", "Units")
    lo_row = meta_row("Lower Limit")
    up_row = meta_row("Upper Limit")

    serial_col = _find_col(header, ("Serial #", "Serial", "Sample", "Sample No."))
    serial_col = 0 if serial_col is None else serial_col
    bin_col = _find_col(header, ("Bin",))
    site_col = _find_col(header, ("Site #", "Site"))
    meta_cols = {c for c, v in enumerate(header) if _norm(v) in _META_NAMES}
    first = max(meta_cols) + 1 if meta_cols else 0

    width = max(len(r) for r in table)
    data = [r if len(r) == width else r + [""] * (width - len(r)) for r in table[dh + 1:]]
    if not data:
        raise ValueError("데이터 행이 없습니다.")

    # --- DEVICE_ID 컬럼을 '이름'으로 찾는다 (위치는 파일마다 다를 수 있음) ---
    id_names = {_norm(n) for n in ID_ITEM_NAMES}
    id_cols = [c for c in range(first, width)
               if _norm(_text(name_row[c]) if c < len(name_row) else "") in id_names]
    id_col = id_cols[0] if id_cols else None
    if id_col is None:
        warnings.append(
            "DEVICE_ID 컬럼을 찾지 못했습니다. Pre↔Post 조인은 Serial # 로 폴백합니다.")

    samples = [_text(r[serial_col]) or str(i) for i, r in enumerate(data, 1)]
    # DEVICE_ID 는 숫자화하지 않고 문자열 원본을 보존한다 (앞자리 0 손실 방지)
    ids = [_text(r[id_col]) for r in data] if id_col is not None else [""] * len(data)
    bins = [_text(r[bin_col]) for r in data] if bin_col is not None else None
    sites = [_text(r[site_col]) for r in data] if site_col is not None else None

    if id_col is not None:
        blank = sum(1 for v in ids if not v)
        if blank:
            warnings.append(f"DEVICE_ID 가 비어 있는 행 {blank}건 — 해당 유닛은 Pre 매칭 제외")

    cols = list(zip(*data))
    at = lambda row, i: row[i] if i < len(row) else ""

    items = {}
    for c in range(first, width):
        if c in id_cols:
            continue                              # 식별자 컬럼은 분석 항목에서 제외
        name = _text(at(name_row, c)) or _text(at(header, c))
        if not name:
            continue
        vals, idx = _parse_column(cols[c])
        if not vals:
            continue
        key = name
        if key in items:                          # 동명 항목 보존 (원본은 덮어써서 유실)
            tnum = _text(at(tn_row, c))
            key = "%s [%s]" % (name, tnum or ("col%d" % c))
            warnings.append("항목명 중복: '%s' → '%s' 로 분리" % (name, key))
        items[key] = {
            "values": np.asarray(vals, dtype=np.float64),
            "rows": None if idx is None else np.asarray(idx, dtype=np.int32),
            "test_number": _text(at(tn_row, c)) or None,
            "unit": _text(at(u_row, c)) or None,
            "lower_limit": _to_float(at(lo_row, c)),
            "upper_limit": _to_float(at(up_row, c)),
            "column": c,
        }
    if not items:
        raise ValueError("숫자 Test Item 컬럼을 찾지 못했습니다.")
    return Dataset(items, samples, ids, bins, sites, path, warnings)


# ---------------------------------------------------------------- 디스크 캐시

def _cache_dir():
    d = os.environ.get("CDFTOOL_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cdf_compare_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _cache_path(path):
    st = os.stat(path)
    key = "%s|%d|%d|%d" % (os.path.abspath(path), st.st_mtime_ns, st.st_size, CACHE_VERSION)
    return os.path.join(_cache_dir(), hashlib.sha256(key.encode()).hexdigest() + ".npz")


def _cache_save(ds, cpath):
    names = list(ds.items)
    arrs, metas = {}, []
    for i, n in enumerate(names):
        d = ds.items[n]
        arrs["v%d" % i] = d["values"]
        if d["rows"] is not None:
            arrs["r%d" % i] = d["rows"]
        m = {k: d[k] for k in ("test_number", "unit", "lower_limit", "upper_limit", "column")}
        m["has_rows"] = d["rows"] is not None
        metas.append(m)
    blob = pickle.dumps({"names": names, "metas": metas, "samples": ds.samples,
                         "ids": ds.ids, "bins": ds.bins, "sites": ds.sites,
                         "warnings": ds.warnings}, protocol=4)
    tmp = cpath + ".tmp.npz"
    np.savez(tmp, meta=np.frombuffer(blob, dtype=np.uint8), **arrs)
    os.replace(tmp, cpath)


def _cache_load(cpath, path):
    with np.load(cpath, allow_pickle=False) as z:
        m = pickle.loads(z["meta"].tobytes())
        items = {}
        for i, n in enumerate(m["names"]):
            d = dict(m["metas"][i])
            d["values"] = z["v%d" % i]
            d["rows"] = z["r%d" % i] if d.pop("has_rows") else None
            items[n] = d
    return Dataset(items, m["samples"], m["ids"], m["bins"], m["sites"], path, m["warnings"])


def clear_disk_cache():
    d = _cache_dir()
    n = 0
    for f in os.listdir(d):
        if f.endswith(".npz"):
            try:
                os.remove(os.path.join(d, f))
                n += 1
            except OSError:
                pass
    return n


def read_datalog(path, use_cache=True):
    """CSV/XLSX → Dataset. (경로, mtime, size) 기준 디스크 캐시."""
    if use_cache:
        try:
            cp = _cache_path(path)
            if os.path.isfile(cp):
                return _cache_load(cp, path)
        except Exception:
            pass
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xlsm"):
        table = _read_xlsx(path)
    elif ext in (".csv", ".txt", ".tsv"):
        table = _read_csv(path)
    else:
        raise ValueError("지원하지 않는 형식입니다: %s" % ext)
    ds = _build(table, path)
    if use_cache:
        try:
            _cache_save(ds, _cache_path(path))
        except Exception:
            pass
    return ds


# ---------------------------------------------------------------- 조인

def _join(pre, post):
    """post 각 행 → pre 행 인덱스(없으면 -1). DEVICE_ID 우선, 없으면 Serial #."""
    if pre is None:
        return np.full(len(post.samples), -1, dtype=np.int32), "none"
    use_id = pre.has_ids() and post.has_ids()
    key = "device_id" if use_id else "sample"
    pre_pos = pre.key_index(prefer_id=use_id)     # 중복 시 마지막 등장 채택
    post_keys = post.key_list(prefer_id=use_id)
    src = np.array([pre_pos.get(k, -1) if k else -1 for k in post_keys], dtype=np.int32)
    return src, key


def match_summary(pre, post):
    """조용한 실패 방지용. payload 에 그대로 넣어 UI 에 노출할 것."""
    src, key = _join(pre, post)
    total = len(post.samples)
    matched = int((src >= 0).sum())
    return {"key": key, "post_units": total,
            "matched": matched, "unmatched": total - matched}


# ---------------------------------------------------------------- 분석

def _std(a, ddof=1):
    return float(a.std(ddof=ddof)) if a.size > ddof else None


def analyze(pre, post, flag_limit=FLAG_LIMIT, ddof=1, min_n=11):
    """전 항목 요약. details 는 만들지 않는다 (그래서 빠르다).

    ddof=0, min_n=0 으로 부르면 Rev.0.027 원본과 수치가 동일하다.
    """
    src, _key = _join(pre, post)
    rows = []
    for item, d in post.items.items():
        v = d["values"]
        n = int(v.size)
        if n == 0:
            continue
        idx = np.arange(n, dtype=np.int32) if d["rows"] is None else d["rows"]
        mu = float(v.mean())
        sd = _std(v, ddof)
        mea = None if not sd else (v - mu) / sd
        mea_max = float(np.abs(mea).max()) if mea is not None and mea.size else None

        diff_max = dm = dsd = None
        if pre is not None and item in pre.items:
            pv = pre.values_full(item)
            s = src[idx]
            pa = np.where(s >= 0, pv[np.clip(s, 0, None)], np.nan)
            with np.errstate(divide="ignore", invalid="ignore"):
                diff = np.where(np.abs(pa) > 0, v / pa - 1.0, np.nan)
            fin = diff[np.isfinite(diff)]
            if fin.size >= 2:
                dm = float(fin.mean())
                dsd = _std(fin, ddof)
                if dsd:
                    diff_max = float(np.abs((fin - dm) / dsd).max())

        if n < min_n:
            result = "INSUFFICIENT N"       # 소표본은 3σ 판정 불가 (max|z| ≤ √(n-1))
        elif sd is None:
            result = "NOT EVALUATED"        # σ 정의 불가
        elif (mea_max is not None and mea_max > flag_limit) or \
             (diff_max is not None and diff_max > flag_limit):
            result = "SELECT"
        else:
            result = "OK"

        rows.append({
            "item": item, "test_number": d["test_number"], "unit": d["unit"],
            "lower_limit": d["lower_limit"], "upper_limit": d["upper_limit"],
            "n": n, "mean": mu, "sigma": sd,
            "min": float(v.min()), "max": float(v.max()),
            "mea_s": mea_max, "diff_mean": dm, "diff_sigma": dsd, "diff_s": diff_max,
            "result": result,
        })
    return rows


def details_for(pre, post, item, flag_limit=FLAG_LIMIT, ddof=1):
    """선택된 **한 항목**의 샘플별 상세. SELECT 항목에만 호출할 것."""
    if item not in post.items:
        return []
    src, _key = _join(pre, post)
    v_full = post.values_full(item)
    if pre is not None and item in pre.items:
        p_full = pre.values_full(item)
        pa = np.where(src >= 0, p_full[np.clip(src, 0, None)], np.nan)
    else:
        pa = np.full(len(post.samples), np.nan)

    fin = v_full[np.isfinite(v_full)]
    mu = float(fin.mean()) if fin.size else None
    sd = _std(fin, ddof)
    with np.errstate(divide="ignore", invalid="ignore"):
        diff = np.where(np.abs(pa) > 0, v_full / pa - 1.0, np.nan)
    dfin = diff[np.isfinite(diff)]
    dm = float(dfin.mean()) if dfin.size else None
    dsd = _std(dfin, ddof)

    mea = (v_full - mu) / sd if sd else np.full_like(v_full, np.nan)
    dsig = (diff - dm) / dsd if dsd else np.full_like(diff, np.nan)

    f = lambda x: None if (x is None or not np.isfinite(x)) else float(x)
    out = []
    for i, s in enumerate(post.samples):
        m, g = f(mea[i]), f(dsig[i])
        flagged = (m is not None and abs(m) > flag_limit) or \
                  (g is not None and abs(g) > flag_limit)
        no_pre = src[i] < 0
        out.append({
            "sample": s,                              # 화면 표시는 Serial #
            "device_id": post.ids[i] if post.ids else "",
            "pre_value": f(pa[i]), "post_value": f(v_full[i]),
            "mea_s": m, "diff": f(diff[i]), "diff_s": g,
            "bin": post.bins[i] if post.bins else None,
            "site": post.sites[i] if post.sites else None,
            "result": "NO PRE SAMPLE" if no_pre else ("SELECT" if flagged else "OK"),
        })
    return out


def materialize_records(ds, items=None):
    """기존 record-dict 구조가 필요한 곳을 위한 어댑터.
    items 를 지정하지 않으면 전 항목을 만든다 — 대용량에서는 절대 그러지 말 것."""
    names = list(ds.items) if items is None else [i for i in items if i in ds.items]
    out = {}
    for name in names:
        d = ds.items[name]
        rows = range(d["values"].size) if d["rows"] is None else d["rows"]
        base = {k: d[k] for k in ("test_number", "unit", "lower_limit", "upper_limit")
                if d[k] is not None}
        recs = []
        for k, i in enumerate(rows):
            r = dict(base)
            r["sample"] = ds.samples[i]
            r["device_id"] = ds.ids[i] if ds.ids else ""
            r["value"] = float(d["values"][k])
            if ds.bins:
                r["bin"] = ds.bins[i]
            if ds.sites:
                r["site"] = ds.sites[i]
            recs.append(r)
        out[name] = recs
    return out
