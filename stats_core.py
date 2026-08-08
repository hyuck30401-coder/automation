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
import os

try:
    import numpy as np
except ImportError:
    np = None

from grubbs_table import grubbs_critical

FLAG_LIMIT = 3.0  # 고정 임계(mode="fixed") — §S2 이전까지 유일했던 값, 회귀 비교용으로 남겨둔다.

_VALID_FLAG_MODES = ("fixed", "grubbs")
FLAG_MODE = os.environ.get("CDFTOOL_FLAG_MODE", "grubbs")
if FLAG_MODE not in _VALID_FLAG_MODES:
    FLAG_MODE = "grubbs"

try:
    # §S7 결정(2026-08-08): 기본 alpha=0.05 → 0.01. Test Data 실측 위양성 SELECT
    # 138/466(0.05: 218/466), Perf Data clean 위양성 8.4%→1.6%, 검출력은 100%로 불변
    # (docs/verdict_reports/FINAL.md 참조). CDFTOOL_FLAG_ALPHA 환경변수로 덮어쓸 수 있는
    # 것은 그대로 유지.
    FLAG_ALPHA = float(os.environ.get("CDFTOOL_FLAG_ALPHA", "0.01"))
except (TypeError, ValueError):
    FLAG_ALPHA = 0.01

# diff_ratio 의 "pre 가 0 은 아니지만 항목 스케일 대비 0 에 가까움" 방어 상대 임계.
# §S4(범위 축소판: pre≈0 폭발 방어만, 2026-08-07). abs(pre) < EPS_REL * robust_pre_scale(item)
# 이면 diff_ratio 는 None(정의 불가)을 반환한다.
#
# 1e-3(항목 스케일의 0.1%)을 기본값으로 잡은 근거: 정상적인 재측정 잡음(§S4 이전 perf
# fixture 설계 기준 item_noise_sigma = item_sigma * 0.05, 즉 스케일의 5% 수준)보다 50배
# 작다 — 정상 표본의 pre 값이 이 임계에 우연히 걸릴 일은 없고, "1000배 이상 스케일이
# 다른" 진짜 병리적 근접-0 케이스만 걸러낸다. 실측(Test Data)으로 이 값이 과하거나
# 부족하면 CDFTOOL_DIFF_EPS_REL 로 조정할 수 있게 환경변수로도 노출한다.
try:
    EPS_REL = float(os.environ.get("CDFTOOL_DIFF_EPS_REL", "1e-3"))
except (TypeError, ValueError):
    EPS_REL = 1e-3

