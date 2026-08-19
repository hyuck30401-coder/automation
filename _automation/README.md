# _automation/

기존 파일은 **한 글자도 건드리지 않는다**는 제약 아래 만든 자동화 계층이다.
여기 있는 것들은 전부 기존 코드를 바깥에서 감싸기만 한다.

## 왜 만들었나

CLAUDE.md §5-2 는 "모든 변경 후 회귀 테스트를 실행하고 PASS 를 확인한다"고
요구한다. 그런데 그 확인을 사람이 매번 기억해서 해야 했다. 이 폴더는 그
확인을 명령 한 줄로 만들고, 나아가 자동 실행이 가능한 형태로 바꾼다.

## 파일

| 파일 | 역할 |
|---|---|
| `headless.py` | 화면 없는 환경에서 분석 모듈을 import 할 수 있게 하는 tkinter 스텁 |
| `_run_one.py` | 스크립트 하나를 헤드리스로 실행하는 부트스트랩 |
| `run_checks.py` | **주 진입점.** 단위 테스트 + 골든 회귀 검증을 한 번에 |
| `ci.yml.draft` | GitHub Actions 워크플로 초안 (원격 저장소 결정 전까지 초안) |
| `pre-push.sample` | push 전 자동 검증 훅 초안 |

## 사용법

```bash
# 단위 테스트만 (빠름, 약 17초)
python _automation/run_checks.py

# 회귀 검증까지 (전체 게이트, 캐시 웜 기준 약 23초)
python _automation/run_checks.py --data-root "Test Data"
```

종료 코드 0 = 전부 통과, 1 = 하나라도 실패. 그래서 훅이나 CI 에 그대로 꽂힌다.

## headless.py 가 푸는 문제

`cdf_compare_tool.py` 4번 줄이 모듈 최상단에서 `import tkinter` 를 한다.
정작 tkinter 가 처음 쓰이는 곳은 438번 줄 `class CdfCompareApp(tk.Tk)` 이고,
CLAUDE.md §2 에 적힌 대로 그 GUI 클래스는 웹 빌드에서 도달 불가능한 죽은
코드다.

결과적으로 tkinter 가 없는 환경에서는 분석 함수를 부르기도 전에 ImportError
로 죽는다. 실제로 이 저장소에서 `tests/test_retest_history.py` 와
`tools/regression_check.py` 두 개가 그래서 실행 불가 상태였다.

`headless.py` 는 sys.modules 에 가짜 tkinter 를 미리 꽂아 그 벽을 넘는다.
**진짜 tkinter 가 설치되어 있으면 아무것도 하지 않으므로**, 개발 PC 에서의
동작은 전혀 달라지지 않는다.

> 근본 해결은 `cdf_compare_tool.py` 의 tkinter import 를 지연시키는 것이지만,
> 그건 기존 파일 수정이라 여기서는 하지 않았다. 판정 로직과 무관한 4줄짜리
> 변경이고, 이 폴더의 게이트로 안전하게 검증할 수 있다.

## 검증 기록

2026-08-12, 작업트리 상태(`ui/layout-v2` 브랜치, `cdf_compare_web.py` 수정본
포함)에서 실제 `Test Data` 로 제자리 실행:

```
[PASS] test_stats_core.py         0.2s
[PASS] test_grubbs_table.py      16.7s
[PASS] test_retest_history.py     0.3s     <- 종전 실행 불가였던 항목
[PASS] regression_check           5.4s
Combos: 2 total, 2 passed, 0 with mismatches, 0 could not be reproduced
전부 통과 (4건, 22.6초)
```

데이터를 임시 폴더로 복사하지 않고 원본 경로에서 그대로 돌렸다
(CLAUDE.md §5-4 준수).

## 아직 결정이 필요한 것

1. **원격 저장소** — 현재 `git remote` 가 없다. GitHub private repo 를 만들면
   `ci.yml.draft` 를 `.github/workflows/ci.yml` 로 옮겨 exe 자동 빌드가 된다.
   사내 보안상 불가하면 로컬 훅 기반으로만 간다.
2. **PyInstaller 명령** — CLAUDE.md §8 이 여전히 TODO 다. 실제 빌드 명령을
   모르면 exe 자동 빌드를 완성할 수 없다.
3. **exe 버전 불일치** — `_release/CDFCompareToolHTML_Rev0.027.exe` 는
   7월 15일자인데 소스는 `Rev.0.028` 이다.
