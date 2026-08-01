# tools/

성능 리팩터링 전후로 분석 결과가 바뀌지 않았는지 확인하는 회귀 테스트 하네스.
HTTP 서버를 띄우지 않고 `cdf_compare_web.py`의 `analyze_to_json()` / `analyze_fail_to_json()`을
직접 호출한다. 자세한 규칙은 프로젝트 루트 `CLAUDE.md` §3-2, 발견된 기존 버그는 `NOTES.md` 참조.

## 실행 예시

```bash
python tools/regression_snapshot.py --data-root "D:\...\Reliability Test Data" --out tests/golden/
python tools/regression_check.py    --data-root "D:\...\Reliability Test Data" --golden tests/golden/
python tools/bench.py               --data-root "D:\...\Reliability Test Data" --repeat 3
```

- `regression_snapshot.py`: 지금 코드의 분석 결과를 `tests/golden/`에 정답 스냅샷(JSON)으로 저장. 데이터가 많으면 `--limit N`으로 조건 수 제한.
- `regression_check.py`: 저장된 스냅샷과 지금 코드의 결과를 비교. 실패하면 (조합, 항목, 필드, 이전값, 현재값) 표를 출력하고 exit code 1.
- `bench.py`: `read_table` / `extract_item_records` / `filter_records_to_last_sample` / `calculate_results_vectorized` / `payload_with_items` / `json.dumps` / 캐시 쓰기 구간별 소요 시간(중앙값, `--repeat` 기본 3)과 payload 크기·항목 수·detail 행 수를 출력. 기본은 데이터 중 가장 큰 조합을 자동 선택하며, `--device --ver --lot --purpose --item --readout --ft-temp`로 특정 조합을 지정할 수도 있다.

`_regression_lib.py`는 세 스크립트가 공유하는 내부 헬퍼(조합 탐색, analyze 호출, 비교 로직)이며 직접 실행하지 않는다.
