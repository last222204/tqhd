"""실제 시세로 시뮬레이터 확인 (저장된 시세가 없으면 건너뜀)."""
import pandas as pd
import pytest

from t6 import store
from t6.sim import data, engine, metrics


@pytest.fixture(scope="module")
def m():
    store.init_db()
    if (store.last_price_date("TQQQ") or "") < "2026-11-01" or store.last_price_date("^IRX") is None:
        pytest.skip("저장된 시세가 부족합니다")
    return data.build()


def test_2022_refuge_is_big_insurance(m):
    a, b = m.i_on_or_after("2022-01-01"), m.i_on_or_before("2022-12-31")
    t = metrics.refuge_records(m, a, b)
    row = t[t["start"] == pd.Timestamp("2022-04-08")].iloc[0]
    assert row["end"] == pd.Timestamp("2022-07-19")
    assert abs(row["tqqq"] - (-0.45)) < 0.02          # TQQQ 그대로 약 −45%
    assert abs(row["effect"] - 0.82) < 0.03           # 피신 효과 약 +82%
    assert row["verdict"] == "보험금"


def test_start_inside_refuge(m):
    p = engine.Params(start=pd.Timestamp("2022-06-16"), end=pd.Timestamp("2023-06-16"))
    r = engine.run(m, engine.UMBRELLA, p)
    assert not r.on[0] and r.trades[0]["to"] in ("SGOV", "BIL")
    t = metrics.refuge_records(m, *engine.window(m, p.start, p.end))
    assert t.iloc[0]["from_start"]


def test_end_inside_refuge_is_ongoing(m):
    a, b = m.i_on_or_after("2022-01-01"), m.i_on_or_before("2022-06-16")
    t = metrics.refuge_records(m, a, b)
    assert t.iloc[-1]["ongoing"]


def test_synthetic_flag(m):
    p = engine.Params(start=pd.Timestamp("2005-01-03"), end=pd.Timestamp("2010-01-04"))
    assert engine.run(m, engine.UMBRELLA, p).synthetic
    assert engine.run(m, "QLD", p).synthetic           # QLD 실제는 2006-06부터
    assert not engine.run(m, "QQQ", p).synthetic
    p2 = engine.Params(start=pd.Timestamp("2011-01-03"), end=pd.Timestamp("2016-01-04"))
    assert not engine.run(m, engine.UMBRELLA, p2).synthetic


def test_dotcom_start_works_with_fred_fx(m):
    p = engine.Params(start=pd.Timestamp("2000-03-01"), end=pd.Timestamp("2005-03-01"))
    r = engine.run(m, engine.UMBRELLA, p)
    s = metrics.summary(r)
    assert r.fx[0] > 1000 and s["final_krw"] > 0 and r.synthetic


def test_whipsaw_and_segments(m):
    a, b = m.i_on_or_after("2022-01-01"), m.i_on_or_before("2022-12-31")
    seg = metrics.holding_segments(m, a, b)
    assert len(seg) >= 3 and metrics.whipsaws(m, a, b) >= 1


def test_ongoing_refuge_not_judged(m):
    a, b = m.i_on_or_after("2022-01-01"), m.i_on_or_before("2022-06-16")
    t = metrics.refuge_records(m, a, b)
    assert t.iloc[-1]["verdict"] == "진행 중"
    s = metrics.refuge_summary(t)
    assert s["ongoing_n"] == 1 and s["gain_n"] + s["pay_n"] == len(t) - 1


def test_all_period_average(m):
    from t6.sim import scan

    tpl = engine.Params(start=m.idx[0], end=m.idx[1], colab=True)
    df, paths = scan.scan_detail(m, [engine.UMBRELLA, "QQQ"], tpl, pd.DateOffset(years=5), False)
    at = scan.average_table(df)
    assert df["start"].nunique() == 141
    assert abs(at.loc[engine.UMBRELLA, "평균 배수"] - 2.35) < 0.05          # 코랩 평균과 같은 값
    p = paths[engine.UMBRELLA]
    assert len(p) > 1200 and abs(p["mean"].iloc[0] - 0.998) < 0.01        # 시작일 ≈ 넣은 돈 (수수료만큼)
    assert (p["p10"] <= p["mean"] + 1e-9).all() and (p["mean"] <= p["p90"] + 1e-9).all()


@pytest.mark.parametrize("colab", [True, False])
def test_exit_column_equals_real_liquidation(m, colab):
    """'그날 팔았다면 세후' 칸 = 실제로 그날 끝내고 판 결과 (세금 해 넘김·5월 납부 포함)."""
    p = engine.Params(start=pd.Timestamp("2019-03-01"), end=pd.Timestamp("2023-09-01"), colab=colab)
    a, b = engine.window(m, p.start, p.end)
    full = engine.run(m, engine.UMBRELLA, p)
    for e in [a + 1, a + 200, a + 300, a + 555, a + 700, a + 820, b]:
        short = engine.run(m, engine.UMBRELLA, engine.Params(**{**p.__dict__, "end": m.idx[e]}))
        assert abs(full.exit_krw[e - a] - short.final_krw) < 1e-6 * short.final_krw, m.idx[e]
