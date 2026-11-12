# CLAUDE.md — CDF Compare Tool 프로젝트 규칙

> AI 코딩 에이전트가 매 작업마다 읽는 프로젝트 컨텍스트다.
> Claude Code 는 `CLAUDE.md`, Cursor 는 `.cursorrules` 로 저장한다.
> 줄번호는 실제 소스(`cdf_compare_web.py` 7,345줄 / `cdf_compare_tool.py` 1,140줄)에서
> 직접 확인한 값이다. 안 맞으면 함수명으로 찾는다.
>
> **⚠️ §8 "빌드 / 실행" 이 비어 있다. 실제 명령어로 채울 것.**

---

## 1. 이 도구는 무엇인가

반도체 **신뢰성 시험 데이터 자동 판정 도구** (Pre/Post CDF Sigma Compare Tool, Rev.0.027).

HTOL·HAST·uHAST·TC·PTC·HTSL·HBM·CDM·LU 같은 스트레스 시험의 **전(Pre)/후(Post)** 측정
데이터를 비교해 사람이 눈으로 못 찾는 것을 자동으로 찾는다.

찾으려는 것은 세 가지다.

1. **스펙은 통과했지만 통계적으로 유의미하게 이동한 잠재 불량** — 핵심 목적.
   화면 용어로 "Abnormal Shift Items" / "Abnormal Pass List".
2. **Fail 유닛의 불량 유형 자동 분류** (Intermittent / Excessive / Slight / Tail)
   → 벤치(FA) 분석 대상 triage.
3. **시험조건 × 온도 × 리드아웃 전조합 스캔** (Total 분석).

### 판정 로직 (§5 참조 — 함부로 바꾸지 말 것)

```
Mea_S  = (측정값 − 해당 항목 표본평균) / 해당 항목 표본표준편차
Diff   = Post / Pre − 1                (DEVICE_ID 로 Pre 를 조인, §3-3 참조)
Diff_S = (Diff − Diff 평균) / Diff 표준편차
판정   : |Mea_S| > FLAG_LIMIT(=3) 또는 |Diff_S| > FLAG_LIMIT  →  SELECT, 아니면 OK
```

`Mea_S` 는 "집단 안에서 원래 튀는 유닛", `Diff_S` 는 "스트레스 때문에 움직인 유닛"을
각각 잡는다. OR 조건이라 둘 중 하나만 걸려도 SELECT. **이 구분이 도구의 핵심 설계이므로
둘을 합치거나 AND 로 바꾸면 안 된다.**

---

## 2. 코드베이스 구조

의존성은 **numpy 하나뿐**이다. PyInstaller 단일 exe 로 배포되며 **사내망 오프라인 환경**에서
동작해야 한다. → **새 서드파티 패키지를 절대 추가하지 말 것.**
(openpyxl, pandas, scipy, matplotlib, Flask 없이 XLSX 파싱/생성·차트·웹서버를 전부 직접
구현한 상태다. 실수가 아니라 의도된 설계다.)

| 파일 | 규모 | 역할 |
|---|---|---|
| `cdf_compare_tool.py` | **1,140줄** | 통계 코어, 데이터로그 파서(CSV/XLSX 직접 구현), 구버전 Tkinter GUI |
| `cdf_compare_web.py` | **7,345줄** | **55~4,664줄이 HTML/CSS/JS 단일 문자열 상수** (`HTML = r"""` ~ `</html>"""`)<br>4,664줄 이후가 HTTP 서버 + 분석 오케스트레이션 + XLSX 익스포트 |

`CdfCompareApp` 은 웹 빌드에서 `object.__new__` 로 생성되어 **순수 데이터 컨테이너로만**
쓰인다(`tk.Tk.__init__` 우회). GUI 메서드 약 670줄은 웹 빌드에서 도달 불가능한 죽은
코드다. **정리 지시가 없는 한 건드리지 말 것.**

### 실행 구조

```
브라우저 (127.0.0.1:8765~8799, 포트 스캔 폴백)
   │
ThreadingHTTPServer
   ├ GET  /                    내장 HTML 상수 전송
   ├ GET  /lookup              조건 캐스케이드 (§4)
   ├ POST /analyze-selection   job_id 발급 (프런트가 pass/fail 을 Promise.all 로 동시 실행)
   ├ GET  /progress?id=        250ms 폴링
   ├ GET  /latest-analysis     완성된 payload
   ├ GET  /item?name=&mode=    항목별 상세 (지연 로딩)
   ├ GET  /export-raw-data     수기 OOXML xlsx
   ├ GET  /summary-template    Summary 템플릿이 자리에 있는지            ← R-082
   ├ GET  /condition-spec      템플릿이 정한 시험 조건 입력칸 사양      ← R-087
   ├ GET  /condition-settings  저장된 시험 조건                         ← R-087
   ├ POST /condition-settings  시험 조건 저장                           ← R-087
   ├ GET  /summary-data        Summary Table 행 (신뢰성 항목별)         ← R-083
   ├ GET  /export-summary      템플릿 서식 그대로 채운 xlsx              ← R-083
   ├ POST /browse-data-files   저장할 파일 고르기 (네이티브 선택창)   ← R-080
   ├ POST /save-plan           저장 계획 (검증·폴더 확정·파일 해석)   ← R-080
   └ POST /save-data-files     계획대로 폴더 생성 + 복사              ← R-080
```

### Summary (R-082 버튼 · R-083 내용)

조건 패널 맨 아래 `Analysis Result` / `Summary` 두 버튼. 상단 appbar 의 `결과 새 창` 은
`Analysis Result` 로 내려왔다 — **id 는 `openResultsWindowBtn` 그대로**라
`setResultPanelsVisible()` 의 활성/비활성 처리를 그대로 쓴다.

- 템플릿 자리: `app_base_dir()/docs/RT_Summary_Template.xlsx` (상수 `SUMMARY_TEMPLATE_NAME`).
  exe 옆 `docs/` 를 가리키므로 소스로 돌리든 exe 로 돌리든 같은 자리다.
- **암호가 걸린 xlsx 는 열 수 없다.** `docs/` 의 기존 두 템플릿은 CDFV2 Encrypted 라 못 읽는다.
**R-083 — `Summary Table` 시트를 신뢰성 항목별 한 줄로 채운다.** (`ESD Result` 시트는 손대지 않고
그대로 복사된다. 자리표시자 방식은 쓰지 않았다 — 템플릿의 열이 고정이라 열 순서로 바로 쓴다.)

