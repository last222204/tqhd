"""QQQ 1년 변동성과 '판이 바뀌었나' 경고."""
import math

import numpy as np
import pandas as pd

from t6.longvol import compute, top_pct_text, vol_1y


def _series(daily_sd_by_year: dict, seed=0):
    """연도별로 일간 표준편차를 정한 가짜 가격 (실제 NYSE 영업일 근사로 평일 사용)."""
    rng = np.random.default_rng(seed)
    parts = []
    for y, sd in daily_sd_by_year.items():
        idx = pd.bdate_range(f"{y}-01-01", f"{y}-12-31")
        parts.append(pd.Series(rng.normal(0, sd, len(idx)), index=idx))
    r = pd.concat(parts)
    return 100 * (1 + r).cumprod()


def test_vol_1y_matches_manual():
    p = _series({1998: 0.01, 1999: 0.01})
    v = vol_1y(p)
    r = p.pct_change().iloc[-252:]
    assert math.isclose(v.iloc[-1], r.std(ddof=1) * math.sqrt(252), rel_tol=1e-12)


def test_percentile_text():
    assert top_pct_text(0.579) == "상위 42%"
    assert top_pct_text(1.0) == "상위 1%"


def test_warning_needs_two_consecutive_year_ends():
    # SOX 는 늘 거칠게(일간 2.5%), QQQ 는 2003~2004 만 SOX 수준으로
    years = range(1998, 2007)
    sox = _series({y: 0.025 for y in years}, seed=1)
    calm = {y: 0.008 for y in years}
    rough_one = {**calm, 2003: 0.03}
    rough_two = {**calm, 2003: 0.03, 2004: 0.03}

    lv1 = compute(_series(rough_one, seed=2), sox, today_year=2007)
    assert lv1.years.loc[2003, "over"] and not lv1.years.loc[2004, "over"]
    assert lv1.warning_years == [] and not lv1.warning

    lv2 = compute(_series(rough_two, seed=2), sox, today_year=2007)
    assert lv2.warning_years == [2004]
    assert not lv2.warning            # 가장 최근 확정 연도(2006)는 잔잔 → 지금 켜진 경고는 아님

    rough_end = {**calm, 2005: 0.03, 2006: 0.03}
    lv3 = compute(_series(rough_end, seed=2), sox, today_year=2007)
    assert lv3.warning and lv3.warning_years[-1] == 2006
    assert 0.3 < lv3.sox_median < 0.5     # 데이터에서 계산 (일간 2.5% ≈ 연 40%)
