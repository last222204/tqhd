"""실제 QQQ 데이터로 검산 (인터넷 필요).

- 2020년 3월 코로나 폭락, 2022년 하락장에 ☂️ 피신 신호가 나왔는지
- 2009년, 2023년 회복 때 ☀️ TQQQ로 돌아왔는지
- 저장된 배당조정 종가가 yfinance auto_adjust=True 종가와 같은지 (백테스트 기준 일치)
"""
import pandas as pd
import pytest

from t6.sources.yfinance_src import YFinanceSource
from t6.strategy import signal_frame

pytestmark = pytest.mark.network


@pytest.fixture(scope="module")
def sf():
    try:
        px = YFinanceSource().fetch_daily("QQQ", "1999-01-01")
    except Exception as e:  # 인터넷이 없으면 건너뜀
        pytest.skip(f"시세를 받지 못함: {e}")
    return signal_frame(px)


def sig(sf, d):
    return sf.loc[pd.Timestamp(d), "signal"]


def test_covid_crash_2020_refuge(sf):
    s = sf.loc["2020-03-12":"2020-04-07", "signal"]
    assert (s == "SGOV").all()
    assert sf.loc["2020-03-01":"2020-03-31", "switch"].any()


def test_bear_2022_refuge(sf):
    s = sf.loc["2022", "signal"]
    assert (s == "SGOV").sum() >= 100           # 2022년 대부분 피신
    for d in ["2022-05-12", "2022-06-16", "2022-10-13"]:
        assert sig(sf, d) == "SGOV", d


def test_recovery_2009_back_to_tqqq(sf):
    assert sig(sf, "2009-03-09") == "SGOV"      # 바닥
    back = sf.loc["2009-03-01":"2009-06-30"]
    assert ((back["signal"] == "TQQQ") & back["switch"]).any()
    assert sig(sf, "2009-06-30") == "TQQQ"


def test_recovery_2023_back_to_tqqq(sf):
    jan = sf.loc["2023-01-01":"2023-01-31"]
    assert ((jan["signal"] == "TQQQ") & jan["switch"]).any()
    assert (sf.loc["2023-04-01":"2023-07-31", "signal"] == "TQQQ").all()


def test_adj_close_equals_auto_adjust():
    import yfinance as yf

    try:
        auto = yf.Ticker("QQQ").history(start="2024-01-01", end="2024-12-31", auto_adjust=True)["Close"]
        mine = YFinanceSource().fetch_daily("QQQ", "2024-01-01").loc["2024-01-01":"2024-12-30", "adj_close"]
    except Exception as e:
        pytest.skip(f"시세를 받지 못함: {e}")
    auto.index = auto.index.tz_localize(None).normalize()
    joined = pd.concat([auto.rename("auto"), mine.rename("mine")], axis=1).dropna()
    assert len(joined) > 200
    assert ((joined["auto"] / joined["mine"] - 1).abs() < 1e-6).all()
