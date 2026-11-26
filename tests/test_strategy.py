"""신호 로직: 둘 다 아래면 SGOV, 하나라도 위면 TQQQ. 경계값 포함."""
import math

import numpy as np
import pandas as pd
import pytest

from t6.strategy import alert_level, decide, near_line, realized_vol, refuge_periods, signal_frame


@pytest.mark.parametrize(
    "close, fast, slow, expected",
    [
        (99, 100, 100, "SGOV"),        # 둘 다 아래
        (90, 95, 110, "SGOV"),
        (101, 100, 102, "TQQQ"),       # 50일선만 위
        (101, 102, 100, "TQQQ"),       # 200일선만 위
        (110, 100, 100, "TQQQ"),       # 둘 다 위
        (100, 100, 101, "TQQQ"),       # 50일선과 정확히 같음 → '아래'가 아님
        (100, 101, 100, "TQQQ"),       # 200일선과 정확히 같음 → '아래'가 아님
        (100, 100, 100, "TQQQ"),       # 둘 다 정확히 같음
        (99.999, 100, 100, "SGOV"),    # 아주 조금이라도 둘 다 아래
    ],
)
def test_decide(close, fast, slow, expected):
    assert decide(close, fast, slow) == expected


def _frame(prices):
    idx = pd.bdate_range("2020-01-01", periods=len(prices))
    p = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "adj_close": p})


def test_frame_needs_200_days():
    sf = signal_frame(_frame([100.0] * 250))
    assert sf["signal"].iloc[:199].isna().all()
    assert sf["signal"].iloc[199] == "TQQQ"
    assert not sf["switch"].any()          # 첫 판정일은 교체일이 아니다


def test_frame_exact_equal_is_not_below():
    sf = signal_frame(_frame([100.0] * 220))
    last = sf.iloc[-1]
    assert last["close"] == last["sma_fast"] == last["sma_slow"] == 100.0
    assert last["signal"] == "TQQQ"
    assert bool(last["border"])            # 거리 0% → 경계선


def test_frame_switch_and_back():
    prices = [100.0] * 220 + [90.0] + [90.0] * 3 + [120.0]
    sf = signal_frame(_frame(prices))
    assert sf["signal"].iloc[219] == "TQQQ"
    assert sf["signal"].iloc[220] == "SGOV" and sf["switch"].iloc[220]
    assert not sf["switch"].iloc[221]
    assert sf["signal"].iloc[-1] == "TQQQ" and sf["switch"].iloc[-1]
    assert int(sf["switch"].sum()) == 2
    periods = refuge_periods(sf)
    assert periods == [(sf.index[220], sf.index[223])]


def test_frame_uses_chosen_column():
    f = _frame([100.0] * 220)
    f["adj_close"] = 50.0
    assert signal_frame(f, "close")["close"].iloc[-1] == 100.0
    assert signal_frame(f, "adj_close")["close"].iloc[-1] == 50.0


def test_near_line_half_percent():
    assert near_line(100.5, 100)
    assert near_line(99.5, 100)
    assert not near_line(100.51, 100)
    assert not near_line(99.49, 100)


def test_realized_vol_matches_manual():
    rng = np.random.default_rng(0)
    p = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, 60)))
    v = realized_vol(p, 20)
    r = p.pct_change().iloc[-20:].to_numpy()
    assert math.isclose(v.iloc[-1], r.std(ddof=1) * math.sqrt(252), rel_tol=1e-12)
    assert v.iloc[:20].isna().all()        # 수익률 20개가 모이기 전엔 없음


@pytest.mark.parametrize(
    "above, vol, expected",
    [(True, 0.36, "red"), (False, 0.36, "yellow"), (True, 0.35, "red"), (False, 0.3499, None),
     (True, 0.20, None), (True, float("nan"), None)],
)
def test_alert_level(above, vol, expected):
    assert alert_level(above, vol) == expected
