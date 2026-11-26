"""청산 시나리오: 코랩 graduation_test.py 검산(±3%), 분류 기준, 같은 청산일, 데이터 끝 처리."""
import numpy as np
import pandas as pd
import pytest

from t6 import store
from t6.sim import data, engine, exits

S = [engine.UMBRELLA, "QQQ", "QLD", "TQQQ"]
# 코랩 결과: 실제 상품, 1,000만 + 매월 17일 100만, 시작 월 2010-03 ~ 2021-11 (141개), 세후
GRAD_A = {  # 연환산 중간값, 연환산 최악, 졸업 배수 중간값, 최하방 최악
    "QQQ": (0.154, 0.126, 1.60, 0.73),
    "QLD": (0.259, 0.206, 2.15, 0.50),
    "TQQQ": (0.355, 0.211, 2.76, 0.33),
    engine.UMBRELLA: (0.295, 0.167, 2.52, 0.50),
}
GRAD_B = {  # 연환산 중간값, 졸업까지 중간값(년)
    "QQQ": (0.173, 5.9), "QLD": (0.358, 2.9), "TQQQ": (0.569, 1.9), engine.UMBRELLA: (0.464, 2.2),
}


def close(x, y, tol=0.03):
    return abs(x / y - 1) <= tol


@pytest.fixture(scope="module")
def m():
    store.init_db()
    if (store.last_price_date("TQQQ") or "") < "2026-11-01" or store.last_price_date("BIL") is None:
        pytest.skip("저장된 시세가 부족합니다")
    return data.build()


@pytest.fixture(scope="module")
def colab_p(m):
    return engine.Params(start=m.idx[0], end=m.idx[1], colab=True)


def test_graduation_a_matches_colab(m, colab_p):
    df = exits.scan_rule(m, S, colab_p, exits.Rule("ath", 5, 15), exits.Thresholds())
    assert df["start"].nunique() == 141
    for s, (irr_med, irr_min, mult_med, low_min) in GRAD_A.items():
        g = df[df["strategy"] == s]
        assert close(g["irr"].median(), irr_med), (s, g["irr"].median())
        assert close(g["irr"].min(), irr_min), (s, g["irr"].min())
        assert close(g["multiple"].median(), mult_med), (s, g["multiple"].median())
        assert close(g["low"].min(), low_min), (s, g["low"].min())
    # 졸업 A 청산일은 시장 기준이라 모든 전략이 같다
    e = df.pivot(index="start", columns="strategy", values="e")
    assert (e.nunique(axis=1) == 1).all()


def test_graduation_b_matches_colab(m, colab_p):
    df = exits.scan_rule(m, S, colab_p, exits.Rule("target", 5, 15, 2.0), exits.Thresholds())
    for s, (irr_med, yrs_med) in GRAD_B.items():
        g = df[df["strategy"] == s]
        assert close(g["irr"].median(), irr_med), (s, g["irr"].median())
        assert close(g["years"].median(), yrs_med), (s, g["years"].median())
    # 첫 1년 안에는 졸업하지 않는다
    assert (df["e"] - df["a"] >= exits.TARGET_MIN_DAYS).all()


def test_data_end_is_counted_not_dropped(m, colab_p):
    df = exits.scan_rule(m, ["QQQ"], colab_p, exits.Rule("target", 5, 15, 2.0), exits.Thresholds())
    late = df[df["status"] == "data_end"]
    assert len(late) > 0 and (late["e"] == len(m.idx) - 1).all()


def test_classification_thresholds_change_mix(m):
    ms = exits.market_state(m)
    base = exits.classify(ms["dd"].to_numpy(), ms["above200"].to_numpy(), exits.Thresholds())
    loose = exits.classify(ms["dd"].to_numpy(), ms["above200"].to_numpy(), exits.Thresholds(-0.10, -0.15))
    assert (loose == exits.GREEN).sum() > (base == exits.GREEN).sum()
    assert (loose == exits.RED).sum() > (base == exits.RED).sum()
    # 2022-10 바닥은 하락장, 2024-12 고점 근처는 상승장
    assert base[m.i_on_or_before("2022-10-13")] == exits.RED
    assert base[m.i_on_or_before("2024-12-16")] == exits.GREEN


def test_exit_rules_basic(m):
    ms = exits.market_state(m)
    th = exits.Thresholds()
    a = m.i_on_or_after("2015-01-02")
    e, st = exits.find_exit(m, a, exits.Rule("crash", 5, 15), ms, th)
    assert st == "grad" and ms["dd"].iloc[e] <= -0.20 and m.idx[e].year == 2020      # 코로나
    e1, _ = exits.find_exit(m, a, exits.Rule("random", 5, 15, seed=7), ms, th)
    e2, _ = exits.find_exit(m, a, exits.Rule("random", 5, 15, seed=7), ms, th)
    e3, _ = exits.find_exit(m, a, exits.Rule("random", 5, 15, seed=8), ms, th)
    assert e1 == e2 and m.idx[e1] >= m.idx[a] + pd.DateOffset(years=5) - pd.Timedelta(days=4)
    ef, sf = exits.find_exit(m, a, exits.Rule("fixed", 5), ms, th)
    assert sf == "fixed" and m.idx[ef] <= m.idx[a] + pd.DateOffset(years=5)