**열은 13개, 헤더는 2줄이다 (R-084).** Result 만 가로 3칸(Room/Hot/Cold), 나머지는 세로 2줄 병합.

| 열 | 값 |
|---|---|
| A Product · B Ver. · C Rel. Type · D Lot ID | 화면이 보낸 분석 조건. **데이터 행 전체를 세로 병합**하므로 첫 줄에만 쓴다 |
| E Rel. Item | `total_reliability_items` + `unit_counts.by_reliability` 의 합집합 |
| F Condition | `시험 조건 입력` 에서 받은 값 (R-087). 예: `Ta 125℃ / Vcc 5.5V` |
| G Duration | 판정에 쓴 Read-out (`total_conditions` / 행의 `judged_readout`) |
| H·I·J Result (Room/Hot/Cold) | `"%dF/%d" % (불량 유닛, 투입 유닛)`. **빈칸이면 그 온도로 시험하지 않은 것** |
| K Fail Item | 대표 1개 + "외 N건" (열 너비 21자). 전체 목록은 화면 표의 툴팁에서 본다 |
| L Judgement · M Remark | **빈칸** — 사람이 적는다 |

**Result 를 온도별로 쪼갠 이유 (R-084).** 한 항목이 Room/Hot/Cold 로 나뉘어 시험되는데
온도마다 Fail 수가 다르다 — 실측 HTOL 은 Room 9 / Hot 1 / Cold 13 이었다. 한 칸으로 합치면
어느 온도를 대표로 삼느냐에 따라 보고서 숫자가 1에서 13까지 흔들린다. **유닛 수는 온도 간
합집합을 쓰면 안 된다** (§3-3: Post 파일의 DEVICE_ID 품질이 고르지 않아 같은 유닛이 온도마다
다른 id 로 잡힐 수 있다). 분모와 분자를 같은 (항목, 온도) 파일에서 뽑아야 "몇 대 중 몇 대" 가
성립한다 — `unit_counts.by_condition["항목||온도"]` 가 분모다.

- 행은 **서버(`summary_table_rows`)가 만든다.** 화면은 받은 행을 그리기만 한다 — 판정 기준이
  화면과 엑셀에서 갈라지지 않게 하려는 것이다.
- **행을 새로 끼워 넣지 않는다.** 템플릿의 빈 행(3~13행)에 값만 꽂는다. 모자라면 저장을 거부하고
  "빈 행을 더 만들어 달라"고 알린다 — 행을 삽입하면 병합 셀·행 높이·테두리가 틀어진다.
- 문자열은 `t="inlineStr"` 로 넣어 `sharedStrings.xml` 을 건드리지 않는다. 셀의 `s`(서식) 속성은
  그대로 두므로 테두리·열 너비가 살아남는다. zip 안의 파일 순서도 원본대로 다시 쓴다.
- **빈 셀은 두 모양으로 온다** — 엑셀이 저장하면 `<c r="A3" s="3"/>`, openpyxl 이 저장하면
  `<c r="A3" s="3" t="n"></c>`. `set_sheet_cell()` 이 둘 다 받는다. 시트 경로를 찾는
  `summary_sheet_path()` 도 속성 순서를 가정하지 않는다 (엑셀은 `Id` 먼저, openpyxl 은
  `Target` 먼저 쓴다). 템플릿을 어느 도구로 저장했느냐에 따라 깨지면 안 된다.
- 조건 네 칸의 세로 병합은 `<mergeCells>` 에 범위를 더해서 만든다. 병합한 칸은 맨 윗줄만
  값을 갖는 것이 엑셀 규칙이라, 그 칸은 첫 데이터 행에만 쓴다.
- 화면 출력은 템플릿이 없어도 된다. 내보내기만 템플릿을 탄다.

### 시험 조건 입력 (R-087)

조건 패널의 `시험 조건 입력` 버튼. 신뢰성 항목별로 Stress 조건과 **투입 샘플 번호(First/Last)** 를
받아 `condition_settings.json` 에 저장하고, Summary 의 Condition 칸을 채운다.

- **입력칸의 사양은 코드가 아니라 템플릿의 `Condition 입력창` 시트가 정한다.** Eden 님이
  템플릿만 고치면 입력창이 따라 바뀐다. 화면에 기본값·선택지를 또 적어두지 마라 — 어긋난다.
- 셀 문구 해석 규칙 (전부 실제 템플릿에 있는 모양이다):

  | 문구 | 읽는 법 |
  |---|---|
  | `125 (Default), 직접입력` | 기본 125 + 자유 입력 |
  | `130 (Default), 110` | 선택지 둘 |
  | `85 (고정값)` | 수정 불가 |
  | `PWR, GND, I/O 체크박스 선택` | 다중 선택 (R-088) |
  | `"500cls, 1000cls (Default), 직접입력"으로 드랍다운` | 따옴표 안이 알맹이, 뒤는 지시어 (R-088) |
  | `"96hrs (if Ta= 130), 256hrs (if Ta = 110)"로 자동입력` | 다른 칸 값에서 따라온다 (R-088) |
  | `N/A` 또는 빈칸 | 칸 없음 |

  **선택지가 하나뿐이면 자유 입력도 켠다** — "기본값이고 필요하면 고친다"는 뜻으로 읽는다
  (R-088, Eden 님 확정). `(고정값)` 으로 명시한 칸만 잠근다.
  **해석이 안 되면 버리지 않고 자유 입력으로 떨어뜨린 뒤 원문을 힌트로 보여준다** — R-037 처럼
  조용히 사라지면 안 된다.
- 열 역할은 헤더가 아니라 **자리**로 읽는다: `D/E/F`·`G/H/I` 가 (라벨·값·단위) 쌍, `J/K` 가
  Datasheet Spec., `L` 이 Duration, `M` 이 Stress Voltage 당 Sample 수. 헤더 문구가
  `Environment/Voltage` 에서 `Stress Condition` 하나로 합쳐져도 그대로 동작한다.
- **여러 항목에 걸쳐 병합된 칸은 값을 공유한다** (R-088). `J3:J6` 은 HTOL·LTOL·HAST 가 같은
  Datasheet Spec. 하나를 쓴다는 뜻이다(Eden 님 확정). 저장 키가 `shared:<범위>` 가 되고,
  한 줄을 고치면 나머지 줄도 같이 바뀐다. 한 항목 안에서만 세로 병합된 칸(`J13:J15`)은 공유가
  아니다 — 병합 범위가 그 항목 밖까지 나가야 공유다.
