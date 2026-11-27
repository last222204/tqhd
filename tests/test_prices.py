"""맨 위 가격 칸 (bestPrices): 정규장 → 프리·애프터 → 선물 추정 → 확정 종가. 판정과는 무관한 '보기용' 값."""
from datetime import datetime, timezone

import pytest


def ms(y, mo, d, h, mi=0, s=0):
    return int(datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc).timestamp() * 1000)


def sec(*a):
    return ms(*a) // 1000


def tr(p, t):
    return None if p is None else {"price": p, "time": t}


def stock(reg, reg_t, last=None, last_t=None, close=None, close_t=None):
    return {"price": reg, "time": reg_t, "prev_close": None, "last": tr(last, last_t), "regular_close": tr(close, close_t)}


def quotes(qqq=None, tqqq=None, nq=None, nq_t=None, bars=()):
    q = {"QQQ": qqq, "TQQQ": tqqq, "USDKRW": None,
         "NQ": None if nq is None else {"price": nq, "time": nq_t, "prev_close": None, "bars": [list(b) for b in bars]}}
    return {"fetched_at": 0, "quotes": q, "errors": {}}


CLOSE_1125 = sec(2026, 11, 25, 21, 0, 1)        # 11-25 정규장 종가가 찍힌 시각


@pytest.fixture
def st(state):
    return state


def best(js, st, q, now):
    return js("bestPrices", st, q, now)


