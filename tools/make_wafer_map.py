# -*- coding: utf-8 -*-
"""유효다이 맵 TXT 견본을 만든다 (R-056 개발용).

실제 맵 파일을 받기 전에 파서와 화면을 붙여보려고 만든 대역이다. 규칙은 Eden 님이
정리해 주신 그대로 —
  · 1 = 유효다이, 0 = 좌표 격자를 채우기 위한 자리
  · 1 이 있는 가장 왼쪽 열 -> X = 11, 1 이 있는 가장 위쪽 행 -> Y = 11
  · 오른쪽으로 갈수록 X +1, 아래로 갈수록 Y +1
원점 칸이 0 이어도 되는 경우(웨이퍼가 둥글어 거의 항상 그렇다)와, 격자 가장자리에
0 패딩이 있는 경우를 둘 다 일부러 만들어 둔다 — 그래야 바운딩 박스 기준이 맞는지
검증할 수 있다.

    python tools/make_wafer_map.py
"""
import io
import os

OUT_DIR = os.path.join("docs", "wafer_map")

# 다이 격자 (패딩 제외). 다이가 가로로 길다고 보고 행을 더 적게 잡았다.
COLS, ROWS = 40, 34
# 웨이퍼 원 (다이 단위). 가장자리 제외(edge exclusion)까지 반영한 유효 반지름.
CX, CY = (COLS - 1) / 2.0, (ROWS - 1) / 2.0
RX, RY = COLS / 2.0 - 0.6, ROWS / 2.0 - 0.6
# 0 패딩 — 좌/우/상/하를 일부러 다르게 둬서 "격자 좌상단 != (11,11)" 을 시험한다.
PAD_L, PAD_R, PAD_T, PAD_B = 4, 2, 3, 2


def build_grid():
    grid = []
    for row in range(ROWS):
        line = []
        for col in range(COLS):
            # 다이 네 귀퉁이가 모두 원 안에 들어와야 유효다이로 친다.
            inside = all(
                ((col + dx - CX) / RX) ** 2 + ((row + dy - CY) / RY) ** 2 <= 1.0
                for dx in (-0.5, 0.5) for dy in (-0.5, 0.5)
            )
            line.append(1 if inside else 0)
        grid.append(line)

    width = COLS + PAD_L + PAD_R
    out = [[0] * width for _ in range(PAD_T)]
    for line in grid:
        out.append([0] * PAD_L + line + [0] * PAD_R)
    out += [[0] * width for _ in range(PAD_B)]
    return out


def coords(grid):
    """규칙대로 좌표를 뽑는다. (기준열, 기준행, {(x, y): (행, 열)})"""
    ones = [(r, c) for r, line in enumerate(grid) for c, v in enumerate(line) if v]
    base_col = min(c for _r, c in ones)
    base_row = min(r for r, _c in ones)
    table = {}
    for r, c in ones:
        table[(11 + c - base_col, 11 + r - base_row)] = (r, c)
    return base_col, base_row, table


def write(path, grid, sep):
    with io.open(path, "w", encoding="utf-8", newline="\r\n") as fh:
        for line in grid:
            fh.write(sep.join(str(v) for v in line) + "\n")


def main():
    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)
    grid = build_grid()
    write(os.path.join(OUT_DIR, "SAMPLE_wafer_map_A_space.txt"), grid, " ")
    write(os.path.join(OUT_DIR, "SAMPLE_wafer_map_B_compact.txt"), grid, "")

    base_col, base_row, table = coords(grid)
    xs = [x for x, _y in table]
    ys = [y for _x, y in table]
    print("격자        : %d행 x %d열 (0 패딩 포함)" % (len(grid), len(grid[0])))
    print("유효다이    : %d개" % len(table))
    print("기준 칸     : 행 %d · 열 %d  -> 이 자리가 (11, 11)" % (base_row, base_col))
    print("             그 칸의 값 = %d  (0 이면 '원점은 유효다이가 아니어도 된다' 사례)"
          % grid[base_row][base_col])
    print("X 범위      : %d ~ %d" % (min(xs), max(xs)))
    print("Y 범위      : %d ~ %d" % (min(ys), max(ys)))
    print("1바이트 한계: X,Y 모두 255 이하여야 함 -> %s"
          % ("OK" if max(max(xs), max(ys)) <= 255 else "**초과**"))
    print()
    print("미리보기 (■ = 유효다이, · = 0)")
    for r, line in enumerate(grid):
        print("   " + "".join("■" if v else "·" for v in line))


if __name__ == "__main__":
    main()
