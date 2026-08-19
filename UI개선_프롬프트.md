# CDF Compare Tool — UI 재구성 프롬프트 (W0~W6)

목업 `UI_레이아웃_제안.png` 기준. **HTML 문자열(약 4,600줄)을 재배치하는 작업**이라 단계를 잘게 나눴습니다.

```powershell
git checkout master
git pull                      # 없으면 생략
git checkout -b ui/layout-v2
```

---

## 이 브랜치에만 적용되는 규칙

```
CLAUDE.md §5-5 "HTML 문자열을 건드리지 마라" 는 이 브랜치에서 해제한다.
이 작업의 본체가 HTML/CSS 재배치이기 때문이다.

대신 아래를 반드시 지킨다.
- W1 을 제외한 모든 단계에서 판정 결과가 바뀌면 안 된다.
  단계마다 tools/regression_check.py 로 확인하고 PASS 를 보고할 것.
- 별도 결과창 모드(isResultsWindow, body.results-window CSS)를 깨뜨리지 마라.
  레이아웃을 바꾸면 그쪽 nth-child 폭 지정이 어긋난다. 매 단계 확인할 것.
- 한 단계가 끝나면 반드시 멈추고 보고한다. 다음 단계로 넘어가지 마라.
```

---

## 진행 순서

| 단계 | 작업 | 판정 변경 | 위험도 |
|---|---|---|---|
| **W0** | Total 조합에서 Read-out 제거 (판정=마지막 회차) | **있음** | 중 |
| **W1** | payload 보강 (요약 집계·시험별 건수·Fail 대표 유형) | 없음 | 낮음 |
| **W2** | 레이아웃 골격 재배치 (조건 접기 + 시험 탭 + 4분할) | 없음 | **높음** |
| **W3** | 목록 열 정리 + 임계 배수 표기 + 시험 배지 | 없음 | 중 |
| **W4** | 용어 변경 (SELECT → 이상 등) | 없음 | 낮음 |
| **W5** | 그래프 패널 정리 (Read-out 체크박스 배치) | 없음 | 낮음 |
| **W6** | Wafer Map 실좌표 연계 | 없음 | 중 (데이터 선행) |

**W0 를 먼저 하는 이유**: 목록 행 수가 바뀝니다. UI 를 먼저 고치면 두 번 손대게 됩니다.
**W6 은 좌표 데이터가 실제로 들어온 뒤**에 하세요. 지금은 파서가 XCoord/YCoord 를 읽지 않습니다.

---

## §W0. Total 분석 조합에서 Read-out 제거

