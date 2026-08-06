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
    check("빈 입력 -> None(§S5, 정의 불가)", sc.mean_of([]) is None)
    check("n=1 -> 그 값", sc.mean_of([5.0]) == 5.0)
    check("n=2 -> 산술평균", sc.mean_of([1.0, 2.0]) == 1.5)
    check("전부 동일값", sc.mean_of([7.0, 7.0, 7.0]) == 7.0)
    check("None 은 제외", sc.mean_of([1.0, None, 3.0]) == 2.0)
    check("nan 은 제외", sc.mean_of([1.0, float("nan"), 3.0]) == 2.0)
    check("inf 는 제외", sc.mean_of([1.0, float("inf"), 3.0]) == 2.0)
    check("전부 비유한 -> None(§S5, 정의 불가)", sc.mean_of([float("nan"), float("inf")]) is None)


def test_std_of():
    print("std_of")
    check("빈 입력 -> None(§S5, 정의 불가)", sc.std_of([]) is None)
    check("n=1 -> None(§S5, 정의 불가, ddof=1 기본값)", sc.std_of([5.0]) is None)
    check("전부 동일값(sigma=0)", sc.std_of([3.0, 3.0, 3.0]) == 0.0)
    check("n=2, ddof=0 (모표준편차)", close(sc.std_of([1.0, 2.0], ddof=0), 0.5))
    check("n=2, ddof=1 (표본표준편차, §S2 기본값)", close(sc.std_of([1.0, 2.0]), math.sqrt(0.5)))
    check("nan 포함 -> 제외 후 계산 (ddof=0)", close(sc.std_of([1.0, 2.0, float("nan")], ddof=0), 0.5))
    check("inf 포함 -> 제외 후 계산 (ddof=1)", close(sc.std_of([1.0, 2.0, float("inf")]), math.sqrt(0.5)))
    check("n=1, ddof=1(기본값) -> None(§S5, n<=ddof 가드는 정의 불가)", sc.std_of([5.0]) is None)
    check("n=1, ddof=0 -> 0.0 (값 하나는 편차 0, 진짜 계산됨)", sc.std_of([5.0], ddof=0) == 0.0)


def test_zscore():
    print("zscore")
    check("빈 입력 -> 빈 리스트", sc.zscore([], 0.0, 1.0) == [])
    check("일반 케이스", sc.zscore([5.0], 3.0, 2.0) == [1.0])
    check("None 은 자리 보존", sc.zscore([1.0, None, 3.0], 0.0, 1.0)[1] is None)
    check("nan 은 None 으로", sc.zscore([float("nan")], 0.0, 1.0) == [None])
    check("inf 는 None 으로", sc.zscore([float("inf")], 0.0, 1.0) == [None])
    check("spread=0, 유한값 -> None(§S5, 0/0 은 정의 불가)", sc.zscore([5.0], 3.0, 0.0) == [None])
    check("spread=0, 비유한값 -> None", sc.zscore([float("nan")], 3.0, 0.0) == [None])
    check("center=None -> 전부 None", sc.zscore([1.0, 2.0], None, 1.0) == [None, None])
    check("spread=None -> 전부 None", sc.zscore([1.0, 2.0], 0.0, None) == [None, None])
    check("길이 보존", len(sc.zscore([1.0, None, float("nan"), 4.0], 0.0, 1.0)) == 4)