- **Duration 은 HTOL~ELFR 만 입력칸이다** (R-088, Eden 님 확정). HAST·uHAST 는 Ta 값에 따라
  자동으로 정해져 읽기 전용이다. 입력값이 있으면 Summary 의 Duration 칸은 분석값 대신 그 값을 쓴다.
- xlsx 읽기는 표준 라이브러리만 쓴다(`read_xlsx_sheet`). 엑셀은 `sharedStrings`, openpyxl 은
  `inlineStr` 로 쓰므로 둘 다 받는다. 세로 병합의 둘째 줄은 건너뛴다 — 안 그러면 HAST 의 Vcc 가
  Ta/R.H. 두 줄에 걸쳐 병합돼 있어 같은 칸이 두 번 생긴다.
- 저장 키는 **조건 폴더 단위**(Product · Rel. Type · Ver. · Lot · Purpose). 같은 Lot 을 다시
  분석하면 입력값이 그대로 뜬다.
- Condition 칸 표기 (R-088, Eden 님 확정):
  - 일반 — `Ta 125℃ / Vcc 5.5V`
  - ESD — `PWR, GND, I/O / 500V ~ 3k (Step: 500V)` (고른 Mode 만 쉼표로, 전압은 범위로)
  - `Vcc` 의 `Op. Max` 처럼 값에 `Max`/`Min` 이 들어 있으면 Datasheet Spec. 의 전압으로 바꿔 쓴다.
    (숫자 여부로 판단하면 ESD 의 Mode 값까지 바뀐다 — 그래서 Max/Min 으로 좁혔다.)
  - Duration 과 Stress Voltage 당 Sample 수는 제 칸이 따로 있으므로 Condition 문자열에 안 넣는다.
- 템플릿 항목 12종 중 `ESD_HBM`→`HBM`, `ESD_CDM`→`CDM` 만 툴 항목과 잇는다
  (`CONDITION_ITEM_ALIASES`). `LTOL`·`ELFR`·`ESD_MM` 은 입력만 받고 Summary 에는 줄이 안 생긴다.
- 입력을 한 번도 안 해도 Condition 칸은 **템플릿의 기본값으로 채워진다.** 빈칸으로 두고 싶으면
  입력창에서 지워야 한다.
- **아직 안 한 것**: 항목 선택으로 분석 범위를 제어하는 것(B)과 Sample # 를 데이터의 Serial # 와
  대조하는 것(C). 입력칸만 먼저 만들어 뒀다.

### 데이터 저장 (R-080)

조건 패널의 `데이터 저장` 버튼이 여는 창에서, 데이터를 폴더 규칙(§3-1)대로 넣는다.

- **계획은 서버가 세운다.** 미리보기와 실제 저장이 같은 `build_save_plan()` 결과를 쓴다 —
  화면에 보이는 경로와 파일이 들어가는 경로가 어긋날 수 없게 한 것이다. 화면에 저장 규칙을
  다시 구현하지 마라.
- 조건 네 가지가 정확히 같은 폴더가 있으면 그 폴더에 넣고, 없으면 순번(기존 최대+1, 두 자리)을
  붙여 새로 만든다. 조건 일치는 `find_condition_folder()` — 구분이 빈 값이면 4토막 폴더만
  맞는다. `device_data_folders()` 의 필터(비면 전체)와 의미가 다르니 섞어 쓰지 마라.
- 만들 폴더명은 **되읽기 검증**을 거친다. `parse_data_folder_name()` 에 다시 넣어 같은 값이
  돌아오지 않으면 거부한다 (예: 구분을 비우고 Lot 에 `ERT`, Purpose 에 언더바 → 5토막으로
  읽혀 토막이 밀린다).
- Pre/Post 는 파일마다 고른다. 기본값은 `guess_file_kind()` 의 추측 — 항목 토막이
  `RELIABILITY_ITEMS` 에 걸리면 Post. 실데이터 54개에 54/54 맞았지만 추측은 추측이라
  화면에서 바꿀 수 있다.
- Pre/Post 하위 폴더는 이미 있으면 그 이름을 쓰고(`child_dir_containing`), 없을 때만
  `00_Pre` / `01_Post` 를 만든다.
- 같은 이름 파일은 기본 건너뜀. 전부 충돌이면 저장 자체를 막는다 — 0건 복사가 성공처럼
  보이면 안 된다.

---

## 3. 데이터 구조 — 실측으로 확인한 사실

> 아래는 전부 실제 파일을 열어 확인한 내용이다. 추측이 아니다.
> 샘플 데이터: `Test Data/SM3502Q/00_MVT0-0_ERT_123456_Tool 검증용/`

### 3-1. 폴더 규약

```
DATA_ROOT/
└── <Device>/                                        ← 예) SM3502Q
    └── <숫자>_<Ver>[_<구분>]_<Lot>_<Purpose>/        ← 구분은 선택. 아래 R-079 참조
        ├── ...pre... /                               ← 이름에 'pre' 포함 (부분 일치)
        └── ...post.../
             └── <..>_<온도코드>_..._<신뢰성항목>_<리드아웃>.csv|CSV|xlsx
```

**R-079 — 조건 폴더명은 4토막과 5토막을 모두 받는다.**

```
4토막  <숫자>_<Ver>_<Lot>_<Purpose>              예) 01_MVT1-3_1111_111
5토막  <숫자>_<Ver>_<구분>_<Lot>_<Purpose>        예) 00_MVT0-0_ERT_123456_Tool 검증용
```

- 5토막으로 읽는 조건은 **3번째 토막이 코드 상수 `RELIABILITY_TYPES` 에 있을 때** 하나뿐이다.
  언더바 개수만으로 가르면 Purpose 에 언더바가 들어간 4토막 폴더를 5토막으로 오인한다.
- `RELIABILITY_TYPES = ["ERT", "Qual.", "Qual. (Q100)", "ORT"]`.
  **새 구분값이 생기면 이 상수에 한 줄 추가해야 한다.** 목록에 없는 값은 Lot 으로 읽힌다.