```text
프로젝트 루트의 CLAUDE.md 를 읽고 시작해라.
이 단계는 판정 결과가 바뀐다. tools/verdict_diff.py 로 정량 보고해야 한다.

## 문제
total_analysis_combinations() 가 조합 키를 (item, readout, ft_temp) 로 잡는다.

    key = (parsed["item"], parsed["readout"], temp)

그래서 Post 폴더에 168/500/1000hrs 가 다 있으면 같은 항목이 3번 나온다.
    HTOL·Room·168hrs  → ICL2_V
    HTOL·Room·500hrs  → ICL2_V
    HTOL·Room·1000hrs → ICL2_V
지금 Test Data 는 Post 파일이 1000hrs 하나뿐이라 드러나지 않았을 뿐이다.

## 확정된 요구사항
판정은 "분석 시점 기준 마지막 Read-out" 하나로만 한다.
T0~T3 는 Detail 열과 그래프 겹치기(추세 비교)용이며 판정에 쓰지 않는다.

## 할 일
1. 조합 키를 (item, ft_temp) 로 바꾼다. readout 은 그 그룹 안에서
   readout_sort_key 기준 마지막 것을 자동 선택한다.
   post_history_files_by_readout() 가 이미 readout_sort_key 로 정렬하고 있으니 재사용해라.

2. 조합 payload 에 판정에 쓴 readout 을 실어라.
     "judged_readout": "1000hrs"
     "readout_history": ["168hrs", "500hrs", "1000hrs"]
   화면 각주에 "판정 Read-out 1000hrs (최신)" 로 표시할 값이다.

3. merge_total_payloads() 가 합칠 때 항목이 중복되지 않는지 확인해라.

4. 조건 영역의 Read-out 드롭다운은 남겨둔다.
   맨 위에 "최신 자동" 옵션을 추가하고 그것을 기본값으로 한다.
   특정 회차를 고르면 그 시점 기준으로 판정하는 기존 동작을 유지한다
   ("500hrs 시점으로 다시 판정" 이 가능해야 한다).

## 리드아웃 개수는 가변이다 - 이게 정상 동작이다
시험 초기에는 리드아웃이 1개뿐이고, 시간이 지나면서 2개 3개로 늘어난다.
없는 회차를 빈칸으로 채우거나 오류로 처리하지 마라. 있는 만큼만 쓴다.

    리드아웃 1개 (1000hrs 만)   → T0(Pre) + T1(1000hrs).  T2/T3 는 아예 만들지 않는다
    리드아웃 2개               → T0 + T1 + T2
    리드아웃 3개 이상          → T0 + T1 + T2 + T3 (최신 3개)

    judged_readout   = 항상 마지막 회차
    readout_history  = 실제 존재하는 회차 목록 (1개면 1개짜리 배열)

없는 회차에 대해서는
    - Detail 테이블에 그 열을 만들지 않는다 (빈 열로 두지 마라)
    - 그래프 체크박스를 만들지 않는다 (비활성 체크박스도 만들지 마라)
    - 그래프 곡선을 그리지 않는다
로 처리한다. 이 규칙은 W2/W3/W5 에도 그대로 적용된다.

## 파일명에 리드아웃이 없는 경우 - 지금은 파일이 조용히 버려진다
parse_post_file_name() 이 파일명 맨 끝 토큰을 무조건 리드아웃으로 읽는다.

    parts = stem.split("_")
    if len(parts) < 2: return None
    item    = parts[-2]
    readout = parts[-1]

그래서 이런 일이 생긴다.
    ..._ROOM_HTOL_1000hrs.CSV  → item=HTOL, readout=1000hrs   정상
    ..._ROOM_HTOL.CSV          → item=ROOM, readout=HTOL      항목명을 리드아웃으로 오인
    HTOL.CSV                   → None 반환 → **파일이 통째로 무시된다**

무시되는 것을 사용자가 알 방법이 없다. "왜 데이터가 안 나오지" 가 된다.

## 고칠 방향
1. 리드아웃 토큰이 없다고 판단되면 파일을 버리지 말고 기본값을 준다.
     readout = "Post"
   그 파일 하나가 T1 이 되고 판정도 그것으로 한다. T0 = Pre, T2/T3 는 만들지 않는다.

2. 마지막 토큰이 리드아웃인지 항목명인지 구분해라.
   판단 기준을 스스로 정하고 근거를 보고해라. 예를 들어
     - 숫자를 포함하면 리드아웃으로 본다 (1000hrs, 168h, 500)
     - RELIABILITY_ITEMS 목록과 일치하면 항목명으로 본다
   두 기준이 충돌하는 실제 파일명이 있는지 Test Data 로 확인해라.

3. 파일명 규칙을 못 읽은 파일은 payload 에 보고한다.
     "filename_warnings": [{"file": "...", "reason": "readout_not_found", "used": "Post"}]
   W5 의 인라인 배너로 표시할 값이다. 조용히 넘어가면 안 된다.

## 하지 말 것
- 파일을 버리는 기존 동작을 유지하지 마라. 그게 지금 문제다.
- 파일명을 바꾸라고 사용자에게 강요하지 마라. 있는 그대로 읽고 알려주기만 한다.

## 검증
Test Data 는 Post 파일이 1개(1000hrs)뿐이다. 그 상태로도 정상 동작해야 한다.
리드아웃이 여러 개인 경우는 간단한 픽스처를 만들어 확인해라
(기존 Post CSV 를 복사해 파일명의 회차만 바꾸면 충분하다. 값이 같아도 구조 검증은 된다).

## 완료 기준 - 숫자로
1. Test Data(Read-out 1개)에서 조합 수와 판정이 **완전히 동일**한가
   (verdict_diff "차이 없음" 이어야 한다. 달라지면 구현이 틀린 것이다)
2. 리드아웃 1개일 때 T2/T3 열·체크박스·곡선이 **생성되지 않는가**
   (빈 열이나 비활성 체크박스가 보이면 잘못된 것이다)
3. 리드아웃 3개짜리 픽스처에서 조합 수가 1/3 로 줄어드는가
4. judged_readout 이 항상 마지막 회차인가. readout_history 가 실제 개수와 맞는가
5. Read-out 드롭다운에서 특정 회차를 골랐을 때 그 회차로 판정되는가
6. 파일명에 리드아웃이 없는 파일(예: `SM3502Q_RR04_AAA_R017_ROOM_HTOL.CSV`)을 만들어
   넣었을 때 **버려지지 않고 T1 로 분석되는가**. filename_warnings 에 보고되는가
7. 기존 정상 파일명은 수정 전과 **완전히 동일하게** 파싱되는가
   (파일별 item/readout 파싱 결과를 수정 전후로 대조해서 보고)

보고 후 멈춰라.
```

