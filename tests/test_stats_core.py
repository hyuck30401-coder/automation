# -*- coding: utf-8 -*-
"""stats_core.py 단위 테스트 (통계개선_프롬프트.md §S1).

이 저장소에는 pytest 가 없다 — 이 스크립트는 표준 라이브러리만으로 돌아가는 독립
실행 파일이다.

Usage:
    python tests/test_stats_core.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))
sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

import stats_core as sc

FAILURES = []


def check(name, condition):
    if condition:
        print(f"  [PASS] {name}")
    else:
        print(f"  [FAIL] {name}")
        FAILURES.append(name)


def close(a, b, tol=1e-9):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


def test_mean_of():
    print("mean_of")
    check("빈 입력 -> 0.0", sc.mean_of([]) == 0.0)
    check("n=1 -> 그 값", sc.mean_of([5.0]) == 5.0)
    check("n=2 -> 산술평균", sc.mean_of([1.0, 2.0]) == 1.5)
    check("전부 동일값", sc.mean_of([7.0, 7.0, 7.0]) == 7.0)
    check("None 은 제외", sc.mean_of([1.0, None, 3.0]) == 2.0)
    check("nan 은 제외", sc.mean_of([1.0, float("nan"), 3.0]) == 2.0)
    check("inf 는 제외", sc.mean_of([1.0, float("inf"), 3.0]) == 2.0)
    check("전부 비유한 -> 0.0", sc.mean_of([float("nan"), float("inf")]) == 0.0)


def test_std_of():
    print("std_of")
    check("빈 입력 -> 0.0", sc.std_of([]) == 0.0)
    check("n=1 -> 0.0", sc.std_of([5.0]) == 0.0)
    check("전부 동일값(sigma=0)", sc.std_of([3.0, 3.0, 3.0]) == 0.0)
    check("n=2, ddof=0 (모표준편차)", close(sc.std_of([1.0, 2.0], ddof=0), 0.5))
    check("n=2, ddof=1 (표본표준편차, §S2 기본값)", close(sc.std_of([1.0, 2.0]), math.sqrt(0.5)))
    check("nan 포함 -> 제외 후 계산 (ddof=0)", close(sc.std_of([1.0, 2.0, float("nan")], ddof=0), 0.5))
    check("inf 포함 -> 제외 후 계산 (ddof=1)", close(sc.std_of([1.0, 2.0, float("inf")]), math.sqrt(0.5)))
    check("n=1, ddof=1(기본값) -> 0.0 (n<=ddof 가드)", sc.std_of([5.0]) == 0.0)
    check("n=1, ddof=0 -> 0.0 (값 하나는 편차 0)", sc.std_of([5.0], ddof=0) == 0.0)


def test_zscore():
    print("zscore")
    check("빈 입력 -> 빈 리스트", sc.zscore([], 0.0, 1.0) == [])
    check("일반 케이스", sc.zscore([5.0], 3.0, 2.0) == [1.0])
    check("None 은 자리 보존", sc.zscore([1.0, None, 3.0], 0.0, 1.0)[1] is None)
    check("nan 은 None 으로", sc.zscore([float("nan")], 0.0, 1.0) == [None])
    check("inf 는 None 으로", sc.zscore([float("inf")], 0.0, 1.0) == [None])
    check("spread=0, 유한값 -> 0.0", sc.zscore([5.0], 3.0, 0.0) == [0.0])
    check("spread=0, 비유한값 -> None", sc.zscore([float("nan")], 3.0, 0.0) == [None])
    check("길이 보존", len(sc.zscore([1.0, None, float("nan"), 4.0], 0.0, 1.0)) == 4)


def test_max_abs_z():
    print("max_abs_z")
    check("빈 입력 -> 0.0", sc.max_abs_z([], 0.0, 1.0) == 0.0)
    check("최댓값 절댓값 선택", sc.max_abs_z([1.0, -5.0, 2.0], 0.0, 1.0) == 5.0)
    check("None/nan 은 후보에서 제외", sc.max_abs_z([1.0, None, float("nan")], 0.0, 1.0) == 1.0)
    check("spread=0 -> 0.0", sc.max_abs_z([1.0, 2.0], 5.0, 0.0) == 0.0)


def test_diff_ratio():
    print("diff_ratio")
    check("일반 케이스", close(sc.diff_ratio(2.0, 3.0), 0.5))
    check("pre 음수, 부호는 이동 방향", close(sc.diff_ratio(-2.0, -1.0), 0.5))
    check("pre=0 -> None", sc.diff_ratio(0.0, 1.0) is None)
    check("pre=None -> None", sc.diff_ratio(None, 1.0) is None)
    check("post=None -> None", sc.diff_ratio(1.0, None) is None)
    check("pre=nan -> None", sc.diff_ratio(float("nan"), 1.0) is None)
    check("post=inf -> None", sc.diff_ratio(1.0, float("inf")) is None)


def test_flag_result():
    print("flag_result")
    check("둘 다 임계 이하 -> False", sc.flag_result(1.0, 1.0, 3.0) is False)
    check("mea_s 초과 -> True", sc.flag_result(3.1, 0.0, 3.0) is True)
    check("diff_s 초과 -> True", sc.flag_result(0.0, 3.1, 3.0) is True)
    check("둘 다 초과 -> True", sc.flag_result(5.0, 5.0, 3.0) is True)
    check("경계값(==limit)은 초과 아님", sc.flag_result(3.0, 3.0, 3.0) is False)
    check("None 은 그 항목만 무시", sc.flag_result(None, 3.1, 3.0) is True)
    check("둘 다 None -> False", sc.flag_result(None, None, 3.0) is False)


def test_numpy_vs_no_numpy():
    print("numpy 유무 동등성 (monkeypatch np=None)")
    real_np = sc.np
    try:
        vectors = [
            [],
            [5.0],
            [1.0, 2.0],
            [3.0, 3.0, 3.0],
            [1.0, None, 3.0, float("nan"), float("inf"), -2.5],
        ]
        for values in vectors:
            sc.np = real_np
            with_np_mean = sc.mean_of(values)
            with_np_std0 = sc.std_of(values, ddof=0)
            with_np_std1 = sc.std_of(values, ddof=1)
            with_np_z = sc.zscore(values, 1.0, 2.0)
            with_np_maxz = sc.max_abs_z(values, 1.0, 2.0)

            sc.np = None
            without_np_mean = sc.mean_of(values)
            without_np_std0 = sc.std_of(values, ddof=0)
            without_np_std1 = sc.std_of(values, ddof=1)
            without_np_z = sc.zscore(values, 1.0, 2.0)
            without_np_maxz = sc.max_abs_z(values, 1.0, 2.0)

            check(f"mean_of 동일 ({values})", close(with_np_mean, without_np_mean))
            check(f"std_of(ddof=0) 동일 ({values})", close(with_np_std0, without_np_std0))
            check(f"std_of(ddof=1) 동일 ({values})", close(with_np_std1, without_np_std1))
            check(
                f"zscore 동일 ({values})",
                len(with_np_z) == len(without_np_z)
                and all(close(a, b) for a, b in zip(with_np_z, without_np_z)),
            )
            check(f"max_abs_z 동일 ({values})", close(with_np_maxz, without_np_maxz))
    finally:
        sc.np = real_np


def main():
    test_mean_of()
    test_std_of()
    test_zscore()
    test_max_abs_z()
    test_diff_ratio()
    test_flag_result()
    test_numpy_vs_no_numpy()

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}개 실패 - {FAILURES}")
        sys.exit(1)
    print("PASS: 전부 통과")
    sys.exit(0)


if __name__ == "__main__":
    main()
