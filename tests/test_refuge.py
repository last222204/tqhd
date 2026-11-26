"""피신 기간별 손익: 직접 계산한 예시와 맞는지."""
import math

import pandas as pd

from t6.refuge import refuge_table, summary, synthetic_3x
from t6.strategy import signal_frame


def _setup():
    # QQQ: 220일 100 → 하루 90 (둘 다 아래, 피신) → 2일 90 → 120 (복귀)
    q = [100.0] * 220 + [90.0, 90.0, 90.0, 120.0]
    idx = pd.bdate_range("2021-01-01", periods=len(q))
    qqq = pd.Series(q, index=idx)
    sf = signal_frame(pd.DataFrame({"close": qqq, "adj_close": qqq}))
    tqqq = pd.Series(50.0, index=idx)
    sgov = pd.Series(100.0, index=idx)
    # 피신 진입일(220) 종가 → 복귀일(223) 종가
    tqqq.iloc[220], tqqq.iloc[223] = 40.0, 60.0      # TQQQ 그대로였다면 +50%
    sgov.iloc[220], sgov.iloc[223] = 100.0, 100.3    # SGOV +0.3%
    return sf, qqq, tqqq, sgov, idx


def test_one_refuge_by_hand():
    sf, qqq, tqqq, sgov, idx = _setup()
    t = refuge_table(sf, qqq, tqqq, sgov)
    assert len(t) == 1
    r = t.iloc[0]
    assert r["start"] == idx[220] and r["end"] == idx[223] and r["days"] == 3
    assert not r["ongoing"]
    assert math.isclose(r["tqqq"], 0.5)
    assert math.isclose(r["sgov"], 0.003)
    assert math.isclose(r["qqq"], 120 / 90 - 1)
    # 피신 효과 = 1.003 / 1.5 - 1 = -33.13% (피신이 손해: 반등을 놓침)
    assert math.isclose(r["effect"], 1.003 / 1.5 - 1)
    assert not r["tqqq_synthetic"] and not r["sgov_cash"]


def test_missing_data_uses_synthetic_and_cash():
    sf, qqq, tqqq, sgov, idx = _setup()
    t = refuge_table(sf, qqq, tqqq.iloc[:0], sgov.iloc[:0]).iloc[0]
    assert t["tqqq_synthetic"] and t["sgov_cash"]
    assert t["sgov"] == 0.0
    # QQQ 90→90→90→120: 일간 0, 0, +33.3% → 3배 = +100%
    assert math.isclose(t["tqqq"], 1.0)
    assert math.isclose(t["effect"], 1 / 2 - 1)


def test_ongoing_refuge():
    sf, qqq, tqqq, sgov, idx = _setup()
    cut = idx[222]
    t = refuge_table(sf.loc[:cut], qqq, tqqq, sgov).iloc[0]
    assert t["ongoing"] and t["end"] == cut


def test_synthetic_3x_compounds_daily():
    s = pd.Series([100.0, 110.0, 99.0])          # +10%, -10%
    assert math.isclose(synthetic_3x(s, 0, 2), 1.3 * 0.7 - 1)


def test_summary():
    t = pd.DataFrame({"effect": [0.10, -0.05, 0.20], "start": pd.to_datetime(["2020-01-01", "2021-01-01", "2022-01-01"])})
    s = summary(t)
    assert s["n"] == 3 and s["wins"] == 2 and s["losses"] == 1
    assert math.isclose(s["total"], 1.1 * 0.95 * 1.2 - 1)
    assert s["best"]["effect"] == 0.20 and s["worst"]["effect"] == -0.05