---

## §W1. payload 보강 — 화면이 필요로 하는 값 만들기

```text
판정 로직은 한 줄도 건드리지 않는다. 집계 값만 추가한다.

## 지금 없는 것
화면에 요약 카드와 시험 항목 탭을 만들려면 아래가 필요한데 payload 에 없다.

1. 전체 집계
     "summary_counts": {
        "total_items":   1824,   # 분석 대상 항목 수 (Binary·단위미인식 제외 후)
        "select":         466,
        "ok":            1351,
        "not_evaluated":    7,
        "insufficient_n":   0,
        "excluded":         8    # 단위 미인식 등으로 제외된 항목 수
     }
   지금은 select_count 만 있다. OK / NOT EVALUATED / 제외 건수는 집계 자체가 없다.

2. 시험 항목별 건수 (탭 배지용)
     "item_counts": [
        {"reliability_item": "HTOL",  "select": 188, "total": 466},
        {"reliability_item": "HAST",  "select": 142, "total": 398},
        {"reliability_item": "PTC",   "select":   0, "total":   0},
        ...
     ]
   Post 파일에 없는 시험도 total=0 으로 포함해라. 화면에서 흐리게 표시할 것이다.

3. 제외된 항목 목록 (인라인 배너용)
     "excluded_items": [{"item": "...", "unit": "degC", "reason": "unit_not_allowed"}, ...]
   unit_is_allowed() 에서 걸러진 항목을 모아라. 지금은 조용히 사라진다.

4. Fail 목록용 항목 대표 이탈 유형
   analyze_fail_to_json() 의 summary_rows 에 추가한다.
     "fail_type": 그 항목 detail 행들의 fail_type 중 가장 심각한 것
   우선순위는 fail_type_for_detail 의 주석에 있는 순서를 그대로 쓴다.
     Intermittent > Unstable > Excessive > Slight > Tail
   ※ 지금 failColumns = passColumns 라 Fail 목록에 이 정보가 전혀 없다.

5. summary row 에 조건 정보 확인
   reliability_item / ft_temp / readout 이 selected_summary 행에 실려 있는지 확인해라.
   없으면 추가한다. §U1 에서 화면 열만 없앴고 필드는 남겨뒀어야 한다.

## 주의
- 판정 결과가 바뀌면 안 된다. 집계는 이미 확정된 result 를 세는 것이다.
- payload 크기가 커진다. item_counts / summary_counts 는 작지만
  excluded_items 는 항목 수만큼 늘어날 수 있으니 필요한 필드만 담아라.

## 완료 기준
1. Test Data 로 분석 후 summary_counts 의 합(select+ok+not_evaluated)이 total_items 와 맞는가
2. item_counts 의 select 합이 summary_counts.select 와 맞는가
3. excluded_items 건수가 실제 제외 건수와 맞는가 (단위별로 몇 건인지 같이 보고)
4. Fail 모드 summary 에 fail_type 이 실리는가
5. tools/regression_check.py PASS (판정 무변화)
6. verdict_diff "차이 없음"

보고 후 멈춰라.
```