_UNSET = object()  # flag_result(mea_threshold=...) 미지정과 None(INSUFFICIENT N) 을 구분하는 센티널


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

    - 빈 입력(또는 전부 비유한값): None(정의 불가) — §S5. "평균 0" 이 아니라 "잴 수
      없음"이므로, 0.0 이 아니라 None 이어야 호출부가 이 둘을 구분해서 판정/표시할 수
      있다. §S5 이전에는 0.0 을 반환해 "완벽히 평균값"과 "데이터 없음"이 구분 불가했다.
    - n=1: 그 값 그대로 반환한다.
    - None/nan/inf 는 평균 계산에서 제외한다 (0 으로 취급하지 않는다).
    - numpy 유무와 무관하게 같은 값을 반환한다.
    """
    data = _clean_finite(values)
    if not data:
        return None
    if np is not None:
        return float(np.asarray(data, dtype=float).mean())
    return sum(data) / len(data)


def std_of(values, ddof=1):
    """유한값의 표준편차.

    - ddof=1(기본값, §S2): 표본표준편차 — Excel STDEV/JMP/Minitab 과 값이 일치한다.
      신뢰성 시험 데이터는 모집단 전수가 아니라 표본이라는 게 §S2 의 근거다. §S1 까지는
      ddof=0(모표준편차, cdf_compare_web.vector_stats / cdf_compare_tool.sample_std 의
      과거 동작)이 기본값이었다 — 판정용 호출부는 모두 명시적으로 ddof=1 을 넘기므로
      이 기본값 자체에 의존하지 않는다(호출부에서 의도가 보이도록 하는 것이 목적).
    - 빈 입력, 또는 n <= ddof (예: ddof=1 일 때 n<=1, ddof=0 일 때 n=0): None(정의 불가)
      을 반환한다 — §S5. n=1,ddof=1(표본표준편차)은 수학적으로 정의되지 않는 경우이지,
      "표준편차가 0"이 아니다. §S5 이전에는 0.0 으로 가드했는데, 그 0.0 이 진짜 sigma=0
      (전 표본 동일값)과 구분되지 않아 "표본이 부족해서 모른다"가 "완전히 균일하다"로
      둔갑했다.
    - None/nan/inf 는 계산에서 제외한다.
    - numpy 유무와 무관하게 같은 값을 반환한다.
    """
    data = _clean_finite(values)
    n = len(data)
    if n - ddof <= 0:
        return None
    if np is not None:
        return float(np.asarray(data, dtype=float).std(ddof=ddof))
    avg = sum(data) / n
    return math.sqrt(sum((value - avg) ** 2 for value in data) / (n - ddof))


def zscore(values, center, spread):
    """values 각 원소의 z-score 리스트. 입력과 같은 길이/순서를 유지한다.

    - center 또는 spread 가 None(mean_of/std_of 가 정의 불가로 None 을 반환한 경우, §S5):
      전체를 None 으로 채운다 — 기준(center) 또는 척도(spread) 자체가 없으면 z-score는
      원천적으로 계산 불가하다.
    - None, nan, inf, 숫자로 변환 불가한 값: 그 자리에 None 을 채운다 (건너뛰지 않는다 —
      호출자가 원본 인덱스와 대응시킬 수 있어야 하기 때문).
    - spread == 0: None(정의 불가) — §S5. 모든 표본이 center 와 같아 (value-center)=0 이라
      "z=0" 처럼 보이지만 0/0 은 수학적으로 정의되지 않는다. §S5 이전에는 0.0 으로
      대체했는데, 이 0.0 이 "이상치 없음(z=0)"과 "애초에 비교 불가(sigma=0)"를 구분하지
      못해 진짜 이상치를 가렸다 — flag_result 쪽 sigma_is_negligible() 이 이 축을
      NOT EVALUATED 로 처리하는 것과 일치시킨다.
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

    if center is None or spread is None:
        return [None] * len(cleaned)

    if np is not None:
        data = np.asarray([math.nan if value is None else value for value in cleaned], dtype=float)
        if spread == 0:
            result = np.full(data.shape, np.nan, dtype=float)
        else:
            result = (data - center) / spread
            result[~np.isfinite(result)] = np.nan
        return [float(value) if math.isfinite(value) else None for value in result.tolist()]

    result = []
    for value in cleaned:
        if value is None:
            result.append(None)
        elif spread == 0:
            result.append(None)
        else:
            z = (value - center) / spread
            result.append(z if math.isfinite(z) else None)
    return result


def max_abs_z(values, center, spread):
    """zscore(values, center, spread) 중 절댓값 최대. 유한한 z-score 가 하나도 없으면
    None(정의 불가) — §S5. 예전에는 0.0 이라 "이상치 없음"과 "잴 수 없음"이 구분 안 됐다.
    """
    scores = zscore(values, center, spread)
    nums = [abs(z) for z in scores if z is not None]
    return max(nums) if nums else None


