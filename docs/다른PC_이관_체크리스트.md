# 다른 PC 에서 이어서 작업하기 — 체크리스트

이 repo 는 **코드와 문서만** 담는다. 사내 시험 데이터와 사람마다 다른 설정은
`.gitignore` 로 빠져 있으므로, 새 PC 에서는 아래를 따로 채워야 한다.

마지막 갱신: 2026-10-15 (R-060 · R-057 반영 시점)

---

## 1. 클론

```powershell
git clone https://github.com/hyuck30401-coder/automation.git 신뢰성데이터분석툴
cd 신뢰성데이터분석툴
```

기존 PC 에서 작업하던 브랜치는 `master` 다.

## 2. 파이썬

- **Python 3.12** (CI 와 같은 버전)
- **의존성은 numpy 하나뿐이다** (CLAUDE.md §5-7 — 사내망이라 목록을 늘리지 않는다)

```powershell
py -m pip install --upgrade pip numpy
```

`openpyxl` / `markitdown` 은 관리대장을 읽을 때만 쓰는 보조 도구이고 툴 실행에는 필요 없다.

## 3. repo 에 따라오지 않는 것 — 손으로 채운다

| 대상 | 무엇인가 | 어떻게 채우나 |
|---|---|---|
| `Test Data/` | 사내 시험 데이터 (약 62MB) | **기존 PC 에서 직접 복사.** 재생성 불가 |
| `Perf Data/` | 벤치마크용 합성 데이터 | 필요하면 `py tools/make_perf_fixture.py` |
| `Known Data/` | 툴 검증용 합성 데이터셋 | `py tools/make_known_data.py` — 시드 고정이라 같은 파일이 나온다 |
| `tests/golden/` | 회귀 검증 기준 스냅샷 | `Test Data` 를 먼저 채운 뒤 `py tools/regression_snapshot.py` |
| `wafer_map_settings.json` | 다이 맵 경로·OTP 항목명 (Device 별) | 툴 화면 Wafer Map 패널 → [설정] 에서 다시 입력 |
| `*.log` | 실행 로그 | 없어도 된다 |

### Test Data 폴더 구조 (복사할 때 그대로 유지)

```
Test Data/
└─ SM3502Q/
   ├─ 00_MVT0-0_1111_111/      ← 골든 스냅샷 기준 조건
   ├─ 01_MVT1-3_1111_111/
   ├─ 01_MVT10-10_1111_111/
   └─ 02_MVT1-3_1111_WMAP/     ← 웨이퍼 맵(R-056·R-057) 검증용
```

데이터 루트는 툴 화면 왼쪽 아래 **DATA PATH → [경로 변경]** 으로 바꾸거나,
환경변수 `CDFTOOL_DATA_ROOT` 로 지정한다.

## 4. 동작 확인

```powershell
py cdf_compare_web.py
```

시작 배너에 `Rev.0.0xx · <날짜>+<소스해시>` 가 찍힌다. 이 해시가 바뀌지 않으면
최신 코드가 안 돌고 있는 것이다 (R-055).

## 5. 커밋 전 게이트 — 반드시 PASS 확인 (CLAUDE.md §5-2)

```powershell
py _automation/run_checks.py --data-root "Test Data"
```

`Test Data` 가 아직 없으면 단위 테스트만이라도 돌린다:

```powershell
py _automation/run_checks.py
```

## 6. 요구사항 관리대장

정본은 **`docs/요구사항관리대장.xlsx`** (이 repo 안) 이다.
예전 위치였던 `C:\파이썬코딩\요구사항관리대장.xlsx` 는 더 이상 쓰지 않는다 —
PC 를 옮기면 따라오지 않아서 repo 안으로 들였다 (2026-10-15).

- 개발 Item 별로 시트가 나뉜다. 이 프로젝트는 `신뢰성툴` 시트 · 번호는 `R-###`
- 상태 6가지: 승인대기 / 작업중 / 검증대기 / 완료 / 보류 / 취소
- **검증대기는 완료가 아니다.** 커밋 열에 해시가 없으면 완료로 바꾸지 않는다
- 커밋 메시지에 번호를 넣는다

읽기: `markitdown docs\요구사항관리대장.xlsx`

## 7. 지금 상태 (2026-10-15)

- 신뢰성툴 60건 — 완료 42 / **검증대기 18**
- 검증대기 18건은 코드는 들어갔고 **선우혁님 PC 확인이 남은 것**이다:
  R-043~R-059, R-060
- 릴리즈 번호는 아직 **Rev.0.031 / 태그 v0.0.31** 이다.
  `APP_REVISION` 은 릴리즈(태그)할 때만 올린다 (CLAUDE.md §9)

### 남은 입력 — 웨이퍼 맵 (R-056 · R-057)

둘 다 **견본 맵 + 합성 WMAP 데이터**로만 검증됐다. 실측 확인에는 두 가지가 필요하다.

1. **실제 유효다이 맵 TXT** (0/1 격자)
2. **실제 OTP 항목명 3개** — Wafer No. / X 좌표 / Y 좌표

받으면 Wafer Map 패널 [설정] 에 넣고 좌표가 맞게 찍히는지만 보면 된다.
견본은 `docs/wafer_map/SAMPLE_wafer_map_A_space.txt` 에 있다.