---

## §W2. 레이아웃 골격 재배치 — 가장 큰 단계

```text
목업 UI_레이아웃_제안.png 을 기준으로 화면 구조를 바꾼다.
이 단계에서는 "자리 배치" 만 한다. 표 열 구성과 용어는 W3/W4 에서 한다.

## 목표 구조
  ┌ 1. 분석 조건 + 실행  [접기/펴기] ──────────────────────┐
  ├ 요약 스트립 (카드 4개 + 판정 기준 각주) ────────────────┤
  ├ 시험 항목 탭 + FT Temp. 칩 ───────────────────────────┤
  ├────────────────────────┬──────────────────────────────┤
  │ 좌상: [Abnormal Pass    │ 우상: 그래프 4탭              │
  │        | Fail 항목] 탭  │       + Read-out 체크박스     │
  ├────────────────────────┼──────────────────────────────┤
  │ 좌하: Analysis Result   │ 우하: Wafer Map                │
  └────────────────────────┴──────────────────────────────┘

## 1. 조건 + 실행을 한 세트로
- 지금 .rda-card(조건) 와 .toolbar(실행 버튼) 가 분리돼 있다. 하나의 카드로 합친다.
- 카드 헤더를 클릭하면 접힌다. 접힌 상태에서는 선택한 조건을 한 줄 요약으로 보여준다.
    ✓ SM3502Q · MVT0-0 · Lot 1111 · 111 · 전체 시험 항목 · Pre 포함
- 분석이 끝나면 자동으로 접힌다. 사용자가 다시 펼칠 수 있다.
- 접힘 상태는 화면 전환·재분석 후에도 유지한다(세션 내 메모리로 충분하다).

## 2. 요약 스트립 신설
W1 의 summary_counts 를 카드 4개로 표시한다.
    [분석 항목] [이상 데이터 식별] [정상] [판정 불가 ⚠]
- 판정 불가는 0건이면 카드를 숨긴다.
- 카드 아래 각주 한 줄:
    판정 기준  Grubbs · α 0.01 · 유닛 57개 · 임계 3.539
    판정 Read-out  1000hrs (최신)      T0~T3 는 추세 비교용
  α 와 임계는 payload 의 flag_limit / flag_alpha 를, Read-out 은 W0 의 judged_readout 을 쓴다.
  임계 옆에 ⓘ 를 두고 title 로 "임계는 유닛 수에 따라 달라집니다 (N=57 → 3.539,
  N=145 → 3.879, N=3000 → 4.673)" 를 넣어라.

## 3. 시험 항목 탭 신설
- 기존 analysisFilterBar 의 Reliability "칩" 을 "탭" 으로 바꾼다.
  맨 앞에 「전체」 탭을 두고, 각 탭에 W1 의 item_counts 건수를 배지로 붙인다.
  total=0 인 시험은 흐리게 표시하고 클릭해도 아무 일이 없게 한다.
- FT Temp. 칩과 Multi 체크박스는 탭 아래 줄에 그대로 둔다.
- 탭을 바꾸면 analysisFilters.reliability_item 이 바뀌고,
  아래 4개 패널이 전부 그 필터를 따른다. (기존 필터 동작을 재사용해라. 새로 만들지 마라)
- 조건 영역의 reliabilityTabs(고정 9종)는 삭제한다. 역할이 겹친다.
  대신 조건의 Reliability Items 드롭다운은 남기고, 맨 위에 "전체 (미선택)" 옵션을 둔다.

## 4. 4분할 배치
- 기존 #passResultsGrid 의 .result-table-column / .result-graph-column 2단 구조를
  2×2 그리드로 바꾼다.
- 좌상 = resultTable + overTable 을 탭으로 (Abnormal Pass Data / Fail 항목 List)
    ※ 지금 Fail/Pass 는 modePayloads 로 이미 둘 다 계산돼 있다. 탭 전환은
      기존 setAnalysisMode() 를 재사용하면 된다. 새 요청을 보내지 마라.
- 좌하 = detailTable (Analysis Result). 항목을 바꿔도 자리가 유지된다.
- 우상 = 그래프 4탭 (기존 graph-tabs 재사용)
- 우하 = waferCanvas
- 높이는 100vh 에 의존하지 마라. 창이 작으면 패널이 뭉개진다.
  각 행에 최소 높이를 주고 넘치면 내부 스크롤로 처리해라.

## 5. 죽은 요소 정리
- 사이드바에서 data-view 가 없는 tree-link 7개(Schedule Management, Final Result,
  Deliverables Status, Traceability Matrix, Action Tracking, Effectiveness Check, Settings)를
  클릭 불가로 만들고 "준비 중" 배지를 붙여라. 삭제하지는 마라.
- 패널 제목의 "□ ⋮" 텍스트를 제거한다. 기능이 없다.
- path-tools 의 "? ! U" 를 제거한다.
- 트리 항목마다 붙은 edit-label(폴더명 편집) 버튼 13개를 제거한다.

## 6. 버전 표기 통일
- APP_REVISION 을 "Rev.0.028" 로 올린다.
- view-subtitle 의 "Reliability Data Analyzer_Ver.0.027" 하드코딩을 없애고
  APP_REVISION 을 참조하게 한다. 두 곳에 따로 적혀 있으면 안 된다.

## 절대 지킬 것
- 판정 결과가 바뀌면 안 된다. 이 단계는 자리만 옮기는 작업이다.
- 별도 결과창(isResultsWindow) 이 깨지지 않아야 한다.
  body.results-window 의 nth-child 폭 지정이 열 개수에 묶여 있으니 확인해라.
- drawCharts() / renderDetailTable() / renderSummaryListTable() 등 기존 렌더 함수의
  "무엇을 그리는가" 로직은 건드리지 마라. "어디에 그리는가" 만 바꾼다.

## 완료 기준 - 화면 캡처와 함께
1. 4분할이 목업대로 배치됐는가 (캡처 첨부)
2. 조건 카드가 접히고 펴지는가. 접힌 요약 문자열이 실제 선택을 반영하는가
3. 시험 항목 탭 전환 시 4개 패널이 모두 필터되는가
4. 별도 결과창이 정상 동작하는가 (캡처 첨부)
5. tools/regression_check.py PASS
6. verdict_diff "차이 없음"
7. 브라우저 콘솔에 에러 0건

보고 후 멈춰라.
```