def diff_ratio(pre_value, post_value, pre_scale=None, eps_rel=None):
    """(post - pre) / abs(pre) — 값이 이동한 방향(내려가면 -, 올라가면 +)만 나타내는
    순수 변화율이다. 열화/개선 판단이 아니다 (엔지니어가 LL/UL 로 판단). pre_value 가
    부호를 바꿔도(음수여도) 분모가 abs(pre_value) 라 부호 왜곡이 없다. §S4 에서 확정된
    공식 그대로다.

    - pre_value/post_value 중 하나라도 None/nan/inf 면 None.
    - pre_value == 0 이면 None (0 나눗셈 방지).
    - pre_scale 을 넘기고 abs(pre_value) < eps_rel(기본 EPS_REL) * pre_scale 이면 None.
      pre 가 정확히 0 은 아니지만 그 항목의 정상 스케일 대비 0 에 가까운 경우를 막는다 —
      분모가 스케일 대비 매우 작으면 절대 변화량이 작아도 비율이 수천~수만으로 폭발해
      diff_sigma 를 부풀리고 진짜 이상치를 가린다(masking, 같은 메커니즘을 §S3 Task 2 에서
      Grubbs "이상치 1개" 가정이 무너질 때도 확인했다). 호출부가 robust_pre_scale() 로
      항목의 median(abs(pre)) 를 구해 넘긴다 — pre_scale 이 None/0 이면 이 검사는
      건너뛴다(호출부가 아직 넘기지 않는 경로와의 하위호환).
    """
    if pre_value is None or post_value is None:
        return None
    if not math.isfinite(pre_value) or not math.isfinite(post_value):
        return None
    if pre_value == 0:
        return None
    if pre_scale is not None and pre_scale > 0:
        eps = EPS_REL if eps_rel is None else eps_rel
        if abs(pre_value) < eps * pre_scale:
            return None
    return (post_value - pre_value) / abs(pre_value)


def robust_pre_scale(pre_values):
    """항목의 pre 값들 중 median(abs(pre)) — diff_ratio 의 상대 임계 기준 스케일. §S4.

    mean 대신 median 을 쓰는 이유: 이 스케일 자체가 diff_ratio 폭발을 막으려는 목적인데
    mean 은 이미 폭발 후보(비정상적으로 작은 pre)나 극단값에 흔들리지만, median 은 절반
    이상이 정상 스케일이면 오염되지 않는다.

    유효(None/nan/inf 아닌) pre 값이 하나도 없으면 None — 호출부는 None 을 받으면 상대
    임계 검사를 건너뛰고(즉 diff_ratio 는 pre_value==0 절대 검사만 적용) 기존 동작을
    유지한다.
    """
    finite = [abs(value) for value in pre_values if value is not None and math.isfinite(value)]
    if not finite:
        return None
    if np is not None:
        return float(np.median(np.asarray(finite, dtype=float)))
    finite.sort()
    mid = len(finite) // 2
    if len(finite) % 2:
        return finite[mid]
    return (finite[mid - 1] + finite[mid]) / 2.0


def sigma_is_negligible(sigma, mean):
    """상대 기준으로 sigma≈0(사실상 전 표본이 동일값)인지 판정한다. §S3.

    절대 0 비교 대신 mean 스케일 대비 상대오차로 판정한다 — 부동소수점 연산 잔차(예:
    1e-38 대의 잔여 오차)가 "sigma==0 아님"으로 통과해버리면 z=(value-mean)/residual 이
    발산해 사실상 판정 불가인 항목이 "확실한 이상(SELECT)"으로 잘못 표시된다.
    기준: sigma <= abs(mean) * 1e-12. mean 이 0(또는 0 에 가까워 상대 기준이 무의미)이면
    sigma <= 1e-300 (사실상 0)이라는 절대 하한을 대신 쓴다.

    sigma 가 None 이면(호출부가 이 통계축을 아직 계산하지 않았거나 해당 없음) 판정하지
    않고 False 를 반환한다 — "모르면 정상"이 아니라 "모르면 이 검사를 건너뛴다"는 뜻이며,
    호출부가 반드시 실제 sigma 를 넘겨야 이 가드가 의미를 갖는다.
    """
    if sigma is None:
        return False
    if not math.isfinite(sigma):
        return True
    if mean is None or not math.isfinite(mean) or mean == 0:
        return sigma <= 1e-300
    return sigma <= abs(mean) * 1e-12