- 구분 토막에 언더바(`_`)는 쓸 수 없다. Purpose 에는 써도 된다 (남은 토막을 되붙인다).
- Reliability Type 은 **선택 축이다.** 비워두면 필터를 걸지 않고 전체 폴더를 본다.
  필수로 만들면 4토막 폴더가 선택 불가가 된다 — 2026-08-02 `c4958dd` 가 고친 버그다.

- 온도코드: `RR`/`ER`=Room, `RH`/`EH`=Hot, `RC`/`EC`=Cold. **`RT` 는 인식 안 됨**
- 확장자 대문자(`.CSV`)는 정상 처리됨
- 예) `SM3502Q_RR04_AAA_R017_ROOM_HTOL_1000hrs.CSV` → item=HTOL, readout=1000hrs, Room

### 3-2. 데이터로그 레이아웃

```
행 46 | Test Name    | ... | DEVICE_ID | ...    ← 항목명 (비어있지 않은 셀이 가장 많은 행)
행 47 | Test Number  | ... | 8.49      | ...
행 48 | Lower Limit  |
행 49 | Upper Limit  |
행 50 | Units        | ... | Binnary   | ...
행 51 | Site # | Serial # | Bin | XCoord | YCoord | <항목들...>   ← 데이터 헤더
행 52+| 데이터
```

주의: `Test Name` 라벨이 **10행(로그 메타)과 46행(실제 항목명) 두 군데** 있다.
`find_test_item_name_row` 가 "비어있지 않은 셀이 가장 많은 행"을 고르므로 46행을
정확히 집는다. **이 휴리스틱을 바꾸면 파싱이 깨진다.**

### 3-3. Pre↔Post 조인은 **DEVICE_ID** 기준 (Serial # 아님)

Serial # 체계가 Pre 와 Post 에서 완전히 다르다.

| | PRE | POST |
|---|---|---|
| 행 수 | 3,173 | 145 |
| Serial # 예시 | `100041, 100049, 100057 …` (6자리) | `1, 2, 3, 4 …` (1번부터 재부여) |
| 고유 Serial # | 3,173 | 79 |
| **Serial # 교집합** | **0건 → 조인 불가** | |
| 고유 DEVICE_ID | 3,162 | 79 |
| **DEVICE_ID 교집합** | **78건, 전부 매칭** | |

Pre 는 **로트 전체를 찍은 ListAll 데이터**, Post 는 **시험 투입 유닛만 1번부터 새로
번호를 매긴 것**이다. 그래서 Serial # 로는 절대 안 붙는다.

**`DEVICE_ID` 는 별도 메타 컬럼이 아니라 Test Item 컬럼 중 하나다.**
Test Name 행의 값이 정확히 `DEVICE_ID` 이며, 이 파일에서는 129번째 열
(Test Number 8.49, Units `Binnary`). **컬럼 위치는 파일마다 다를 수 있으므로 반드시
이름으로 찾아야 한다.** 모든 시험 항목 파일에 같은 이름으로 들어간다(사용자 확인).

처리해야 할 예외 두 가지:

- **Post 의 DEVICE_ID 빈칸** — Serial 79번이 4행 전부 빈칸(Bin 4). Pre 매칭 불가 →
  `NO PRE SAMPLE` 로 처리. **절대 다른 유닛에 붙이면 안 된다.**
- **Pre 의 DEVICE_ID 중복** — 11건이 2회씩 등장. **마지막 등장을 채택**한다
  (`filter_records_to_last_sample` 과 같은 규칙).

`DEVICE_ID` 컬럼 자체는 측정값이 아니라 식별자이므로 **분석 항목에서 제외**한다.
(현재는 Units=`Binnary` 라 단위 필터에 우연히 걸리는데, 그 우연에 의존하지 말 것)

화면 표시(`Sample No.`)는 계속 **Serial #** 를 쓴다. 조인만 DEVICE_ID 로 한다.

### 3-4. 재시험은 **같은 파일 안에서 행이 반복**된다 (별도 파일 아님)

```
POST 145행 = 정상 57유닛(1행씩) + fail 22유닛(각 4행: 초기 + 재시험 3회)
예) DEVICE_ID 211997446 → Serial 16 (Bin 15) × 4행
    Serial 25 → Bin 15 → 17 → 15 → 15   (회차마다 Bin 이 다를 수 있음)
Serial # ↔ DEVICE_ID 는 양쪽 파일 모두 1:1
```

그런데 코드는 **"재시험 = 별도 파일"** 모델이다(`stage_sort_key`, `merged_fail_rows`).
파일이 하나면 `merged_fail_rows` 가 `if len(files) == 1: return` 으로 즉시 빠져나가
재시험 병합 로직이 실행되지 않는다.

**현재 동작 (실측 확인)**

| 경로 | 코드 | 결과 |
|---|---|---|
| Pass 값 | `filter_records_to_last_sample` 의 `by_sample[sample] = record` | **마지막 회차** |
| Fail 값 | `rows_from_records` 의 `row_map[sample]["items"][item] = record` | **마지막 회차** |
| Bin | `if not row_map[sample].get("bin")` | **첫 회차** |
| 이력 | `stages` 에 `"FT"` 하나만 | **1~3회차 소실** |

→ Bin 과 측정값의 출처가 어긋나고, `fail_type_for_detail` 의 `Intermittent` 판정은
history 에서 pass 를 찾는데 history 가 비어 있어 **원리적으로 성립 불가능**하다.

**사용자가 확정한 요구사항**

1. **대표 측정값 = 마지막 회차** (현재 동작과 동일 — 이 부분은 바꾸지 않는다)
2. **1회차 fail → 마지막 회차 Bin1 로 회복한 유닛은 `Intermittent`** 로 분류하고
   벤치 대상에서 제외 → **현재는 오분류된다.** `NOTES.md` P0 참조

### 3-5. 단위 필터로 제외되는 항목 (실측)

`unit_is_allowed` 화이트리스트는 V/A/s/Ω 계열뿐이다. 실제 데이터 548항목 중:

| 단위 | 항목 수 | 판정 |
|---|---|---|
| `V` / `uA` / `mA` / `Ohm` / `mS` | 462 | 통과 |
| `Binnary` | 58 | **제외** |
| `FailStep` | 21 | **제외** |
| `mOhm` | 4 | **제외** |
| `Khz` / `MHz` / `MHZ` | 3 | **제외** |

제외 사유가 UI 어디에도 표시되지 않아 사용자는 항목이 왜 없는지 알 수 없다.

---