---

## §W3. 목록 열 정리 + 임계 배수 표기

```text
## 1. 기본 열 축소
passColumns 18열 중 기본 표시를 6개로 줄인다.
    Test No. | 항목 | 사유 | N | Max |σ| / 임계 | Q'ty
나머지 12열(Unit/LL/UL/Avg./Stdev./Shift/Shift-σ/Δ Mean/Min./Max./%/Sample No.)은
「＋ 열」 버튼으로 켜고 끈다. 선택 상태는 세션 내 유지.

열을 삭제하지 마라. 표시 여부만 토글한다. Excel 내보내기는 전체 열을 그대로 내보낸다.

## 2. Max |σ| 를 임계 대비 배수로
지금은 절대값(7.42)이라 임계 3.539 를 외우고 있어야 판단된다.
    표시:  2.10×   [막대]
    계산:  severity / max(mea_threshold, diff_threshold)
severity 와 항목별 임계는 payload 에 이미 있다(§V4, §S3). 새로 계산하지 마라.
- 1.0× 이상이면 빨강, 미만이면 회색
- 막대는 항목 간 상대 비교용. 0~3× 를 폭 0~100% 로 매핑하고 3× 초과는 100% 로 고정
- 원래 절대값은 title 툴팁으로 보여줘라 ("Mea_S 7.42 / Diff_S 4.13, 임계 3.539")

## 3. 시험 배지 (§U1 회귀 복구)
「전체」 탭일 때만 첫 열에 시험 배지를 표시한다.
    HTOL·Room   (reliability_item + ft_temp 를 합친 한 열)
특정 시험 탭을 고르면 이 열을 숨긴다.
※ 원래 코드의 hideContextColumns 로직과 같은 취지다. §U1 에서 통째로 없앤 것을 되살린다.
※ Read-out 은 이제 판정당 하나이므로 배지에 넣지 않는다(각주에 이미 있다).

## 4. Fail 탭 열 구성
Fail 목록은 Pass 와 봐야 할 값이 다르다. failColumns 를 별도로 정의한다.
    Test No. | 시험 | 항목 | 이탈 유형 | N | Max |σ| | Q'ty | Sample No.
이탈 유형은 W1 에서 만든 항목 대표 fail_type 을 쓴다.
Shift/σ 와 Δ Mean 은 Fail 모드에서 의미가 약하므로 기본 숨김으로 둔다.

## 5. Analysis Result 열
detailColumns 는 그대로 두되, 판정에 쓴 Read-out 열만 굵게 표시한다.
어느 열인지는 W0 의 judged_readout 으로 판단한다.

리드아웃 개수는 가변이다(W0 참조). 존재하는 회차만 열로 만들어라.
리드아웃이 1개면 Pre 와 그 1개만 나오는 것이 정상이다.
빈 열을 만들거나 "-" 로 채우지 마라.

## 완료 기준
1. 기본 6열로 뜨는가, 「＋ 열」로 나머지가 켜지는가
2. 배수 표기가 절대값과 일치하는가 (임의 항목 3개를 골라 severity / 임계 / 배수를 나란히 보고)
3. 「전체」 탭에서만 시험 배지가 보이는가
4. Fail 탭에 이탈 유형이 표시되는가
5. Excel 내보내기는 전체 열이 그대로 나가는가
6. regression_check PASS, verdict_diff 차이 없음

보고 후 멈춰라.
```