_STATUS_PRIORITY = {"SELECT": 3, "NOT EVALUATED": 2, "INSUFFICIENT N": 1, "OK": 0}


def _branch_status(z, n, sigma, mean, alpha, fixed_limit, mode, threshold=_UNSET):
    """z-score 하나(mea_s 또는 diff_s)에 대한 판정. z 가 None 이면 None(해당 통계 없음).

    threshold 를 넘기면(호출부가 같은 n 에 대해 이미 threshold_for() 로 계산해둔 값)
    grubbs_critical() 재호출을 건너뛴다 — 항목당 한 번이면 되는 계산을 표본 수만큼
    반복하지 않기 위한 최적화(§S3 후속). 안 넘기면(_UNSET) 기존처럼 여기서 계산한다.

    mode == "grubbs" 에서는 "sigma 를 못 구했다(None) 또는 사실상 0" 인지를 z 가 None
    인지보다 먼저 확인한다(§S5). mean_of/std_of/zscore 가 이제 계산 불가 시 0.0 대신
    None 을 반환하므로(§S5), 이 순서를 바꾸지 않으면 "그 축이 원래 없음(예: pre 데이터
    자체가 없음)"과 "그 축을 시도는 했는데 sigma 를 못 구했거나 사실상 0"이 똑같이
    z=None 으로 뭉개져 flag_result 가 그 축을 통째로 건너뛰고 다른 축에만 기대게 된다
    (§S3 이전 "σ=0 인 항목은 조용히 OK" 버그가 형태를 바꿔 재발하는 것과 같다). sigma 가
    None 인 경우까지 NOT EVALUATED 로 묶는 이유: 이 함수 차원에서는 "그 축이 원래 없음"과
    "시도했지만 정의 불가"를 구분할 방법이 없다 — 어느 쪽이든 이 축으로는 판정할 수
    없다는 결론은 같으므로, "판정 불가"를 명시하는 쪽(NOT EVALUATED)이 "조용히 무시하고
    다른 축에 의존"보다 항상 더 정직하다. (실제로 "그 축이 원래 없음" 케이스는 이미
    item_analysis/detail 쪽에서 "NO PRE ITEM"/"NO PRE SAMPLE" 로 이 결과보다 먼저 또는
    나중에 덮어써지므로, 여기서 NOT EVALUATED 로 잡혀도 최종 사용자에게 보이는 라벨은
    바뀌지 않는다.)
    mode == "fixed" 는 §S2 이전 회귀 비교 기준이라 이 재정렬을 적용하지 않는다 — z 가
    None 이면(그 축이 없거나 spread==0) 곧바로 None 을 반환해 그 축을 판정에서 제외한다.
    OK 는 최하위 우선순위라 "그 축이 명시적으로 OK"와 "그 축이 제외됨"은 최종 결과에서
    동일하게 작용하므로, 이 경로는 §S2 이전 고정 임계 동작과 결과가 달라지지 않는다.
    """
    if mode == "fixed":
        if z is None:
            return None
        return "SELECT" if (math.isfinite(z) and abs(z) > fixed_limit) else "OK"
    if sigma is None or sigma_is_negligible(sigma, mean):
        return "NOT EVALUATED"
    if z is None:
        return None
    if threshold is _UNSET:
        threshold = grubbs_critical(n, alpha)
    if threshold is None:
        return "INSUFFICIENT N"
    return "SELECT" if (math.isfinite(z) and abs(z) > threshold) else "OK"


