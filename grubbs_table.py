# -*- coding: utf-8 -*-
"""Grubbs 이상치 검정 임계값 (양측) — scipy 없이 동작한다.

    G_crit(n, a) = (n-1)/sqrt(n) * sqrt(t^2 / (n-2 + t^2)),   t = t_{a/(2n), n-2}

t 분포의 upper-tail 임계값(t_{p, df})은 정규화 불완전베타함수(regularized
incomplete beta function)의 역함수를 이분법으로 풀어 **직접 계산**한다
(Numerical Recipes 스타일의 `_betacf` 연속분수 전개). scipy 의존 없이 임의의
(n, alpha) 조합을 오차 없이 지원한다.

§S7 이전에는 scipy 로 사전 계산한 alpha=0.05/0.01 두 테이블만 갖고 log(n) 선형
보간하는 방식이었는데, 그 두 값이 아닌 alpha 는 **조용히 alpha=0.05 테이블로
폴백**하는 버그가 있었다(예: alpha=0.025 를 넣어도 0.05 결과가 나옴). 이 버그를
낳았던 그 하드코딩 테이블은 `tests/test_grubbs_table.py` 에 회귀 비교용으로만
남아 있다(새 계산이 옛 테이블 값과 허용오차 1e-3 이내로 일치하는지 확인).

의존성: 표준 라이브러리 math 뿐.
"""

import functools
import math


def _betacf(a, b, x):
    """정규화 불완전베타함수 연속분수 전개 (Numerical Recipes 방식)."""
    maxit = 200
    eps = 3e-16
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, maxit + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def _betainc(a, b, x):
    """정규화 불완전베타함수 I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _t_sf(t, df):
    """P(T > t), t >= 0, Student's t (자유도 df)."""
    x = df / (df + t * t)
    return 0.5 * _betainc(df / 2.0, 0.5, x)


def _t_isf(p, df, lo=0.0, hi=1000.0, iters=100):
    """역함수: P(T > t) = p 를 만족하는 t 를 이분법으로 구한다."""
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if _t_sf(mid, df) > p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


@functools.lru_cache(maxsize=None)
def grubbs_critical(n, alpha=0.05):
    """표본 크기 n, 유의수준 alpha 의 Grubbs 임계값. n < 3 이면 None (판정 불가).

    (n, alpha) 조합마다 결과가 고정이라 lru_cache 로 메모이즈한다 — 호출부가 항목별로
    같은 n 을 표본 수만큼 반복 호출해도(§S3 최적화 전) 실제 계산은 조합당 1회뿐이다.
    """
    if n is None or n < 3:
        return None
    df = n - 2
    t = _t_isf(alpha / (2 * n), df)
    return (n - 1) / math.sqrt(n) * math.sqrt(t * t / (n - 2 + t * t))


def max_possible_z(n, ddof=1):
    """표본 내에서 나올 수 있는 최대 |z|.

    ddof=1 이면 (n-1)/sqrt(n), ddof=0 이면 sqrt(n-1).
    임계값이 이 값보다 크면 어떤 데이터로도 flag 가 불가능하다.
    """
    if n is None or n < 2:
        return 0.0
    return (n - 1) / math.sqrt(n) if ddof == 1 else math.sqrt(n - 1)


def can_evaluate(n, alpha=0.05, ddof=1):
    """이 표본 크기에서 이상치 판정이 원리적으로 가능한가."""
    g = grubbs_critical(n, alpha)
    return g is not None and g < max_possible_z(n, ddof)