def test_max_abs_z():
    print("max_abs_z")
    check("빈 입력 -> None(§S5, 정의 불가)", sc.max_abs_z([], 0.0, 1.0) is None)
    check("최댓값 절댓값 선택", sc.max_abs_z([1.0, -5.0, 2.0], 0.0, 1.0) == 5.0)
    check("None/nan 은 후보에서 제외", sc.max_abs_z([1.0, None, float("nan")], 0.0, 1.0) == 1.0)
    check("spread=0 -> None(§S5, 전 표본이 zscore 정의 불가)", sc.max_abs_z([1.0, 2.0], 5.0, 0.0) is None)
    check("전부 spread=0 이 아닌 개별 None 후보만 있을 때도 정의 불가 -> None", sc.max_abs_z([float("nan")], 0.0, 1.0) is None)


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
    """§S3: flag_result 는 이제 bool 이 아니라
    "SELECT"/"OK"/"INSUFFICIENT N"/"NOT EVALUATED" 문자열을 반환한다."""
    print("flag_result")
    # mode="fixed": §S2 이전(고정 3.0 임계)과 완전히 동일해야 한다 -- fixed_limit 만 비교,
    # n/sigma/mean 은 무시.
    check("fixed: 둘 다 임계 이하 -> OK", sc.flag_result(1.0, 1.0, 57, mode="fixed") == "OK")
    check("fixed: mea_s 초과 -> SELECT", sc.flag_result(3.1, 0.0, 57, mode="fixed") == "SELECT")
    check("fixed: diff_s 초과 -> SELECT", sc.flag_result(0.0, 3.1, 57, mode="fixed") == "SELECT")
    check("fixed: 둘 다 초과 -> SELECT", sc.flag_result(5.0, 5.0, 57, mode="fixed") == "SELECT")
    check("fixed: 경계값(==limit)은 초과 아님", sc.flag_result(3.0, 3.0, 57, mode="fixed") == "OK")
    check("fixed: None 은 그 항목만 무시 -> SELECT", sc.flag_result(None, 3.1, 57, mode="fixed") == "SELECT")
    check("fixed: 둘 다 None -> OK", sc.flag_result(None, None, 57, mode="fixed") == "OK")
    check("fixed: n/sigma/mean 은 무시된다", sc.flag_result(3.1, 0.0, 2, sigma=0.0, mean=0.0, mode="fixed") == "SELECT")

    # mode="grubbs": n=57, alpha=0.05 -> grubbs_critical=3.1799... (grubbs_table.py 로 검증됨)
    g57 = sc.threshold_for(57, mode="grubbs")
    check("grubbs: n=57 임계값이 fixed 3.0 보다 크다", g57 > 3.0)
    check("grubbs: 임계 이하 -> OK", sc.flag_result(g57 - 0.01, 0.0, 57, sigma=1.0, mean=0.0, mode="grubbs") == "OK")
    check("grubbs: 임계 초과 -> SELECT", sc.flag_result(g57 + 0.01, 0.0, 57, sigma=1.0, mean=0.0, mode="grubbs") == "SELECT")

    # n<3 -> INSUFFICIENT N (Grubbs 는 n>=3 이어야 정의된다)
    check(
        "grubbs: n<3 -> INSUFFICIENT N",
        sc.flag_result(5.0, None, 2, sigma=1.0, mean=0.0, mode="grubbs") == "INSUFFICIENT N",
    )
    check(
        "grubbs: diff 만 n<3 이어도 INSUFFICIENT N 이 mea 의 OK 를 덮는다 (우선순위)",
        sc.flag_result(
            1.0, 5.0, 57, sigma=1.0, mean=0.0,
            diff_n=2, diff_sigma=1.0, diff_mean=0.0, mode="grubbs",
        ) == "INSUFFICIENT N",
    )

    # sigma≈0(상대 기준) -> NOT EVALUATED. BUCK_SS 처럼 z 가 폭발해도 판정 불가로 분류돼야 한다.
    check(
        "grubbs: sigma≈0(상대) -> NOT EVALUATED",
        sc.flag_result(1e20, None, 57, sigma=1e-20, mean=1.0, mode="grubbs") == "NOT EVALUATED",
    )
    check(
        "grubbs: SELECT 는 NOT EVALUATED 보다 우선순위가 높다",
        sc.flag_result(
            1e20, 5.0, 57, sigma=1e-20, mean=1.0,
            diff_n=57, diff_sigma=1.0, diff_mean=0.0, mode="grubbs",
        ) == "SELECT",
    )

    # §S5: sigma 가 None(std_of 정의 불가)일 때도, z 값과 무관하게 sigma 체크가 z=None
    # 체크보다 먼저 이뤄져 NOT EVALUATED 로 떨어져야 한다 (OK 로 새는 회귀 방지).
    check(
        "grubbs: sigma=None, z 는 유한값이어도 -> NOT EVALUATED (sigma 체크가 z 체크보다 우선)",
        sc.flag_result(5.0, None, 57, sigma=None, mean=1.0, mode="grubbs") == "NOT EVALUATED",
    )
    check(
        "grubbs: sigma=None, z=None (실제 zscore(spread=None) 결과) -> NOT EVALUATED, OK 로 새지 않는다",
        sc.flag_result(None, None, 57, sigma=None, mean=None, mode="grubbs") == "NOT EVALUATED",
    )
    # §S5 통합: std_of(n=1)->None, zscore(값, mean, None)->[None] 이 실제로 이어져도
    # flag_result 최종 결과가 NOT EVALUATED 이지 OK 로 새지 않는지 확인.
    _s5_values = [5.0]
    _s5_mean = sc.mean_of(_s5_values)
    _s5_sigma = sc.std_of(_s5_values)
    _s5_z = sc.zscore(_s5_values, _s5_mean, _s5_sigma)[0]
    check("§S5 통합: std_of(n=1) -> None", _s5_sigma is None)
    check("§S5 통합: zscore(값, mean, sigma=None) -> None", _s5_z is None)
    check(
        "§S5 통합: flag_result(위 z/sigma, mode=grubbs) -> NOT EVALUATED (OK 로 새지 않는다)",
        sc.flag_result(_s5_z, None, 1, sigma=_s5_sigma, mean=_s5_mean, mode="grubbs") == "NOT EVALUATED",
    )

    # grubbs 모드는 ddof=1(표본표준편차) 전제 -- ddof=0 은 명시적으로 거부한다.
    try:
        sc.flag_result(1.0, 1.0, 57, ddof=0, mode="grubbs")
        check("grubbs: ddof=0 은 ValueError", False)
    except ValueError:
        check("grubbs: ddof=0 은 ValueError", True)


