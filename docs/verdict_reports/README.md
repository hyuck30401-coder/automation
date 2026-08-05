# verdict_reports

통계개선_프롬프트.md §S2 부터는 판정(SELECT/OK/판정불가) 자체가 의도적으로 바뀐다.
`tools/regression_check.py`는 그 순간부터 매번 FAIL 하는 게 정상이라 신호로 못 쓴다.
대신 각 단계마다 `tools/verdict_diff.py --baseline tests/verdict_base/ --report docs/verdict_reports/S<n>.md`
로 만든 리포트를 여기에 커밋해서, "그 단계에서 무엇이 왜 바뀌었는지"를 저장소에 남긴다.

## 규칙
- 파일명: `S2.md`, `S3.md`, ... 각 절 번호와 1:1 대응.
- `tests/verdict_base/`는 5MB+ 라 git에 안 올린다 (`.gitignore`). 리포트만 추적한다.
- baseline 자체는 언제든 그 이전 커밋에서 `verdict_diff.py --save`로 재생성 가능하다.
- 리포트 위에 그 단계에서 바뀐 이유를 한두 줄 사람말로 덧붙여도 된다 (verdict_diff.py 출력 그대로 붙여넣기만 해도 무방).
