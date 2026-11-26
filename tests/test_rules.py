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
def base(prev_state=NIGHT, prev_weight=0, ag=1.0, al=1.0):
    # 직전 49일 합 4900 → 50일선 닿는 가격 100, 직전 199일 합 19701 → 200일선 닿는 가격 99
    return {"qqq_prev_close": 100.0, "sum_prev_49": 4900.0, "sum_prev_199": 19701.0,
            "wilder_avg_gain": ag, "wilder_avg_loss": al, "prev_state": prev_state, "prev_weight": prev_weight}


def test_exactly_on_line_is_day():
    b = base()
    e = T.evaluate(b, 100.0)                                     # 정확히 50일선 위 (같음)
    assert e["sma50"] == 100.0 and not e["night"] and e["state"] == DAY
    e = T.evaluate(b, 99.0)                                      # 정확히 200일선과 같음, 50일선 아래
    assert e["sma200"] == 99.0 and not e["night"] and e["state"] == DAY


def test_both_below_is_night_one_above_is_day():
    b = base()
    assert T.evaluate(b, 98.999999)["night"]                     # 둘 다 아래 → 밤
    assert not T.evaluate(b, 99.5)["night"]                      # 200일선만 위 → 낮
    assert T.is_night(1, 2, 3) and not T.is_night(2.5, 2, 3) and not T.is_night(3, 3, 2)


@pytest.mark.parametrize("prev, w, night, rsi, expect", [
    (DAY, 100, False, 3, (DAY, 100)),
    (DAY, 100, True, 30, (NIGHT, 0)),
    (DAY, 100, True, 14.99, (HUNT, 50)),                         # 밤이 되는 날에도 바로 사냥
    (DAY, 100, True, 4.99, (HUNT, 100)),
    (NIGHT, 0, True, 15, (NIGHT, 0)),                            # 정확히 15 는 진입 아님
    (NIGHT, 0, True, 5, (HUNT, 50)),                             # 정확히 5 는 절반
    (HUNT, 50, True, 4.9, (HUNT, 100)),                          # 절반 → 전액
    (HUNT, 100, True, 30, (HUNT, 100)),                          # 기다림 (시간 제한 없음)
    (HUNT, 50, True, 50, (HUNT, 50)),                            # 정확히 50 은 청산 아님
    (HUNT, 50, True, 50.01, (NIGHT, 0)),
    (HUNT, 50, False, 80, (DAY, 100)),                           # 사냥 중 선 회복 → 청산 없이 낮
    (NIGHT, 0, False, 3, (DAY, 100)),
])
def test_next_state(prev, w, night, rsi, expect):
    assert T.next_state(prev, w, night, rsi) == expect


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
    assert T.evaluate(b, lower)["state"] == DAY                  # 정확히 그 가격은 '같음' → 낮
