# -*- coding: utf-8 -*-
"""웨이퍼 다이 맵(R-056) 시험용 데이터를 만든다.

원본 Pre/Post 파일을 한 글자도 고치지 않고, 맨 끝에 다이 정보 3개 항목을 덧붙인
사본을 새 폴더로 낸다. 값은 실제 OTP 처럼 **2진수 문자열(앞자리 0 제거)** 이다.

  · 배정 키는 DEVICE_ID — 같은 칩이면 Pre/Post/모든 시험 파일에서 좌표가 같다.
    Serial # 는 파일마다 다시 매겨질 수 있어 키로 쓸 수 없다.
  · 좌표는 유효다이 맵의 1 자리에서만 뽑고, 같은 웨이퍼 안에서 중복되지 않는다.
  · 일부러 일부는 0 / 0xFF 로 둬서 "좌표 없음" 처리 경로도 확인되게 한다.
  · 난수는 고정 시드라 다시 돌려도 같은 파일이 나온다.

    python tools/make_wafer_testdata.py
"""
import io
import os
import random

SRC_DIR = os.path.join("Test Data", "SM3502Q", "01_MVT1-3_1111_111")
OUT_DIR = os.path.join("Test Data", "SM3502Q", "02_MVT1-3_1111_WMAP")
DIE_MAP = os.path.join("docs", "wafer_map", "SAMPLE_wafer_map_A_space.txt")
ENCODING = "cp949"
NEWLINE = "\r\n"
SEED = 20260927

WAFERS = [3, 11, 19]
ORIGIN_BASE = 11
BAD_RATIO = 0.03                     # 미기입·판독실패로 둘 비율
BAD_VALUES = [0, 255]                # 0 과 0xFF

COLUMNS = [
    ("TEST_OTP_WAFER_NO", "99.1"),
    ("TEST_OTP_DIE_X", "99.2"),
    ("TEST_OTP_DIE_Y", "99.3"),
]
UNIT = "Binnary"
LOWER, UPPER = "0", "11111111"
HEAD_ROWS = ("test name", "test number", "lower limit", "upper limit", "units", "unit")


def to_binary(value):
    """실제 datalog 와 같은 표기 — 2진수 문자열, 앞자리 0 없음."""
    return format(int(value), "b")


def load_die_coords():
    """유효다이 맵에서 (X, Y) 목록을 만든다 (R-056 규칙 그대로)."""
    grid = []
    with io.open(DIE_MAP, encoding="utf-8-sig") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            cells = stripped.split() if " " in stripped else list(stripped)
            grid.append([1 if c.strip() == "1" else 0 for c in cells if c.strip()])
    ones = [(r, c) for r, row in enumerate(grid) for c, v in enumerate(row) if v]
    base_row = min(r for r, _c in ones)
    base_col = min(c for _r, c in ones)
    return [(ORIGIN_BASE + c - base_col, ORIGIN_BASE + r - base_row) for r, c in ones]


def split_line(line):
    return line.split(",")


def header_index(lines):
    """항목 헤더 5줄과 데이터 시작 행을 찾는다.

    'Test Name' 은 파일 위쪽 메타에도 한 번 나오므로, Site # 행 바로 위의
    넓은(항목이 실린) 블록을 쓴다.
    """
    site = None
    for i, line in enumerate(lines):
        if split_line(line)[0].strip().lower() in ("site #", "site"):
            site = i
            break
    if site is None:
        raise ValueError("Site # 행을 찾지 못했습니다.")
    heads = {}
    for i in range(max(0, site - 8), site):
        name = split_line(lines[i])[0].strip().lower()
        if name in HEAD_ROWS and len(split_line(lines[i])) > 10:
            heads["unit" if name == "units" else name] = i
    for need in ("test name", "test number", "lower limit", "upper limit", "unit"):
        if need not in heads:
            raise ValueError("항목 헤더 '%s' 를 찾지 못했습니다." % need)
    return heads, site


def collect_device_ids(paths):
    ids = []
    seen = set()
    for path in paths:
        lines = io.open(path, "rb").read().decode(ENCODING, "replace").split(NEWLINE)
        heads, site = header_index(lines)
        names = split_line(lines[heads["test name"]])
        try:
            col = next(i for i, v in enumerate(names) if v.strip().upper() == "DEVICE_ID")
        except StopIteration:
            raise ValueError("%s 에 DEVICE_ID 항목이 없습니다." % os.path.basename(path))
        for line in lines[site + 1:]:
            if not line.strip():
                continue
            fields = split_line(line)
            if col >= len(fields):
                continue
            value = fields[col].strip()
            if value and value not in seen:
                seen.add(value)
                ids.append(value)
    return ids