def test_regular(js, st):
    now = ms(2026, 11, 27, 16, 0)
    q = quotes(stock(640.0, now // 1000 - 20, 640.0, now // 1000 - 60), stock(46.5, now // 1000 - 20, 46.5, now // 1000 - 60))
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "regular"
    assert b["qqq"]["base"] == pytest.approx(st["qqq_prev_close"])          # 정규장 중 % 는 전일(11-25) 종가 대비
    assert b["qqq"]["chg"] == pytest.approx(640.0 / st["qqq_prev_close"] - 1)
    assert b["tqqq"]["est"] is False


def test_premarket_fresh(js, st):
    now = ms(2026, 11, 27, 9, 40)
    q = quotes(stock(633.93, CLOSE_1125, 651.38, sec(2026, 11, 27, 9, 38)),
               stock(45.28, CLOSE_1125, 48.93, sec(2026, 11, 27, 9, 37)))
    b = best(js, st, q, now)
    assert b["phase"] == "pre"
    assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "pre"
    assert b["qqq"]["price"] == 651.38 and b["tqqq"]["price"] == 48.93
    assert b["qqq"]["base"] == 633.93 and b["qqq"]["baseDate"] == "2026-11-25"
    assert b["qqq"]["chg"] == pytest.approx(651.38 / 633.93 - 1)
    assert b["qqq"]["t"] == sec(2026, 11, 27, 9, 38) * 1000


def test_premarket_tqqq_frozen_uses_qqq_times_three(js, st):
    now = ms(2026, 11, 27, 9, 40)
    q = quotes(stock(633.93, CLOSE_1125, 651.38, sec(2026, 11, 27, 9, 38)),
               stock(45.28, CLOSE_1125, 48.0, sec(2026, 11, 27, 9, 20)))      # 20분 전 → 멈춤
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == "pre" and b["qqq"]["est"] is False
    t = b["tqqq"]
    assert t["kind"] == "pre" and t["est"] is True and t["via"] == "qqq"
    assert t["price"] == pytest.approx(45.28 * (1 + 3 * (651.38 / 633.93 - 1)))
    assert t["chg"] == pytest.approx(3 * (651.38 / 633.93 - 1))


def test_afterhours_percent_from_todays_close(js, st):
    now = ms(2026, 12, 1, 22, 0)                                              # 동부 17:00
    close_t = sec(2026, 12, 1, 21, 0, 1)
    q = quotes(stock(650.0, close_t, 652.6, sec(2026, 12, 1, 21, 59), 650.0, close_t),
               stock(47.0, close_t, 47.6, sec(2026, 12, 1, 21, 58), 47.0, close_t))
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "post"
    assert b["qqq"]["base"] == 650.0 and b["qqq"]["baseDate"] == "2026-12-01"   # state(11-25) 를 기다리지 않음
    assert b["qqq"]["chg"] == pytest.approx(652.6 / 650.0 - 1)
    assert b["tqqq"]["chg"] == pytest.approx(47.6 / 47.0 - 1)


def test_night_futures_anchor_is_last_afterhours_trade(js, st):
    now = ms(2026, 12, 2, 3, 0)                                               # 동부 22:00, 시간외 없음
    close_t = sec(2026, 12, 1, 21, 0, 1)
    t0 = sec(2026, 12, 2, 0, 59)                                              # 애프터장 마지막 체결 (동부 19:59)
    bars = [(sec(2026, 12, 2, 0, 45), 26500.0), (sec(2026, 12, 2, 0, 50), 26520.0), (sec(2026, 12, 2, 0, 55), 26510.0),
            (sec(2026, 12, 2, 1, 0), 26600.0), (sec(2026, 12, 2, 2, 50), 26700.0)]
    q = quotes(stock(650.0, close_t, 652.0, t0, 650.0, close_t), stock(47.0, close_t, 47.5, t0, 47.0, close_t),
               nq=26775.0, nq_t=sec(2026, 12, 2, 2, 52), bars=bars)
    b = best(js, st, q, now)
    assert b["phase"] == "none"
    Q, T = b["qqq"], b["tqqq"]
    assert Q["kind"] == T["kind"] == "futures" and Q["est"] and T["est"]
    assert Q["anchor"]["p0"] == 652.0 and Q["anchor"]["t0"] == t0 * 1000
    assert Q["anchor"]["f0"] == 26510.0                                       # 00:55 봉 (01:00 에 끝남 = t0 바로 전)
    assert Q["price"] == pytest.approx(652.0 * 26775.0 / 26510.0)
    assert T["price"] == pytest.approx(47.5 * (1 + 3 * (Q["price"] / 652.0 - 1)))
    assert Q["chg"] == pytest.approx(Q["price"] / 650.0 - 1)                  # % 는 정규장 종가 대비
    assert Q["t"] == sec(2026, 12, 2, 2, 52) * 1000


def test_anchor_numbers(js, st):
    """P0=100, F0=20000, F=20200 → QQQ 101.00, TQQQ = 최근가 × 1.03"""
    now = ms(2026, 12, 2, 3, 0)
    t0 = sec(2026, 12, 2, 0, 59)
    q = quotes(stock(99.0, sec(2026, 12, 1, 21, 0, 1), 100.0, t0, 99.0, sec(2026, 12, 1, 21, 0, 1)),
               stock(50.0, sec(2026, 12, 1, 21, 0, 1), 50.0, t0 - 120, 50.0, sec(2026, 12, 1, 21, 0, 1)),
               nq=20200.0, nq_t=sec(2026, 12, 2, 2, 55), bars=[(sec(2026, 12, 2, 0, 50), 19990.0), (sec(2026, 12, 2, 0, 55), 20000.0)])
    b = best(js, st, q, now)
    assert round(b["qqq"]["price"], 2) == 101.00
    assert b["tqqq"]["price"] == pytest.approx(50.0 * 1.03)


@pytest.mark.parametrize("now, why", [
    (ms(2026, 11, 28, 12, 0), "weekend"),
    (ms(2026, 11, 26, 15, 0), "thanksgiving"),
])
def test_weekend_and_holiday_futures_alive(js, st, now, why):
    t0 = sec(2026, 11, 26, 0, 59)                                             # 11-25 애프터장 마지막
    q = quotes(stock(633.93, CLOSE_1125, 636.62, t0), stock(45.28, CLOSE_1125, 45.93, t0),
               nq=26400.0, nq_t=now // 1000 - 600, bars=[(sec(2026, 11, 26, 0, 50), 26300.0), (sec(2026, 11, 26, 0, 55), 26310.0)])
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == "futures", why
    assert b["qqq"]["price"] == pytest.approx(636.62 * 26400.0 / 26310.0)
    assert b["qqq"]["base"] == pytest.approx(633.93, abs=1e-4)


@pytest.mark.parametrize("now", [ms(2026, 11, 28, 12, 0), ms(2026, 11, 26, 15, 0)])
def test_weekend_and_holiday_futures_frozen_is_close(js, st, now):
    t0 = sec(2026, 11, 26, 0, 59)
    q = quotes(stock(633.93, CLOSE_1125, 636.62, t0), stock(45.28, CLOSE_1125, 45.93, t0),
               nq=26400.0, nq_t=now // 1000 - 3 * 3600, bars=[(sec(2026, 11, 26, 0, 55), 26310.0)])   # 3시간째 그대로
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "close"
    assert b["qqq"]["price"] == pytest.approx(633.93, abs=1e-4) and b["qqq"]["baseDate"] == "2026-11-25"
    assert b["tqqq"]["price"] == pytest.approx(45.28, abs=1e-4)


def test_proxy_down_is_close(js, st):
    for now in (ms(2026, 11, 27, 9, 40), ms(2026, 11, 27, 16, 0), ms(2026, 11, 28, 12, 0)):
        b = best(js, st, None, now)
        assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "close"
        assert b["qqq"]["price"] == pytest.approx(st["qqq_prev_close"])
        assert b["tqqq"]["price"] == pytest.approx(st["tqqq_prev_close"])
        assert b["qqq"]["baseDate"] == st["as_of"]
        assert b["tqqq"]["chg"] is None                                       # TQQQ 그 전 종가는 state 에 없음


def test_futures_without_bars_falls_back_to_state_anchor(js, st):
    """5분봉이 기준 시각을 못 덮으면 (야후 연휴 공백) 휴장 갭 칸과 같은 state.json 기준점."""
    now = ms(2026, 11, 27, 8, 50)                                             # 프리장 전 (동부 03:50)
    q = quotes(stock(633.93, CLOSE_1125, 636.62, sec(2026, 11, 26, 0, 59)), stock(45.28, CLOSE_1125, 45.93, sec(2026, 11, 26, 0, 59)),
               nq=26800.0, nq_t=now // 1000 - 300, bars=[])
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == "futures" and b["qqq"]["anchor"]["fromState"] is True
    assert b["qqq"]["price"] == pytest.approx(st["qqq_prev_close"] * 26800.0 / st["nq_prev_settle"])
    assert b["tqqq"]["price"] == pytest.approx(st["tqqq_prev_close"] * (1 + 3 * (b["qqq"]["price"] / st["qqq_prev_close"] - 1)))


def test_regular_stale_goes_to_futures_not_old_price(js, st):
    now = ms(2026, 11, 27, 16, 0)
    old = now // 1000 - 900                                                   # 15분 전 정규장 가격 = 멈춤
    q = quotes(stock(640.0, old, 640.0, old), stock(46.5, old, 46.5, old),
               nq=26500.0, nq_t=now // 1000 - 60, bars=[(old - 300, 26400.0)])
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == "futures"
    assert b["qqq"]["price"] == pytest.approx(640.0 * 26500.0 / 26400.0)


def test_real_yahoo_premarket_capture(js, st):
    """실제 야후 1분봉(2026-11-27 프리장) 을 프록시 쌍둥이로 읽어 넣으면 pre 가 나온다."""
    import json
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "tools"))
    import dev_server as D
    fx = lambda n: json.loads((root / "tests" / "fixtures" / f"yahoo_{n}.json").read_text(encoding="utf-8"))  # noqa: E731
    q = {"fetched_at": 0, "errors": {}, "quotes": {"QQQ": D.parse_for("QQQ", fx("QQQ_1m_pre")), "TQQQ": D.parse_for("TQQQ", fx("TQQQ_1m_pre")),
                                                   "NQ": D.parse_for("NQ", fx("NQ_F_5m")), "USDKRW": None}}
    now = q["quotes"]["QQQ"]["last"]["time"] * 1000 + 60_000
    b = best(js, st, q, now)
    assert b["qqq"]["kind"] == b["tqqq"]["kind"] == "pre"
    assert b["qqq"]["base"] == pytest.approx(633.93)