## 4. 화면 입력 필드 (8개)

| # | 라벨 | 값의 출처 |
|---|---|---|
| 1 | Product | `DATA_ROOT` 바로 아래 폴더 이름 (R-081 전 라벨은 `Device`, id 는 그대로 `deviceInput`) |
| 2 | Rel. Type | 조건 폴더명 3번째 토막 — **5토막일 때만.** 선택 사항(R-079) |
| 3 | Ver. | 조건 폴더명 2번째 토막 |
| 4 | Lot No. | 조건 폴더명 Lot 토막 |
| 5 | Purpose | 조건 폴더명 Purpose 토막 |
| 6 | Reliability Items | **코드 상수 `RELIABILITY_ITEMS` 고정 9종** (파일을 보지 않음) |
| 7 | Read-out | Post 파일명 마지막 토막 |
| 8 | FT Temp. | Post 파일명 온도코드 |

**1~5번이 조건 폴더 하나를 확정하고, 6~8번이 그 폴더 안 `01_Post` 의 파일을 고른다.
두 축은 서로 참조하지 않는다.**

> 2번 Rel. Type 만 필수가 아니다. `has_base_analysis_selection` 과
> `selected_data_path` 의 필수 목록에 넣지 마라 — 4토막 폴더가 통째로 막힌다.

---

## 5. 절대 규칙

### 5-1. 판정 숫자를 바꾸지 말 것

**현재 판정 기준(§S7, 2026-08-08 확정): Grubbs 검정, alpha=0.01, ddof=1(표본표준편차).**
근거와 상세 정의는 §11 "통계 판정 규칙" 참조. **이 기준은 명시적 지시 없이 다시
바꾸지 않는다** — alpha/ddof/검정 방식을 바꾸는 순간 `tests/golden/`,
`docs/verdict_reports/`, 이 문서 §11 이 전부 stale 해지므로, 바꿔야 한다면 이 세
가지를 함께 갱신하는 별도 작업으로 다룬다.

**성능 리팩터링과 동작 변경을 절대 같은 커밋에 섞지 않는다.**

통계 정의(ddof, 임계값, 페어링 방식, 플로팅 포지션)를 바꾸는 작업은 반드시 별도
브랜치로 분리한다. 성능 작업 중 통계 문제를 발견하면 **`NOTES.md` 에 적기만 하고
넘어간다.**

이유: 성능 리팩터링의 유일한 검증 수단이 "숫자가 안 바뀌었다" 인데, 통계를 같이
고치면 회귀 테스트가 전부 실패해서 **성능 변경 때문인지 통계 수정 때문인지 구분할
수 없게 된다.**

성능 작업에서 통계 파라미터를 함수 인자로 노출하는 것은 허용한다. 단 **기본값은
반드시 현재 동작과 동일**해야 한다.

### 5-2. 회귀 테스트를 통과해야 한다

모든 변경 후 아래를 실행하고 **PASS 를 확인**한다. 실패하면 원인을 찾을 때까지 다음
작업으로 넘어가지 않는다. 원인을 못 찾으면 되돌린다.

```
python tools/regression_check.py --data-root <실제경로> --golden tests/golden/
```

### 5-3. 작업 대상은 **프로젝트 루트의 실제 파일**이다

수정은 반드시 아래 두 파일에 한다. **다른 경로의 사본을 만들거나 고치지 마라.**

```
<프로젝트 루트>/cdf_compare_web.py
<프로젝트 루트>/cdf_compare_tool.py
```

작업을 마치기 전에 **스스로 검증**해라. 보고만 하고 끝내지 마라.

```bash
git status                      # 수정된 파일이 위 두 개인지
git diff --stat                 # 변경 규모가 예상과 맞는지
grep -c "<이번에 추가한 식별자>" cdf_compare_web.py   # 실제로 들어갔는지
```

검증 결과를 **숫자로** 보고해라. "수정했습니다" 만으로는 부족하다.

### 5-3-1. 개발 서버 테스트 전에 exe 를 먼저 종료해라

`CDFCompareToolHTML_Rev0.027.exe` 가 이미 8765 포트를 잡고 있으면, Windows 의
`SO_REUSEADDR` 특성상 `python cdf_compare_web.py` 와 **동시에 같은 포트에 바인딩**되고
브라우저 요청이 어느 쪽으로 갈지 예측할 수 없다.

그 결과 **소스를 고쳐도 화면이 안 바뀌는** 현상이 생긴다(옛 exe 가 응답).
테스트 전에 반드시 exe 프로세스를 종료하고, 브라우저에서 확인한 내용이
개발 서버의 것인지 확인해라.

### 5-4. 실제 데이터로 검증하라 — 우회 금지

과거에 실패한 전례가 있으므로 명시한다. 다음은 **전부 금지**다.

- 데이터를 임시 폴더(`AppData\Local\Temp\...`, 스크래치패드)로 복사해서 돌리기
- **폴더명을 임의로 바꿔서**(예: 토막 수를 맞추려고 접미사 추가) 파서를 통과시키기
- 합성 픽스처로 대체하고 실제 데이터로 검증했다고 보고하기
- **분석 결과가 비어 있는데 그것을 정답 스냅샷으로 저장하기**

데이터 경로에서 막히면 **멈추고 사용자에게 물어봐라.** 스스로 우회하지 마라.
결과가 비어 있으면 그것 자체가 버그 신호다. 원인을 보고하라.

### 5-5. HTML 문자열 상수를 함부로 건드리지 말 것

`cdf_compare_web.py` 의 **55줄(`HTML = r"""`) ~ 4,664줄(`</html>"""`)** 은 프런트엔드
전체가 들어간 하나의 문자열이다. **해당 작업에서 명시적으로 허용하지 않는 한 수정하지
않는다.** 따옴표 하나만 깨져도 파일 전체가 문법 오류가 난다.

### 5-6. 지시 범위를 벗어나지 말 것

한 작업에서 지시한 함수/파일 밖을 "겸사겸사" 고치지 않는다. 발견한 문제는 `NOTES.md`
에 한 줄로 기록만 한다. 리뷰 가능한 크기 유지가 속도보다 중요하다.

### 5-7. 새 의존성 금지

numpy 와 파이썬 표준 라이브러리만 사용한다. §2 첫 문단 참조.

---

## 6. 알려진 문제 — 지금은 고치지 말 것