def assign(device_ids):
    """DEVICE_ID -> (wafer, x, y). 좌표가 없어야 할 유닛은 값에 None 대신 0/255 를 넣는다."""
    rng = random.Random(SEED)
    coords = load_die_coords()
    pools = {}
    for wafer in WAFERS:
        pool = coords[:]
        rng.shuffle(pool)
        pools[wafer] = pool
    table = {}
    for index, device_id in enumerate(sorted(device_ids)):
        wafer = WAFERS[index % len(WAFERS)]
        if rng.random() < BAD_RATIO:
            bad = rng.choice(BAD_VALUES)
            table[device_id] = (wafer, bad, bad)
            continue
        if not pools[wafer]:
            raise ValueError("웨이퍼 %d 의 유효다이가 모자랍니다." % wafer)
        x, y = pools[wafer].pop()
        table[device_id] = (wafer, x, y)
    return table


def convert(path, out_path, table):
    lines = io.open(path, "rb").read().decode(ENCODING, "replace").split(NEWLINE)
    heads, site = header_index(lines)
    names = split_line(lines[heads["test name"]])
    # 항목 헤더 끝의 빈 칸을 떼어내 진짜 열 수를 구한다. 이 폭에 데이터 행을 맞춰야
    # 새 항목의 이름과 값이 같은 열에 놓인다 (Pre 병합본은 이 둘이 1칸 어긋나 있다).
    width = len(names)
    while width > 0 and not names[width - 1].strip():
        width -= 1
    device_col = next(i for i, v in enumerate(names) if v.strip().upper() == "DEVICE_ID")

    def fit(line, extra):
        fields = split_line(line)
        fields = (fields + [""] * width)[:width]
        return ",".join(fields + extra)

    out = list(lines)
    out[heads["test name"]] = fit(lines[heads["test name"]], [c[0] for c in COLUMNS])
    out[heads["test number"]] = fit(lines[heads["test number"]], [c[1] for c in COLUMNS])
    out[heads["lower limit"]] = fit(lines[heads["lower limit"]], [LOWER] * 3)
    out[heads["upper limit"]] = fit(lines[heads["upper limit"]], [UPPER] * 3)
    out[heads["unit"]] = fit(lines[heads["unit"]], [UNIT] * 3)

    filled = blank = 0
    for i in range(site + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        fields = split_line(line)
        device_id = fields[device_col].strip() if device_col < len(fields) else ""
        entry = table.get(device_id)
        if entry is None:
            out[i] = fit(line, ["", "", ""])      # DEVICE_ID 가 빈 행 — 좌표 없음
            blank += 1
        else:
            out[i] = fit(line, [to_binary(v) for v in entry])
            filled += 1
    folder = os.path.dirname(out_path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    io.open(out_path, "wb").write(NEWLINE.join(out).encode(ENCODING, "replace"))
    return filled, blank


def main():
    paths = []
    for sub in ("00_Pre", "01_Post"):
        folder = os.path.join(SRC_DIR, sub)
        for name in sorted(os.listdir(folder)):
            paths.append(os.path.join(folder, name))
    device_ids = collect_device_ids(paths)
    table = assign(device_ids)
    bad = sum(1 for v in table.values() if v[1] in BAD_VALUES and v[1] == v[2])
    print("유닛(DEVICE_ID) %d개 · 웨이퍼 %s · 좌표 없음으로 둔 유닛 %d개"
          % (len(table), WAFERS, bad))
    per_wafer = {}
    for wafer, _x, _y in table.values():
        per_wafer[wafer] = per_wafer.get(wafer, 0) + 1
    print("웨이퍼별 유닛:", dict(sorted(per_wafer.items())))
    print()
    for path in paths:
        rel = os.path.relpath(path, SRC_DIR)
        out_path = os.path.join(OUT_DIR, rel)
        filled, blank = convert(path, out_path, table)
        print("  %-58s 행 %5d (좌표 %5d · 없음 %3d)"
              % (os.path.basename(path)[:58], filled + blank, filled, blank))
    print("\n->", OUT_DIR)


if __name__ == "__main__":
    main()
