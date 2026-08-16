# -*- coding: utf-8 -*-
"""전체 검증을 한 번에 돌리는 게이트.

    python _automation/run_checks.py                       # 단위 테스트만
    python _automation/run_checks.py --data-root "Test Data"  # 회귀 검증까지

종료 코드 0 이면 전부 통과. 1 이면 하나라도 실패.
커밋 전 / push 전 / CI 에서 이 한 줄만 부르면 된다.

CLAUDE.md §5-2: "모든 변경 후 회귀 테스트를 실행하고 PASS 를 확인한다."
그 확인을 사람이 기억해서 하는 대신 자동으로 만든다.
"""

import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUN_ONE = os.path.join(HERE, "_run_one.py")

UNIT_TESTS = [
    "tests/test_stats_core.py",
    "tests/test_grubbs_table.py",
    "tests/test_retest_history.py",
]


def run(label, args, timeout):
    """검사 하나를 실행하고 (통과여부, 소요초, 출력) 을 돌려준다."""
    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, RUN_ONE] + args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
        elapsed = time.time() - started
        output = proc.stdout.decode("utf-8", errors="replace")
        return proc.returncode == 0, elapsed, output
    except subprocess.TimeoutExpired:
        return False, time.time() - started, "시간 초과 ({}초)".format(timeout)


def main():
    parser = argparse.ArgumentParser(description="전체 검증 게이트")
    parser.add_argument(
        "--data-root",
        help="실제 시험 데이터 폴더. 지정하면 골든 회귀 검증까지 수행한다.",
    )
    parser.add_argument(
        "--golden", default="tests/golden/", help="골든 스냅샷 폴더 (기본: tests/golden/)"
    )
    parser.add_argument(
        "--timeout", type=int, default=1800, help="회귀 검증 제한시간(초), 기본 1800"
    )
    args = parser.parse_args()

    results = []

    print("=" * 62)
    print(" 단위 테스트")
    print("=" * 62)
    for test in UNIT_TESTS:
        ok, elapsed, output = run(test, [test], timeout=300)
        results.append((os.path.basename(test), ok, elapsed))
        print("  [{}] {:<28} {:>6.1f}s".format("PASS" if ok else "FAIL", os.path.basename(test), elapsed))
        if not ok:
            print("  " + "-" * 58)
            for line in output.strip().splitlines()[-15:]:
                print("    " + line)
            print("  " + "-" * 58)

    if args.data_root:
        print()
        print("=" * 62)
        print(" 골든 회귀 검증  (데이터: {})".format(args.data_root))
        print("=" * 62)
        ok, elapsed, output = run(
            "regression_check",
            ["tools/regression_check.py", "--data-root", args.data_root, "--golden", args.golden],
            timeout=args.timeout,
        )
        results.append(("regression_check", ok, elapsed))
        for line in output.strip().splitlines()[-25:]:
            print("  " + line)
        print("  [{}] {:>6.1f}s".format("PASS" if ok else "FAIL", elapsed))
    else:
        print()
        print("  (회귀 검증 건너뜀 — --data-root 를 주면 실행합니다)")

    print()
    print("=" * 62)
    failed = [name for name, ok, _ in results if not ok]
    total_time = sum(t for _, _, t in results)
    if failed:
        print(" 실패 {}건: {}".format(len(failed), ", ".join(failed)))
        print(" 총 {:.1f}초".format(total_time))
        print("=" * 62)
        return 1

    print(" 전부 통과 ({}건, {:.1f}초)".format(len(results), total_time))
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
