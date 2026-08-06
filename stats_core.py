# -*- coding: utf-8 -*-
"""단일화된 통계 코어 — 통계개선_프롬프트.md §S1.

cdf_compare_web.py(Pass 모드, vector_stats/vector_sigmas)와 cdf_compare_tool.py
(Fail 모드, mean/sample_std/sigma)가 같은 산수를 각자 따로 구현하고 있었다. 지금은
둘 다 ddof=0(모표준편차)라 값이 같지만, 구현이 갈라져 있어 한쪽만 고치면 Pass/Fail
판정이 어긋나는 위험이 있었다. 이 모듈이 그 유일한 구현이다.

**이 모듈 자체는 판정 규칙을 바꾸지 않는다.** std_of() 의 기본값은 기존 동작과 동일한
ddof=0 이다 (ddof=1 전환은 §S2 에서, 이 모듈의 기본값을 바꾸는 방식으로 한다).

의존성은 numpy(있으면 사용, 없으면 순수 파이썬 fallback)와 표준 라이브러리뿐이다.
numpy 유무에 따라 반환값이 달라지지 않도록 두 경로 모두 같은 결측치 처리 규칙
(None/nan/inf 는 계산에서 제외)과 같은 나눗셈 규칙(0 나눗셈 방지)을 쓴다.
"""
import math

try:
    import numpy as np
except ImportError:
    np = None


def _clean_finite(values):
    """values 를 float 로 변환하고 None/nan/inf/변환 불가 값을 제외한 리스트를 만든다."""
    cleaned = []
    for value in values:
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            cleaned.append(number)
    return cleaned


def mean_of(values):
    """유한값의 산술평균.

    - 빈 입력(또는 전부 비유한값): 0.0 을 반환한다.
    - n=1: 그 값 그대로 반환한다.
    - None/nan/inf 는 평균 계산에서 제외한다 (0 으로 취급하지 않는다).
    - numpy 유무와 무관하게 같은 값을 반환한다.
    """
    data = _clean_finite(values)
    if not data:
        return 0.0
    if np is not None:
        return float(np.asarray(data, dtype=float).mean())
    return sum(data) / len(data)


def std_of(values, ddof=0):
    """유한값의 표준편차.

    - ddof=0(기본값): 모표준편차 — cdf_compare_web.vector_stats /
      cdf_compare_tool.sample_std 의 기존 동작(둘 다 np.std() 기본 ddof=0)과 동일하다.
      §S2 에서 이 기본값을 ddof=1 로 바꿀 계획이다.
    - 빈 입력, 또는 n <= ddof (예: ddof=0 일 때 n=0): 0.0 을 반환한다. n=1,ddof=0 은
      이 가드에 걸리지 않고 정상적으로 계산되지만, 값 하나짜리 표본편차는 수학적으로도
      0.0 이라 결과는 같다 — 별도 특수 케이스가 필요 없다.
    - None/nan/inf 는 계산에서 제외한다.
    - numpy 유무와 무관하게 같은 값을 반환한다.
    """
    data = _clean_finite(values)
    n = len(data)
    if n - ddof <= 0:
        return 0.0
    if np is not None:
        return float(np.asarray(data, dtype=float).std(ddof=ddof))
    avg = sum(data) / n
    return math.sqrt(sum((value - avg) ** 2 for value in data) / (n - ddof))


def zscore(values, center, spread):
    """values 각 원소의 z-score 리스트. 입력과 같은 길이/순서를 유지한다.

    - None, nan, inf, 숫자로 변환 불가한 값: 그 자리에 None 을 채운다 (건너뛰지 않는다 —
      호출자가 원본 인덱스와 대응시킬 수 있어야 하기 때문).
    - spread == 0: 유한값은 0.0 (0 나눗셈 대신), 비유한값은 None.
    - 결과 자체가 비유한(inf/nan)이면 None 으로 바꾼다 (center/spread 가 항상 유한하다는
      전제 하에 이 프로젝트에서는 실질적으로 발생하지 않지만, numpy 유무에 관계없이
      동일한 결과를 보장하기 위해 두 경로 모두 이 처리를 한다).
    - numpy 유무와 무관하게 같은 값을 반환한다.
    """
    cleaned = []
    for value in values:
        if value is None:
            cleaned.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            cleaned.append(None)
            continue
        cleaned.append(number if math.isfinite(number) else None)

    if np is not None:
        data = np.asarray([math.nan if value is None else value for value in cleaned], dtype=float)
        if spread == 0:
            result = np.zeros(data.shape, dtype=float)
            result[~np.isfinite(data)] = np.nan
        else:
            result = (data - center) / spread
            result[~np.isfinite(result)] = np.nan
        return [float(value) if math.isfinite(value) else None for value in result.tolist()]

    result = []
    for value in cleaned:
        if value is None:
            result.append(None)
        elif spread == 0:
            result.append(0.0)
        else:
            z = (value - center) / spread
            result.append(z if math.isfinite(z) else None)
    return result


def max_abs_z(values, center, spread):
    """zscore(values, center, spread) 중 절댓값 최대. 유한값이 없으면 0.0."""
    scores = zscore(values, center, spread)
    nums = [abs(z) for z in scores if z is not None]
    return max(nums) if nums else 0.0


def diff_ratio(pre_value, post_value):
    """(post - pre) / abs(pre) — 값이 이동한 방향(내려가면 -, 올라가면 +)만 나타내는
    순수 변화율이다. 열화/개선 판단이 아니다 (엔지니어가 LL/UL 로 판단). pre_value 가
    부호를 바꿔도(음수여도) 분모가 abs(pre_value) 라 부호 왜곡이 없다. §S4 에서 확정된
    공식 그대로다.

    - pre_value/post_value 중 하나라도 None/nan/inf 면 None.
    - pre_value == 0 이면 None (0 나눗셈 방지).
    """
    if pre_value is None or post_value is None:
        return None
    if not math.isfinite(pre_value) or not math.isfinite(post_value):
        return None
    if pre_value == 0:
        return None
    return (post_value - pre_value) / abs(pre_value)


def flag_result(mea_s, diff_s, limit=3.0):
    """mea_s 또는 diff_s 의 절댓값이 limit 을 초과하면 True(SELECT 감), 아니면 False(OK).

    None/nan/inf 인 입력은 그 항목만 플래그에 기여하지 않는다(전체가 False 가 되는 게
    아니라 나머지 하나로 판단한다). 둘 다 None/비유한이면 False.
    """
    mea_flag = mea_s is not None and math.isfinite(mea_s) and abs(mea_s) > limit
    diff_flag = diff_s is not None and math.isfinite(diff_s) and abs(diff_s) > limit
    return mea_flag or diff_flag