def test_threshold_for():
    print("threshold_for")
    check("fixed 모드 -> FLAG_LIMIT(3.0)", sc.threshold_for(57, mode="fixed") == 3.0)
    check("grubbs 모드, n=57 -> fixed 3.0 보다 크다", sc.threshold_for(57, mode="grubbs") > 3.0)
    check("grubbs 모드, n<3 -> None", sc.threshold_for(2, mode="grubbs") is None)
    check(
        "grubbs 모드, n 이 클수록 임계값도 커진다 (n=3000 > n=57)",
        sc.threshold_for(3000, mode="grubbs") > sc.threshold_for(57, mode="grubbs"),
    )


def test_sigma_is_negligible():
    print("sigma_is_negligible")
    check("sigma=None -> False (판정 보류, 정상 취급 아님)", sc.sigma_is_negligible(None, 1.0) is False)
    check("sigma=nan -> True", sc.sigma_is_negligible(float("nan"), 1.0) is True)
    check("mean=0, sigma=0 -> True (절대 하한)", sc.sigma_is_negligible(0.0, 0.0) is True)
    check("mean=1.0, sigma<=|mean|*1e-12 -> True", sc.sigma_is_negligible(1e-13, 1.0) is True)
    check("mean=1.0, sigma>|mean|*1e-12 -> False", sc.sigma_is_negligible(1e-11, 1.0) is False)
    check("정상적인 sigma(BUCK_SS 실측값 규모) -> False", sc.sigma_is_negligible(0.074, 2.77) is False)


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
    test_threshold_for()
    test_sigma_is_negligible()
    test_numpy_vs_no_numpy()

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)}개 실패 - {FAILURES}")
        sys.exit(1)
    print("PASS: 전부 통과")
    sys.exit(0)


if __name__ == "__main__":
    main()
