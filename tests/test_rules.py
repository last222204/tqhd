"""검증 1 (RSI2 Wilder 알려진 값) · 검증 3 (상태 경계값) · 검증 4 (임계 가격 왕복) — 파이썬 쪽."""
import math

import pytest

import tqhd as T

DAY, NIGHT, HUNT = T.DAY, T.NIGHT, T.HUNT


# ── 검증 1: RSI2 ────────────────────────────────
def test_wilder_rsi2_known_values():
    # 변화: +1, -0.5, +1.5, -1  (손으로 계산한 값)
    rsi, ag, al = T.wilder_rsi2([10, 11, 10.5, 12, 11])
    assert math.isnan(rsi[0]) and math.isnan(rsi[1])
    assert ag[2] == 0.5 and al[2] == 0.25
    assert rsi[2] == pytest.approx(200 / 3, abs=1e-12)          # RS 2   → 66.67
    assert ag[3] == 1.0 and al[3] == 0.125
    assert rsi[3] == pytest.approx(800 / 9, abs=1e-12)          # RS 8   → 88.89
    assert ag[4] == 0.5 and al[4] == 0.5625
    assert rsi[4] == pytest.approx(800 / 17, abs=1e-12)         # RS 8/9 → 47.06


def test_wilder_rsi2_edges():
    rsi, _, _ = T.wilder_rsi2([1, 2, 3, 4])
    assert rsi[2] == 100 and rsi[3] == 100                       # 하락 없음 → 100
    rsi, _, _ = T.wilder_rsi2([4, 3, 2, 1])
    assert rsi[2] == 0 and rsi[3] == 0


def test_wilder_matches_pandas_ewm_after_warmup(prices):
    """독립 구현(pandas ewm, alpha=1/2)과 같은 값인지. 시작값 영향이 사라진 뒤 비교."""
    c = prices["qqq"]
    d = c.diff()
    g = d.clip(lower=0)
    l = (-d).clip(lower=0)
    g.iloc[2] = (g.iloc[1] + g.iloc[2]) / 2
    l.iloc[2] = (l.iloc[1] + l.iloc[2]) / 2
    eg = g.iloc[2:].ewm(alpha=0.5, adjust=False).mean()
    el = l.iloc[2:].ewm(alpha=0.5, adjust=False).mean()
    ref = 100 - 100 / (1 + eg / el)
    rsi, _, _ = T.wilder_rsi2(list(c))
    for i in range(len(c) - 300, len(c)):
        assert rsi[i] == pytest.approx(ref.iloc[i - 2], abs=1e-9)


# ── 검증 3: 경계값 ──────────────────────────────
def base(prev_state=NIGHT, prev_weight=0, ag=1.0, al=1.0, s199=19701.0):
    # 직전 49일 합 4900 → 50일선 닿는 가격 100, 직전 199일 합 19701 → 200일선 닿는 가격 99 (19900 이면 100)
    return {"qqq_prev_close": 100.0, "sum_prev_49": 4900.0, "sum_prev_199": s199,
            "wilder_avg_gain": ag, "wilder_avg_loss": al, "prev_state": prev_state, "prev_weight": prev_weight}


# ① 낮은 초과(>)만. 두 선 다 같거나 아래면 밤.
def test_rule1_both_lines_equal_is_night():
    e = T.evaluate(base(s199=19900.0), 100.0)                    # 50일선 = 200일선 = 종가
    assert e["sma50"] == 100.0 and e["sma200"] == 100.0 and e["night"] and e["state"] == NIGHT
    e = T.evaluate(base(s199=19900.0), 100.000001)               # 둘 다 살짝 위 → 낮
    assert not e["night"] and e["state"] == DAY


def test_rule1_one_equal_other_below_is_night():
    e = T.evaluate(base(), 99.0)                                 # 200일선과 같음, 50일선 아래
    assert e["sma200"] == 99.0 and e["sma50"] > 99.0 and e["night"]
    e = T.evaluate(base(s199=20099.0), 100.0)                    # 50일선과 같음, 200일선 아래
    assert e["sma50"] == 100.0 and e["sma200"] > 100.0 and e["night"]


def test_rule1_one_above_is_day_both_below_is_night():
    b = base()
    e = T.evaluate(b, 100.0)                                     # 50일선과 같음, 200일선은 위(초과) → 낮
    assert e["sma50"] == 100.0 and 100.0 > e["sma200"] and not e["night"]
    assert not T.evaluate(b, 99.5)["night"]                      # 200일선만 위 → 낮
    assert T.evaluate(b, 98.999999)["night"]                     # 둘 다 아래 → 밤
    assert T.is_night(3, 3, 3) and T.is_night(1, 2, 3) and T.is_night(3, 3, 4)
    assert not T.is_night(3.0000001, 3, 3) and not T.is_night(3, 2, 4) and not T.is_night(3, 4, 2)