---

## §W4. 용어 변경

```text
SELECT 는 "선택하다" 라는 UI 동작으로 읽힌다. 사용자가 고른 게 아니라 툴이 골라낸 것이다.

## 화면 표기만 바꾼다. 내부 값(result == "SELECT")은 그대로 둔다.
표시 계층에서만 변환해라. 백엔드 문자열을 바꾸면 골든·verdict_diff·Excel 이 전부 깨진다.

  내부 값            화면 표기
  SELECT           →  이상
  OK               →  정상
  NOT EVALUATED    →  판정 불가
  INSUFFICIENT N   →  표본 부족
  NO PRE ITEM      →  Pre 없음
  NO PRE SAMPLE    →  Pre 미매칭

  패널 제목
  Abnormal Shift Items          →  이상 데이터 식별 결과
  Fail & Abnormal Data Lists    →  (탭으로 대체됨)

  Spec.-Out Type 값은 그대로 둔다 (Measured/Delta/Intermittent/Unstable/Excessive/Slight/Tail).
  이건 엔지니어링 용어라 번역하면 오히려 혼란스럽다.
  다만 Pass 모드의 Measured / Delta 는 "측정" / "변화" 로 표기해도 좋다. 판단해서 제안해라.

## Excel 내보내기
Raw / Summary 시트의 값은 내부 값(SELECT/OK)을 그대로 쓴다. 다운스트림 호환 때문이다.
화면과 다르다는 것을 헤더 정의서에 반영할 수 있게, 무엇을 바꾸고 무엇을 그대로 뒀는지 보고해라.

## 완료 기준
1. 화면에 SELECT / OK 문자열이 남아 있지 않은가 (grep 결과 보고)
2. payload 와 Excel 의 내부 값은 그대로인가
3. regression_check PASS

보고 후 멈춰라.
```

