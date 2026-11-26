"""엔진을 손으로 계산한 예시와 맞춰 본다 (작은 가짜 시장)."""
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from t6.sim import engine, metrics
from t6.sim.data import REFUGE, Asset, Market


def _asset(n, pr=None, div=None, label="X", cash=False):
    pr = np.zeros(n) if pr is None else np.asarray(pr, float)
    div = np.zeros(n) if div is None else np.asarray(div, float)
    tr = (1 + pr) * (1 + div) - 1
    return Asset(tr, pr, div, np.zeros(n, bool), np.full(n, cash), np.full(n, label, object))


def _market(dates, tqqq_pr, sig_on, fx, ref_div=None):
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    n = len(idx)
    assets = {
        "TQQQ": _asset(n, tqqq_pr, label="TQQQ"),
        "QQQ": _asset(n, label="QQQ"),
        REFUGE: _asset(n, div=ref_div, label="SGOV"),
    }
    s = pd.Series(100.0, index=idx)
    return Market(idx, assets, np.asarray(fx, float), np.zeros(n), np.asarray(sig_on, bool),
                  np.ones(n, bool), s, s, s)


def _params(m, **kw):
    return engine.Params(start=m.idx[0], end=m.idx[-1], monthly_krw=0, **kw)


def test_switch_round_trip_by_hand():
    m = _market(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"],
                tqqq_pr=[0, 0.10, -0.05, 0, 0, 0.02],
                sig_on=[1, 1, 0, 0, 1, 1], fx=[1000] * 6,
                ref_div=[0, 0, 0, 0.001, 0, 0])
    r = engine.run(m, engine.UMBRELLA, _params(m, initial_krw=1_000_000), pay=np.zeros(6, bool))

    V = 1_000_000 / 1000 * (1 - 0.002)          # 처음 매수 0.2%
    V *= 1.10
    V *= 0.95
    p1 = V * 0.997                               # 피신: 매도 0.3%
    g1 = p1 * 1000 - 1_000_000                   # 원화 실현 차익
    V, B = p1 * 0.997, p1 * 1000                 # 매수 0.3%, 취득가 = 수수료 떼기 전
    net = V * 0.001 * (1 - 0.154)                # 배당 15.4% 떼고 재투자
    V += net
    B += net * 1000
    p2 = V * 0.997                               # 복귀
    g2 = p2 * 1000 - B
    V, B = p2 * 0.997, p2 * 1000
    V *= 1.02
    p3 = V * 0.997                               # 마지막 전량 매도 0.3%
    g3 = p3 * 1000 - B
    tax = max(g1 + g2 + g3 - 2_500_000, 0) * 0.22   # 공제 안쪽 → 0
    assert tax == 0
    assert math.isclose(r.final_krw, p3 * 1000, rel_tol=1e-12)
    assert [t["kind"] for t in r.trades] == ["처음 매수", "교체", "교체", "마지막 전량 매도"]
    assert math.isclose(r.trades[1]["realized"], g1, rel_tol=1e-12)
    assert list(r.on) == [True, True, False, False, True, True]


def test_capital_gains_tax_with_fx_by_hand():
    m = _market(["2024-03-04", "2024-03-05", "2024-03-06"], tqqq_pr=[0, 0.5, 0], sig_on=[1, 1, 1],
                fx=[1000, 1050, 1100])
    r = engine.run(m, engine.UMBRELLA, _params(m, initial_krw=20_000_000), pay=np.zeros(3, bool))
    proceeds_usd = 20_000 * 0.998 * 1.5 * 0.997
    gain = proceeds_usd * 1100 - 20_000_000      # 환차익 포함
    tax = (gain - 2_500_000) * 0.22
    assert math.isclose(r.final_krw, proceeds_usd * 1100 - tax, rel_tol=1e-12)
    assert math.isclose(r.cap_tax, tax, rel_tol=1e-12)
    # 환율 고정(달러 기준)이면 환율 효과가 없다
    r2 = engine.run(m, engine.UMBRELLA, _params(m, initial_krw=20_000_000, fx_mode="fixed"), pay=np.zeros(3, bool))
    gain2 = proceeds_usd * 1000 - 20_000_000
    assert math.isclose(r2.final_krw, proceeds_usd * 1000 - (gain2 - 2_500_000) * 0.22, rel_tol=1e-12)


