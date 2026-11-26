"""코랩 백테스트 숫자와 검산 (검산 모드). ±3% 넘게 다르면 엔진을 의심한다.

조건: 실제 상품, 1,000만 원 + 매월 17일 100만 원, 5년 뒤 전부 매도 세후,
      시작 월 2010-03 ~ 2021-11 각 달 첫 거래일 (141개), 종료 = 시작 + 5년 직전 거래일.
저장된 시세(data/t6.db)를 쓴다. 시세가 없으면 건너뛴다.
"""
import numpy as np
import pandas as pd
import pytest

from t6 import store
from t6.sim import data, engine

EXPECTED = {   # 전략: (평균 배수, 최악, 원금손실 비율)
    engine.UMBRELLA: (2.35, 1.21, 0.00),
    "TQQQ": (2.82, 0.90, 0.01),
    "QLD": (2.15, 1.15, 0.00),
    "QQQ": (1.55, 1.20, 0.00),
}


@pytest.fixture(scope="module")
def market():
    store.init_db()
    for s in ["QQQ", "TQQQ", "QLD", "BIL", "SGOV", "^IRX"]:
        last = store.last_price_date(s)
        if last is None or last < "2026-11-01":
            pytest.skip("저장된 시세가 부족합니다. 사이트에서 시세를 먼저 받으세요.")
    return data.build()


def colab_windows(m):
    out = []
    for y in range(2010, 2022):
        for mo in range(1, 13):
            if (2010, 3) <= (y, mo) <= (2021, 11):
                a = m.i_on_or_after(f"{y}-{mo:02d}-01")
                b = m.i_on_or_before(m.idx[a] + pd.DateOffset(years=5))
                out.append((a, b))
    return out


@pytest.mark.parametrize("strategy", list(EXPECTED))
def test_matches_colab(market, strategy):
    m = market
    pay = data.pay_mask(m, 17)
    wins = colab_windows(m)
    assert len(wins) == 141
    mult = np.array([
        engine.run(m, strategy, engine.Params(start=m.idx[a], end=m.idx[b], colab=True), pay, (a, b)).multiple
        for a, b in wins
    ])
    mean, worst, loss = EXPECTED[strategy]
    assert abs(mult.mean() / mean - 1) < 0.03, f"평균 {mult.mean():.3f} vs 코랩 {mean}"
    assert abs(mult.min() / worst - 1) < 0.03, f"최악 {mult.min():.3f} vs 코랩 {worst}"
    assert abs((mult < 1).mean() - loss) <= 0.01
    # 검산 구간에는 가상 데이터가 없어야 한다
    r = engine.run(m, strategy, engine.Params(start=m.idx[wins[0][0]], end=m.idx[wins[0][1]], colab=True),
                   pay, wins[0])
    assert not r.synthetic
