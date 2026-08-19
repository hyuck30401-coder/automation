# -*- coding: utf-8 -*-
"""스크립트 하나를 헤드리스 환경에서 실행하는 부트스트랩.

각 검사를 별도 프로세스로 띄워서 서로 상태가 섞이지 않게 한다.

    python _automation/_run_one.py tests/test_stats_core.py
    python _automation/_run_one.py tools/regression_check.py --data-root "Test Data" --golden tests/golden/
"""

import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# 프로젝트 루트와 _automation 을 import 경로에 올린다
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import headless  # noqa: E402  - sys.modules 에 tkinter 스텁을 심는다 (import 부작용)

if len(sys.argv) < 2:
    print("사용법: python _automation/_run_one.py <스크립트> [인자...]", file=sys.stderr)
    raise SystemExit(2)

target = sys.argv[1]
if not os.path.isabs(target):
    target = os.path.join(ROOT, target)

if not os.path.exists(target):
    print("대상 스크립트를 찾을 수 없습니다: {}".format(target), file=sys.stderr)
    raise SystemExit(2)

# 대상 스크립트의 폴더도 경로에 올린다.
# `python tools/regression_check.py` 로 직접 실행하면 파이썬이 tools/ 를 자동으로
# sys.path 에 넣어주지만, runpy 로 부를 때는 그게 없어서 형제 모듈
# (_regression_lib 등) import 가 실패한다.
target_dir = os.path.dirname(target)
if target_dir and target_dir not in sys.path:
    sys.path.insert(0, target_dir)

# 대상 스크립트가 자기 argv 를 그대로 보도록 재구성
sys.argv = [target] + sys.argv[2:]

os.chdir(ROOT)  # 상대경로(예: "Test Data")가 프로젝트 루트 기준이 되도록

try:
    runpy.run_path(target, run_name="__main__")
except SystemExit as exc:
    raise SystemExit(exc.code if exc.code is not None else 0)