---

## §W5. 그래프 패널 정리

```text
## 1. Read-out 체크박스를 그래프 패널 안으로
지금 graphFilterBar 가 별도 영역에 있다. 우상단 그래프 패널의 탭 바로 아래로 옮긴다.
    READ-OUT  ☑ T0 Pre  ☑ T1 168hrs  ☑ T2 500hrs  ☑ T3 1000hrs      ☐ Fail Exception
- 라벨에 실제 리드아웃명을 같이 표시해라 (지금은 T1/T2/T3 만 나온다).
  post_readout_labels 를 쓰면 된다.
- **리드아웃 개수는 가변이다(W0 참조).** 존재하는 회차의 체크박스만 만들어라.
  리드아웃이 1개면 `☑ T0 Pre  ☑ T1 1000hrs` 두 개만 나오는 것이 정상이다.
  없는 회차를 비활성 체크박스로 만들거나 "T2 (없음)" 으로 표시하지 마라.
- 체크박스 옆에 해당 시리즈 색상 점을 표시해서 그래프와 대응되게 해라.
- 색은 시간 순서가 읽히도록 T0 파랑 → T1 초록 → T2 주황 → T3 빨강 순으로 고정한다.
  지금 readoutColor 팔레트는 빨강부터 시작해서 순서가 안 읽힌다.

## 2. 차트 도구
각 그래프 패널 우측에 PNG 저장과 확대 버튼을 둔다.
- PNG 저장: canvas.toDataURL 로 내려받기. 파일명은 "항목명_그래프종류_날짜.png"
- 확대: 모달로 전체 화면 표시. 닫기는 ESC 와 배경 클릭 둘 다 동작해야 한다.
  ※ alert/confirm 은 쓰지 마라. 브라우저 모달은 흐름을 끊는다.

## 3. 에러 표시를 인라인 배너로
지금 alert(err.message) 로 띄운다. "Unexpected end of JSON input" 같은 개발자용
메시지가 그대로 나온다.
- 요약 스트립 아래에 배너 영역을 만들고 거기에 표시해라.
- 배너에는 (a) 사람이 읽을 수 있는 요약 (b) 원문 메시지 접기 (c) 복사 버튼 (d) 닫기
- W1 의 excluded_items 도 같은 배너로 보여줘라.
    "단위를 인식하지 못해 8개 항목이 분석에서 제외되었습니다  degC(3) %(2) dB(2) 없음(1)"

## 4. 필수 조건 검증
Reliability Items / Read-out / FT Temp. 가 비어 있어도 Analyze 가 눌린다.
지금은 그대로 실행되어 빈 응답을 받고 에러가 난다.
- 조건이 부족하면 실행 버튼을 비활성화하고, 어떤 항목이 필요한지 표시해라.
- 단, 「전체 (미선택)」 은 정상적인 선택이다. 이건 Total 분석이므로 실행 가능해야 한다.

## 5. 상태 표시 통합
status-pill / summary / latestAnalysisDate / itemThresholdLabel / flagAlphaLabel 이
6곳에 흩어져 있다. 실행바 우측 한 곳으로 모아라.
"Status: Failed" 인데 "Analysis is running..." 이 같이 보이는 모순도 고쳐라.

## 완료 기준
1. Read-out 체크박스가 그래프 패널 안에 있고 실제 리드아웃명이 보이는가
2. 체크를 끄면 해당 곡선이 사라지는가
3. PNG 저장과 확대가 동작하는가
4. 조건이 비면 실행 버튼이 비활성화되는가
5. 에러가 alert 이 아니라 배너로 나오는가 (일부러 에러를 내서 확인)
6. regression_check PASS

보고 후 멈춰라.
```

---