전부 판정 결과를 바꾸므로 성능 작업 중에는 손대면 안 된다. 상세는 `NOTES.md`.

**§S2~S7 로 해결됨(제거된 항목)**: 재시험 이력 소실(Intermittent 판정 불가) → §S6/S6b,
`sample_std` ddof=0 오표기 → §S2, `FLAG_LIMIT=3` 고정 임계 → §S3(Grubbs 전환),
`diff_ratio` pre≈0 폭발 방어 없음 → §S4(EPS_REL), `safe_ratio`/`sigma`/`mean` 의
"정의 불가"가 `0.0`으로 둔갑 → §S3/§S5(NOT EVALUATED/None). 상세는 §11과
`docs/verdict_reports/FINAL.md`, `NOTES.md` "완료/결정됨" 참조.

| 위치 | 문제 |
|---|---|
| `empirical_cdf` (tool:452) | 플로팅 포지션 `i/n` → 최상위 점이 항상 100% 라 확률지에 못 올림 |
| `item_analysis` (web:5029) | `enumerate(post_records)` 인덱스로 `post_values[index]` 참조 → 길이 어긋날 수 있음. **현재는 `to_float` 덕에 미발현(잠재)**. 컬럼형 전환 시 자동 해소 |
| `merged_fail_rows` (web:5610) | 재시험 파일을 `zip(...)` 로 위치 매칭. 실제 데이터에선 `len(files)==1` 이라 **실행조차 안 됨**. 우선순위 낮음 |
| `unit_is_allowed` (web:4748) | §3-5 참조. `DISALLOWED` 매칭이 **부분 문자열**이라 하이픈 포함 단위 전부 제외 |
| `Handler` 전체 | Origin/Host/Referer 검증 없음 (CSRF, DNS 리바인딩) |
| `waferPositionForSample` (프런트) | 웨이퍼 맵 좌표가 샘플번호 mod 12 로 만든 **가짜 값**. 실제 XCoord/YCoord 컬럼은 데이터에 존재함 |

---

## 7. 성능 기준선 (실측)

항목 1,000 × 유닛 3,000 (26 MB CSV) 기준. 개선 목표치다.

| 구간 | 현재 | 목표 |
|---|---:|---:|
| `read_csv` | 0.53s | — |
| `extract_item_records` | **6.8~10.3s (전체의 69%)** | 0.7s |
| `analyze` | 2.05s | 0.15s |
| `payload_with_items` | 2.3s | 0.1s |
| **`json.dumps`** | **12.5s (839 MB)** | 0.7s (25 MB) |
| 파싱 메모리 | **914 MB** | 24 MB |
| Total 분석 병렬 효율 | **0.89배 (ThreadPool — 역효과)** | 코어 수 비례 |

병목의 근본 원인 세 가지:

1. `numeric_count()` 가 컬럼마다 전체 데이터 행을 다시 스캔 → `to_float` 2배 호출
2. 컬럼 상수 메타(`test_number`, `unit`, limits)를 셀마다 재계산 →
   3M 셀 처리에 `row_value_at` 2,100만 회 / `cell_text` 1,500만 회 호출
3. **측정값 1개당 dict 1개** → 300만 개 dict
   (①②만 고치면 1.5배, 구조를 바꿔야 16배)

`payload_with_items()` (6280줄) 가 `payload['results']` **전체**를 순회하며 모든 항목의
상세를 만드는 것도 큰 비용이다. UI 는 선택된 항목 하나만 표시하고 `/item` + split cache
로 지연 로딩이 이미 가능하다.

**참고 구현**: `fast_datalog.py` 에 컬럼형 파서 + DEVICE_ID 조인 + 디스크 캐시 +
벡터화 분석이 구현되어 있다. 다만 **기존 코드와 다른 부분이 있으면 기존 코드가 정답**
이다. 반드시 기존 로직에 맞춰라.

### 7-1. §S7 완료 후 재측정 (Perf Data, `tools/bench.py --repeat 3`, 2026-08-08)

작업 시작 시점(§S1 이전) TOTAL 921.9s → **§S7 완료 시점 193.950s (-728s, -79%)**.
파스 캐시가 웜(warm)한 상태에서 측정했다 — `read_table`/`extract_item_records` 가
0.000s 로 나오는 것은 그 구간이 빨라졌다는 뜻이 아니라 캐시 히트로 스킵됐다는
뜻이다. 즉 위 §7 표(콜드 파스, `extract_item_records` 69%)와 이 표는 서로 다른
조건을 측정한 것이므로 직접 비교하지 않는다.

| 구간 | 초 | 비중 |
|---|---:|---:|
| `filter_records_to_last_sample` | 0.450s | 0.2% |
| `calculate_results_vectorized` | 29.095s | 15.0% |
| `payload_with_items` | 9.570s | 4.9% |
| `json.dumps` | 14.772s | 7.6% |
| **`cache write`** | **96.265s (49.6%)** | — |
| **TOTAL (wall, median)** | **193.950s** | — |

(508 items, payload 428,900,562 bytes, detail rows 1,478,280 — pass 모드, PERF01
콤보.) `cache write` 가 현재 최대 병목(49.6%)이며 §S7 범위 밖의 별도 과제다.
`calculate_results_vectorized`(29.095s)는 §S7 이전 grubbs-전용 재작성 직후 측정치
(`bench_after_grubbs_rewrite.txt`, 30.070s)와 거의 동일 — alpha 0.05→0.01 전환과
grubbs 정확 계산 자체는 이 구간 비용을 늘리지 않았다(`grubbs_critical` 메모이제이션,
§S4, 덕분).

---

## 8. 빌드 / 실행

```bash
# 개발 실행
python cdf_compare_web.py

# exe 빌드 (로컬)
#   근거: C:\파이썬코딩\CDFCompareToolHTML_Rev0.027.spec
#   Analysis(['cdf_compare_web.py']) / console=False / datas·hiddenimports 없음
pyinstaller --onefile --windowed --name CDFCompareToolHTML_Rev0.028 cdf_compare_web.py

# exe 빌드 (자동) — 이쪽을 쓰는 것이 원칙이다
#   태그를 밀면 GitHub Actions 의 build-exe 잡이 Windows 러너에서 빌드하고
#   스모크 테스트(실제로 서버가 뜨는지)까지 한 뒤 Releases 에 올린다.
#   exe 이름의 Rev 는 소스의 APP_REVISION 에서 뽑으며, 태그와 어긋나면 빌드가 멈춘다.
git tag v0.0.28 && git push origin v0.0.28

# 회귀 검증 / 벤치마크
python tools/regression_snapshot.py --data-root <경로> --out tests/golden/
python tools/regression_check.py    --data-root <경로> --golden tests/golden/
python tools/bench.py               --data-root <경로> --repeat 3
```