def test_tax_paid_next_may_by_selling():
    dates = ["2023-12-28", "2023-12-29", "2024-01-02", "2024-05-30", "2024-05-31", "2024-06-03"]
    m = _market(dates, tqqq_pr=[0, 0.5, 0, 0, 0, 0], sig_on=[1, 0, 0, 0, 0, 0], fx=[1000] * 6)
    r = engine.run(m, engine.UMBRELLA, _params(m, initial_krw=20_000_000), pay=np.zeros(6, bool))
    p1 = 20_000 * 0.998 * 1.5 * 0.997
    gain = p1 * 1000 - 20_000_000
    due = (gain - 2_500_000) * 0.22
    sale = [t for t in r.trades if t["kind"] == "세금 납부용 매도"]
    assert len(sale) == 1 and sale[0]["date"] == pd.Timestamp("2024-05-31")   # 5월 마지막 거래일
    assert math.isclose(sale[0]["tax"], due, rel_tol=1e-12)
    assert math.isclose(r.tax_by_year[2024], due, rel_tol=1e-9)              # 마지막 날 세금 0 (차익 없음)
    V = p1 * 0.997
    gross = due / 1000 / 0.997
    left = (V - gross) * 1000
    assert math.isclose(r.value_krw[4], left, rel_tol=1e-12)


def test_unpaid_tax_settled_on_last_day():
    dates = ["2023-12-28", "2023-12-29", "2024-01-02", "2024-02-01"]
    m = _market(dates, tqqq_pr=[0, 0.5, 0, 0], sig_on=[1, 0, 0, 0], fx=[1000] * 4)
    r = engine.run(m, engine.UMBRELLA, _params(m, initial_krw=20_000_000), pay=np.zeros(4, bool))
    p1 = 20_000 * 0.998 * 1.5 * 0.997
    due = (p1 * 1000 - 20_000_000 - 2_500_000) * 0.22
    V = p1 * 0.997
    final = V * 0.997 * 1000
    gain_last = final - p1 * 1000              # 피난처 매도 손실 (수수료)
    assert math.isclose(r.final_krw, final - due - max(gain_last - 2_500_000, 0) * 0.22, rel_tol=1e-12)


def test_start_in_refuge_and_zero_amounts():
    m = _market(["2024-01-02", "2024-01-03", "2024-01-04"], tqqq_pr=[0, 0.1, 0.1], sig_on=[0, 0, 1],
                fx=[1000] * 3)
    pay = np.array([False, True, True])
    r = engine.run(m, engine.UMBRELLA, engine.Params(start=m.idx[0], end=m.idx[-1]), pay=pay)
    assert r.trades[0]["to"] == "SGOV" and not r.on[0]       # 처음 돈이 피난처로
    # 코랩: 그날 보유 = 전날 종가 판정. 전날도 피신이면 처음 돈이 수수료 없이 전액 피난처로
    rc = engine.run(m, engine.UMBRELLA, engine.Params(start=m.idx[1], end=m.idx[-1], colab=True), pay=pay)
    assert rc.value_krw[0] == 10_000_000 and not rc.on[0]

    r0 = engine.run(m, engine.UMBRELLA, engine.Params(start=m.idx[0], end=m.idx[-1], initial_krw=0), pay=pay)
    assert r0.invested_total == 2_000_000 and r0.final_krw > 0
    s0 = metrics.summary(r0)
    assert math.isfinite(s0["multiple"]) and math.isfinite(s0["low"])

    r1 = engine.run(m, engine.UMBRELLA, engine.Params(start=m.idx[0], end=m.idx[-1], monthly_krw=0), pay=pay)
    assert r1.invested_total == 10_000_000


def test_xirr():
    d = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])
    assert abs(metrics.xirr(d, np.array([-100, 110])) - 0.0999) < 0.001


def test_twr_removes_contributions():
    m = _market(["2024-01-02", "2024-01-03", "2024-01-04"], tqqq_pr=[0, 0, 0], sig_on=[1, 1, 1], fx=[1000] * 3)
    pay = np.array([False, True, False])
    r = engine.run(m, "QQQ", engine.Params(start=m.idx[0], end=m.idx[-1], initial_krw=1_000_000,
                                           monthly_krw=1_000_000, liquidate=False), pay=pay)
    ret = metrics.twr(r)
    # 가격이 그대로이면 적립을 해도 시간가중 수익률은 (매수 수수료 말고는) 0
    assert abs(ret.iloc[1] - (-0.002 * 1_000_000 / (1_000_000 * 0.998))) < 1e-9
    assert abs(ret.iloc[2]) < 1e-12