def flag_result(
    mea_s, diff_s, n, sigma=None, mean=None,
    diff_n=None, diff_sigma=None, diff_mean=None,
    alpha=None, ddof=1, mode=None, fixed_limit=FLAG_LIMIT,
    mea_threshold=_UNSET, diff_threshold=_UNSET,
):
    """mea_s/diff_s 로부터 "SELECT"/"OK"/"INSUFFICIENT N"/"NOT EVALUATED" 를 반환한다. §S3.

    mea_s 는 n(=post 표본 크기)/sigma/mean 분포에서, diff_s 는 diff_n(=유효 diff 쌍
    개수)/diff_sigma/diff_mean 분포에서 나온 z 라 서로 다른 표본일 수 있다 — 각각 독립
    평가한 뒤 결합한다. diff_* 를 안 넘기면 mea_s 와 같은 n/sigma/mean 을 공유한다고
    본다(같은 표본에서 나온 두 값을 함께 판정하는 호출부용 단축 경로).

    - mode == "fixed": 기존 |z| > fixed_limit 동작 그대로(§S2 이전과 완전히 동일해야
      회귀 비교의 기준으로 쓸 수 있다) — n/sigma/mean 의 영향을 전혀 받지 않는다.
    - mode == "grubbs"(기본값, CDFTOOL_FLAG_MODE 로 전역 설정 가능): 임계값을
      grubbs_critical(n, alpha) 로 계산한다. n<3 이거나 표에서 계산 불가하면
      "INSUFFICIENT N". sigma_is_negligible() 이 True 면 "NOT EVALUATED"
      (그 표본은 사실상 전부 같은 값이라 z 자체가 정의상 무의미 — Grubbs 임계와 무관).
    - 두 축의 상태가 다르면 "SELECT" > "NOT EVALUATED" > "INSUFFICIENT N" > "OK" 순으로
      더 심각한/더 정보성 있는 쪽을 최종 결과로 삼는다. 둘 다 None(mea_s/diff_s 모두
      없음)이면 "OK".

    mea_threshold/diff_threshold: 호출부가 같은 n 에 대해 이미 threshold_for(n) 를
    계산해뒀다면(예: 한 항목의 표본 수천 개를 순회하며 매 샘플 flag_result 를 부르는
    루프) 여기로 넘겨서 grubbs_critical 재계산을 건너뛴다. 안 넘기면(기본값) 예전처럼
    이 함수 안에서 계산한다 — 동작은 동일하고 속도만 다르다. §S3 후속(성능) 최적화.
    """
    mode = mode or FLAG_MODE
    if mode not in _VALID_FLAG_MODES:
        raise ValueError(f"알 수 없는 flag mode: {mode!r}")
    if mode == "grubbs" and ddof != 1:
        raise ValueError("grubbs 모드는 ddof=1(표본표준편차) 을 전제로 한다 — grubbs_table.py 의 임계값이 그 기준으로 계산됨")
    alpha = FLAG_ALPHA if alpha is None else alpha
    diff_n = n if diff_n is None else diff_n
    diff_sigma = sigma if diff_sigma is None else diff_sigma
    diff_mean = mean if diff_mean is None else diff_mean

    mea_status = _branch_status(mea_s, n, sigma, mean, alpha, fixed_limit, mode, threshold=mea_threshold)
    diff_status = _branch_status(diff_s, diff_n, diff_sigma, diff_mean, alpha, fixed_limit, mode, threshold=diff_threshold)
    statuses = [status for status in (mea_status, diff_status) if status is not None]
    if not statuses:
        return "OK"
    return max(statuses, key=lambda status: _STATUS_PRIORITY[status])


def threshold_for(n, mode=None, alpha=None, fixed_limit=FLAG_LIMIT):
    """이 n 에서 실제로 쓰인 임계값(숫자). UI 에 "왜 이게 SELECT 인가" 표시용. §S3.

    mode="fixed" 면 n 과 무관하게 fixed_limit. mode="grubbs" 면 grubbs_critical(n, alpha)
    — n<3 등으로 정의 불가하면 None (호출부가 INSUFFICIENT N 표시에 씀).
    """
    mode = mode or FLAG_MODE
    if mode == "fixed":
        return fixed_limit
    alpha = FLAG_ALPHA if alpha is None else alpha
    return grubbs_critical(n, alpha)