**multiprocessing 을 도입하는 작업에서는 개발 환경 테스트로 충분하지 않다.**
반드시 PyInstaller 로 빌드한 exe 에서 확인해야 한다.
(이 exe 에는 `pyi_rth_multiprocessing` 런타임 훅이 이미 번들되어 있어
추가 hidden-import 없이 `multiprocessing.freeze_support()` 한 줄이면 동작할 것으로 보인다.)

### 파일 인코딩

소스에 한글 주석과 한글 경로가 들어 있다. **UTF-8 로 읽고 쓴다.** cp949 로 저장하지 않는다.

---

## 9. 작업 방식

- **Eden 님의 요구사항은 `docs/요구사항관리대장.xlsx` (이 repo 안) 에서 번호로 관리한다.**
  개발 Item 별로 시트가 나뉘어 있고, 이 프로젝트는 `신뢰성툴` 시트 · 번호는 `R-###`.
  새 요구사항을 받으면 코드를 건드리기 전에 먼저 번호를 부여하고, 커밋 메시지에
  그 번호를 넣는다(예: `fix(ui): R-010 …`). 상태 정의와 규칙은 그 파일 `안내` 시트에 있다.
  읽기: `python -c "import openpyxl;..."` 또는 `markitdown docs\요구사항관리대장.xlsx`.
  (2026-10-15 이전 위치는 `C:\파이썬코딩\요구사항관리대장.xlsx` 였다. PC 를 옮기면
   따라오지 않아 repo 안으로 들였다 — 그 경로의 파일은 더 이상 쓰지 않는다.)
- **먼저 읽는다.** 추측하지 않는다. 확신이 없으면 멈추고 질문한다.
- 큰 함수를 통째로 재작성하지 말고 **바꿀 부분만 최소 수정**한다.
- 기존 함수 시그니처를 유지한다. 바꿔야 하면 **호출부를 먼저 grep 으로 전부 찾고** 시작한다.
- 작업 끝에 무엇을 바꿨는지 **3줄 이내로** 요약한다.
- **`APP_REVISION` 은 릴리즈 번호다. 릴리즈(태그)할 때만 올린다.** 변경마다 올리면
  배포된 적 없는 리비전이 쌓이고 태그가 결번이 된다(R-042에서 Rev.0.038 → Rev.0.031 로
  되돌렸다). 같은 리비전 안에서 빌드를 구분하는 것은 화면에 병기되는 `BUILD_ID`
  (개발 실행이면 git 짧은 해시, exe 면 빌드 시각)가 맡는다. 태그는 리비전과 맞춘다
  (`Rev.0.031` → `v0.0.31`) — CI 가 둘을 대조한다.
- 커밋은 한 가지 목적만 담고, 메시지에 **측정 수치를 포함**한다.

```
perf(payload): SELECT 항목만 details 생성, /progress 슬림화

- payload_with_items 가 selected_summary 항목만 순회하도록 변경
- /progress 는 상태만 반환, JOBS 에 payload 미저장
- 측정: json.dumps 12.5s → 0.7s, payload 839MB → 25MB
- regression_check PASS
```

---

## 10. 용어 사전

| 용어 | 의미 |
|---|---|
| Pre / Post | 스트레스 시험 **전** / **후** 측정 |
| Readout | 중간 측정 시점 (168hrs / 500hrs / 1000hrs 등) |
| FT Temp | Final Test 온도 (Room / Hot / Cold) |
| Bin | 테스터 판정 코드. Bin 1 = 양품 |
| **DEVICE_ID** | **유닛의 진짜 식별자. Pre↔Post 조인 키** (§3-3) |
| Serial # | 파일 내 순번. Pre 와 Post 에서 체계가 다름 — **조인에 쓰면 안 됨**. 화면 표시용 |
| Mea_S | 측정값의 표본 내 z-score (§11) |
| Diff_S | Pre 대비 변화율의 z-score (§11) |
| SELECT | \|Mea_S\| 또는 \|Diff_S\| 가 Grubbs 임계(alpha=0.01) 초과로 판정된 항목/샘플 (§11) |
| NOT EVALUATED | σ가 사실상 0(표본이 전부 같은 값)이라 z-score 자체가 정의상 무의미 — 판정 불가 (§11) |
| Intermittent | **유닛 전체**가 1차 fail, 마지막 회차 Bin 은 pass 로 회복 → 벤치(FA) 대상에서 제외 (§11) |
| Unstable | 유닛은 최종 fail 이지만 **개별 항목**이 회차 사이에 spec pass 를 찍은 적 있음 → 벤치 대상, 오히려 주목 (§11) |
| Excessive | 스펙에서 1% 이상 벗어난 명백한 하드 불량 |
| Slight | Mea_S·Diff_S **둘 다** Grubbs 임계 초과 → 통계로 뒷받침되는 진성 열화 |
| Tail | 그 외, 분포 꼬리 |
| Need Bench | FA(고장분석) 의뢰 대상 표시 |

---

## 11. 통계 판정 규칙

**현재 기준(§S7, 2026-08-08 확정)**: Grubbs 단일-이상치 검정, **alpha=0.01**,
표준편차는 **ddof=1(표본표준편차)**. §5-1 규칙에 따라 명시적 지시 없이 바꾸지 않는다.
근거 데이터는 `docs/verdict_reports/FINAL.md`(S0→S7 누적 비교)와
`docs/verdict_reports/S2.md`~`S6b.md`(단계별 상세)에 있다.

### 11-1. Mea_S / Diff_S 정의

- **Mea_S** — 한 항목의 Post 표본(크기 n) 안에서, 그 샘플 측정값의 z-score:
  `(value - mean) / std(ddof=1)`. "이 유닛의 측정값이 같은 항목의 다른 유닛들과
  비교해 몇 시그마 떨어져 있는가."