## §W6. Wafer Map 실좌표 연계 — 좌표 데이터 확보 후

```text
※ 이 단계는 XCoord/YCoord 가 실제로 파싱되는 상태여야 시작할 수 있다.
   먼저 파서 확인부터 하고, 없으면 파서 작업이 선행이다.

## 지금 상태 - 가짜 좌표다
waferPositionForSample() 이 샘플 번호를 12로 나눈 나머지로 좌표를 만든다.
    row = floor((n-1)/12),  col = (n-1) % 12
그리고 모든 다이를 "Good"(#b8dafc)으로 칠하면서 범례에는
"Fail / Good / Edge or No Die" 3분류를 표시한다.
틀린 정보를 정확해 보이게 그리는 상태다.

## 할 일
1. 파서가 XCoord / YCoord / Wafer 번호를 읽는지 확인해라.
   CSV 52행 헤더에 site # / Serial # / Bin / XCoord / YCoord 가 있다.
   읽지 않으면 record 에 추가한다 (파싱만 추가, 판정 로직은 건드리지 마라).

2. waferPositionForSample() 을 삭제하고 실좌표를 쓴다.
   좌표가 없는 샘플은 그리지 않는다. 가짜 위치에 그리지 마라.

3. 다이 색을 실제 상태로 칠한다.
     선택 항목에서 이상으로 걸린 다이  → 빨강
     정상 다이                        → 연파랑
     좌표가 없거나 미측정              → 회색
   범례를 실제로 칠하는 색과 일치시켜라.

4. 우측 정보 패널
     Wafer / Sample / X Coord / Y Coord / Bin
   선택 샘플이 바뀌면 같이 갱신된다.

5. 좌표가 하나도 없으면 패널에 "좌표 정보가 없습니다" 를 표시하고
   웨이퍼를 그리지 마라. 빈 원을 그리면 오독한다.

## 선택 - 군집 판정 (Eden 님 확인 필요)
이상 다이가 서로 인접해 있으면 공정/장비 편차, 흩어져 있으면 개별 불량 신호다.
    인접 판정: 이상 다이 중 8-이웃으로 연결된 군집의 최대 크기
    3개 이상 인접하면 "군집 감지" 표시
이 기능을 넣을지는 지시를 받고 진행해라. 지시 없으면 넣지 마라.

## 완료 기준
1. 실제 XCoord/YCoord 로 그려지는가 (임의 샘플 3개의 좌표를 원본 CSV 와 대조 보고)
2. 좌표 없는 샘플이 가짜 위치에 그려지지 않는가
3. 범례가 실제 색과 일치하는가
4. 선택 샘플을 바꾸면 우측 정보가 갱신되는가

보고 후 멈춰라.
```

---

## 커밋

단계마다 하나씩. W2 는 크므로 안에서도 나눠도 좋습니다.

```powershell
git commit -m "fix(total): Total 분석 조합에서 Read-out 제거 - 판정은 마지막 회차 기준"
git commit -m "feat(payload): 요약 집계·시험별 건수·제외 항목·Fail 대표 유형 추가"
git commit -m "feat(ui): 레이아웃 4분할 재배치 - 조건 접기, 시험 항목 탭"
git commit -m "feat(ui): 목록 기본 6열 + 임계 대비 배수 표기 + 시험 배지 복구"
git commit -m "feat(ui): 판정 결과 용어를 한글 표기로 (내부 값은 유지)"
git commit -m "feat(ui): 그래프 Read-out 체크박스 이동, 에러를 인라인 배너로"
git commit -m "feat(wafer): 실제 XCoord/YCoord 연계"
```

---

## 시작 명령

```
프로젝트 루트의 CLAUDE.md 를 읽고, UI개선_프롬프트.md 의 "이 브랜치에만 적용되는 규칙" 을
읽은 뒤 §W0 코드블록을 수행해라. §W1 이후는 하지 마라.
완료 기준을 숫자로 보고한 뒤 멈춰라.
```