# ② 비중은 RSI2 가 정한다 (양방향). <5 → 100, 5~15 → 50, 15~50 → 유지(사냥 중), >50 → 전량 매도.
RULE2 = [
    (DAY, 100, False, 3, (DAY, 100)),
    (DAY, 100, True, 30, (NIGHT, 0)),
    (DAY, 100, True, 14.99, (HUNT, 50)),                         # 밤이 되는 날에도 바로 사냥
    (DAY, 100, True, 4.99, (HUNT, 100)),
    (NIGHT, 0, True, 15, (NIGHT, 0)),                            # 정확히 15 는 진입 아님 (15~50 구간)
    (NIGHT, 0, True, 14.999, (HUNT, 50)),
    (NIGHT, 0, True, 5, (HUNT, 50)),                             # 정확히 5 는 50% (5 미만만 100%)
    (NIGHT, 0, True, 4.999, (HUNT, 100)),
    (HUNT, 50, True, 4.9, (HUNT, 100)),                          # 50% → 5 아래 → 100%
    (HUNT, 100, True, 10, (HUNT, 50)),                           # 100% → 5~15 로 올라옴 → 50%
    (HUNT, 100, True, 5, (HUNT, 50)),                            # 정확히 5 도 50%
    (HUNT, 100, True, 14.99, (HUNT, 50)),
    (HUNT, 100, True, 15, (HUNT, 100)),                          # 15~50 → 직전 비중 유지
    (HUNT, 50, True, 15, (HUNT, 50)),
    (HUNT, 100, True, 30, (HUNT, 100)),                          # 시간 제한 없음
    (HUNT, 50, True, 50, (HUNT, 50)),                            # 정확히 50 은 유지
    (HUNT, 100, True, 50, (HUNT, 100)),
    (HUNT, 50, True, 50.01, (NIGHT, 0)),                         # 50 초과 → 전량 매도
    (HUNT, 100, True, 50.01, (NIGHT, 0)),
    (HUNT, 50, False, 80, (DAY, 100)),                           # 사냥 중 선 회복 → 청산 없이 낮
    (HUNT, 100, False, 3, (DAY, 100)),
    (NIGHT, 0, False, 3, (DAY, 100)),
]


@pytest.mark.parametrize("prev, w, night, rsi, expect", RULE2)
def test_rule2_weight_follows_rsi(prev, w, night, rsi, expect):
    assert T.next_state(prev, w, night, rsi) == expect


def test_rule2_round_trip_100_50_100():
    """한 사냥 안에서 100 → 50 → 100 → 50 → 유지 → 청산."""
    s, w, seen = NIGHT, 0, []
    for rsi in (3, 10, 4, 12, 30, 45, 51):
        s, w = T.next_state(s, w, True, rsi)
        seen.append((s, w))
    assert seen == [(HUNT, 100), (HUNT, 50), (HUNT, 100), (HUNT, 50), (HUNT, 50), (HUNT, 50), (NIGHT, 0)]


# ③ 가격은 배당조정(수정주가) 종가
def test_rule3_fetch_uses_adjusted_close(monkeypatch):
    import pandas as pd
    import yfinance as yf
    import update_state as U
    seen = {}

    def fake(symbol, **kw):
        seen.update(kw)
        idx = pd.DatetimeIndex(["2026-11-24", "2026-11-25"])
        return pd.DataFrame({"Close": [1.0, 2.0]}, index=idx)
    monkeypatch.setattr(yf, "download", fake)
    s = U.fetch_daily("QQQ")
    assert seen["auto_adjust"] is True and list(s) == [1.0, 2.0]


# ── 검증 4: 임계 가격 왕복 ──────────────────────
@pytest.mark.parametrize("ag, al", [(1.0, 1.0), (5.37, 8.19), (0.0, 3.0), (4.0, 0.0), (0.01, 9.0)])
@pytest.mark.parametrize("target", [5.0, 15.0, 50.0])
def test_rsi_price_round_trip(ag, al, target):
    p = T.rsi_price(100.0, ag, al, target)
    lo, _, _ = T.rsi_step(100.0, ag, al, p * (1 - 1e-9))
    hi, _, _ = T.rsi_step(100.0, ag, al, p * (1 + 1e-9))
    at, _, _ = T.rsi_step(100.0, ag, al, p)
    assert at == pytest.approx(target, abs=1e-9)
    assert lo < target < hi


def test_cross_price_round_trip():
    b = base(prev_state=DAY, prev_weight=100, ag=3.0, al=1.0)    # RSI 높음 → 사냥 아님
    p50, p200 = T.cross_price(4900.0, 50), T.cross_price(19701.0, 200)
    lower = min(p50, p200)
    assert T.evaluate(b, lower * (1 - 1e-9))["state"] == NIGHT
    assert T.evaluate(b, lower * (1 + 1e-9))["state"] == DAY
    assert T.evaluate(b, lower)["state"] == NIGHT                # 정확히 그 가격 = 선과 같음 → 밤