- **Diff_S** — Pre→Post 변화율(`diff_ratio = (post - pre) / abs(pre)`, `abs(pre) <
  EPS_REL * robust_pre_scale(item)`이면 정의 불가로 `None`, §11-6)의, 같은 항목
  표본 내 z-score. "이 유닛의 변화량이 같은 항목의 다른 유닛들 변화량과 비교해 몇
  시그마 떨어져 있는가." Mea_S 와 표본이 다를 수 있어(유효 diff 쌍 개수 ≠ n) 독립
  평가 후 결합한다(`stats_core.flag_result`).
- 최종 판정은 **두 축 중 더 심한 쪽**: `SELECT > NOT EVALUATED > INSUFFICIENT N > OK`
  우선순위로, 둘 중 하나라도 SELECT 면 그 항목/샘플은 SELECT.

### 11-2. Grubbs 임계값 메커니즘

고정 3σ 대신 표본 크기 n 에 따라 달라지는 Grubbs 임계값을 쓴다
(`grubbs_table.grubbs_critical(n, alpha)`, incomplete-beta 함수 기반 정확 계산,
§S7 에서 이전 scipy 보간-테이블 폴백의 alpha-에일리어싱 버그를 제거). 이유:
모표준편차 기준 `max|z| ≤ √(n-1)` 라서 **n 이 작으면 고정 3σ 는 flag 가 수학적으로
불가능**하고, n 이 크면(수천 단위) 순수 노이즈만으로도 대부분이 flag 된다(NOTES.md
"P0 — 통계 정의" 참조) — n 에 무관하게 같은 **유의수준(alpha)** 을 보장하는 것이
Grubbs 임계값의 목적이다.

### 11-3. alpha = 0.01 근거

`alpha_sweep.py` 로 Test Data(n=57)/Perf Data(clean 유닛 499·outlier 유닛 500) 양쪽에서
0.05/0.025/0.01 을 실측 비교했다(2026-08-08 최종 코드 상태 재확인,
`docs/verdict_reports/FINAL.md` §3):

| alpha | Perf Data clean 위양성 | Perf Data outlier 검출력 | Test Data SELECT(466항목) |
|---|---:|---:|---:|
| 0.05 | 8.4% (42/499) | 100% (500/500) | 218 |
| 0.025 | 4.0% (20/499) | 100% (500/500) | 181 |
| **0.01** | **1.6% (8/499)** | **100% (500/500)** | **138** |

alpha 를 0.05→0.01 로 낮추면 위양성이 8.4%→1.6%(약 1/5)로 줄어드는데도 **진성
이상치 검출력은 100%로 그대로**다 — 검출력을 희생하지 않고 위양성만 줄일 수 있는
구간이라 0.01 을 기본값으로 채택했다. `CDFTOOL_FLAG_ALPHA` 환경변수로 덮어쓸 수
있다.

### 11-4. ddof = 1 근거 (§S2)

이전 코드는 `np.std()`/`statistics.pstdev` 기본값인 ddof=0(모표준편차)을 썼면서
함수명은 `sample_std`(표본표준편차)였다 — 이름과 구현이 불일치했다. 표본표준편차
(ddof=1, `n-1` 로 나눔)는 Excel `STDEV`/JMP 의 정의와 일치하고, 현장 엔지니어가
그 도구들로 검산할 때 같은 숫자가 나온다. `stats_core.flag_result` 는 `mode="grubbs"`
일 때 `ddof=1` 을 전제로 하며(그 외 값이면 예외), `grubbs_table.py` 의 임계값도
이 기준으로 계산되어 있다 — 둘을 분리해서 바꾸면 안 된다.

### 11-5. Diff 부호 컨벤션 (§S4, 2026-08-05 결정)

`diff_ratio = (post - pre) / abs(pre)` — 분모는 **절댓값**을 쓴다(부호 있는 `pre`를
분모로 쓰면 pre 가 음수인 항목에서 열화/개선 부호가 반전되는 버그가 있었다, §S4
이전). 부호 자체는 **값이 이동한 방향**(내려가면 `-`, 올라가면 `+`)이며, 이것이
"열화"인지 "개선"인지는 툴이 판단하지 않는다 — LL/UL 스펙 방향을 보는 것은
엔지니어의 몫이다.

### 11-6. EPS_REL 게이트 (§S4)

`abs(pre) < EPS_REL * robust_pre_scale(item)` (기본 `EPS_REL = 1e-3`, 항목 스케일의
0.1%, `CDFTOOL_DIFF_EPS_REL` 로 조정 가능)이면 `diff_ratio` 는 **정의 불가(`None`)**
를 반환한다. pre 값이 0 은 아니지만 그 항목의 정상 스케일에 비해 사실상 0에
가까울 때, 분모가 아주 작은 수라 diff_ratio 가 비정상적으로 폭발(수백~수천 배)해
가짜 이상치를 만드는 것을 막는다. 정상적인 재측정 잡음(항목 스케일의 ~5%)보다
50배 작은 임계라 정상 표본이 우연히 걸릴 일은 없다.

### 11-7. Intermittent / Unstable 구분 (§S6, §S6b)

같은 파일 안에서 반복되는 재시험(retest) 이력을 물리적 행 단위로 복원한 뒤
(`stage_history_from_records`), 두 가지 서로 다른 질문에 서로 다른 이름을 준다:

- **Intermittent** (유닛 레벨, `state["is_intermittent"]`) — 그 **유닛 전체**가 1차
  회차(FT)에 fail, **마지막** 회차 Bin 은 pass 로 회복했는가
  (`(not bin_is_pass(first)) and bin_is_pass(last)`). 참이면 최종 상태가 정상이므로
  벤치(FA) 대상에서 제외한다.
- **Unstable** (항목 레벨) — 유닛은 **최종적으로 fail** 인데, **개별 항목** 하나가
  회차 사이 어느 시점에 spec pass 를 찍은 적 있는가(스펙 경계에서 흔들림). 벤치
  대상이며, 오히려 주목할 신호다.
- 우선순위: 유닛이 Intermittent 면(더 상위 사실이므로) 그 유닛의 모든 항목은
  Intermittent 로만 표시하고, 항목 레벨 flip-flop 은 따지지 않는다. Intermittent 가
  아닐 때만 Unstable 판정으로 내려간다.
- 실데이터(Test Data) 실측: 22개 fail 유닛 중 Intermittent(유닛 회복) **0건**,
  Unstable(항목 flip-flop, VSTART Serial 25·62) **2건**. `fail_type` 분포:
  `{'Excessive': 3, 'Slight': 2, 'Tail': 17, 'Unstable': 2}`.
