"""RSI2 · 사냥: 검산 숫자, 역산, 사냥 회차, 확인 시각(서머타임), 휴장일, 실시간 없음."""
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from t6 import market_time as mt
from t6 import rsi2, store
from t6.config import RISK_OFF
from t6.strategy import signal_frame

KST = mt.KST


def hm(dt):
    d = dt.astimezone(KST)
    return (d.month, d.day, d.hour, d.minute)


@pytest.fixture(scope="module")
def real():
    store.init_db()
    q = store.load_prices("QQQ")
    if q.empty or q.index[-1] < pd.Timestamp("2026-11-13"):
        pytest.skip("2026-11-13 까지의 시세가 없습니다")
    q = q.loc[:"2026-11-13"]
    sf = signal_frame(q)
    return q, sf


# ── 검산 숫자 (2026-11-13 종가까지 → 다음 거래일 기준) ─
def test_check_numbers(real):
    q, _ = real
    lv = rsi2.levels(q["adj_close"])
    assert abs(lv.close - 679.89) < 0.01
    assert abs(lv.buy_rsi - 659.54) < 0.5 and abs(lv.refuge - 681.51) < 0.5
    assert abs(lv.buy - 659.54) < 0.5 and abs(lv.sell - 682.39) < 0.5


def test_signal_prices_are_exact_boundaries(real):
    q, _ = real
    lv = rsi2.levels(q["adj_close"])
    nxt = (lambda p: rsi2.rsi_next(p, lv.close, lv.au, lv.ad))
    assert nxt(lv.buy_rsi - 0.01) < 10 < nxt(lv.buy_rsi + 0.01)
    assert nxt(lv.sell - 0.01) < 50 < nxt(lv.sell + 0.01)


def test_rsi_next_matches_full_recursion():
    rng = np.random.default_rng(0)
    c = list(100 * np.cumprod(1 + rng.normal(0, 0.01, 60)))
    st_ = rsi2.rsi2_state(c)
    for t in (5, 20, 59):
        _, A0, D0 = st_[t - 1]
        assert math.isclose(rsi2.rsi_next(c[t], c[t - 1], A0, D0), st_[t][0], rel_tol=1e-12)


def test_reverse_check_every_day(real):
    q, sf = real
    rc = rsi2.reverse_check(q["adj_close"], sf["signal"].map(lambda s: None if s is None else s == RISK_OFF))
    bad = rc[~rc["ok"]]
    assert len(rc) > 6000 and rc["ok"].mean() >= 0.99, bad.head(20).to_string()


# ── 사냥 회차 ────────────────────────────────────
def test_real_hunt_2026_11_05_ends_in_two_days(real):
    q, sf = real
    h = rsi2.hunts(rsi2.rsi_series(q["adj_close"]), sf["signal"] == RISK_OFF)
    row = h[h["entry"] == pd.Timestamp("2026-11-05")].iloc[0]
    assert row["exit"] == pd.Timestamp("2026-11-09") and row["days"] == 2 and row["reason"] == "RSI2>50"


def _hunts(r, f):
    idx = mt.sessions()[(mt.sessions() >= "2026-02-02")][: len(r)]
    return rsi2.hunts(pd.Series(r, index=idx, dtype=float), pd.Series(f, index=idx)), idx


def test_five_day_exit_and_reset():
    # 0일 진입(RSI 5) → 1~4일 RSI 30 → 5일째 RSI 30 이면 종료
    h, idx = _hunts([5, 30, 30, 30, 30, 30, 30], [True] * 7)
    assert h.iloc[0]["exit"] == idx[5] and h.iloc[0]["reason"] == "5일"
    # 5일째 RSI 가 아직 10 미만 → 계속, 그날부터 다시 5일 (10일째 종료)
    h, idx = _hunts([5, 30, 30, 30, 30, 8, 30, 30, 30, 30, 30, 30], [True] * 12)
    assert h.iloc[0]["count_from"] == idx[5] and h.iloc[0]["exit"] == idx[10] and h.iloc[0]["days"] == 10


def test_t6_sun_ends_hunt_keeping_tqqq():
    h, idx = _hunts([5, 30, 30], [True, True, False])
    assert h.iloc[0]["exit"] == idx[2] and h.iloc[0]["reason"].startswith("T6 맑음")
    h, idx = _hunts([5, 30, 60], [True, True, True])
    assert h.iloc[0]["exit"] == idx[2] and h.iloc[0]["reason"] == "RSI2>50"
    h, idx = _hunts([30, 5, 20], [True, True, True])                 # 진행 중
    assert h.iloc[0]["entry"] == idx[1] and pd.isna(h.iloc[0]["exit"])


# ── 시간 · 휴장 ──────────────────────────────────
def test_check_time_dst_and_early_close():
    assert hm(rsi2.check_time(date(2026, 3, 6))) == (3, 7, 5, 50)      # 겨울 (금요일 장)
    assert hm(rsi2.check_time(date(2026, 3, 9))) == (3, 10, 4, 50)     # 서머타임 시작 주 월요일
    assert hm(rsi2.check_time(date(2026, 11, 2))) == (11, 3, 5, 50)    # 서머타임 끝난 주
    assert hm(rsi2.check_time(date(2026, 11, 27))) == (11, 28, 2, 50)  # 추수감사절 다음 날 조기 폐장


def test_today_session_hidden_on_holidays_and_weekends():
    assert rsi2.today_session(datetime(2026, 11, 27, 1, 0, tzinfo=KST)) is None    # 11/26(목) 추수감사절 ET 낮
    assert rsi2.today_session(datetime(2026, 11, 15, 12, 0, tzinfo=KST)) is None   # 일요일
    assert rsi2.today_session(datetime(2026, 11, 17, 6, 30, tzinfo=KST)) is None   # 월요일 장 마감 뒤
    assert rsi2.today_session(datetime(2026, 11, 16, 23, 0, tzinfo=KST)) == date(2026, 11, 16)
    s = date(2026, 11, 16)
    assert not rsi2.market_open(datetime(2026, 11, 16, 23, 0, tzinfo=KST), s)       # 개장 전
    assert rsi2.market_open(datetime(2026, 11, 17, 1, 0, tzinfo=KST), s)


# ── 사냥 칸 ──────────────────────────────────────
def _lv():
    """검산 숫자와 같은 모양의 가짜 기준: 기준 가격들은 같은 공식으로 계산해서 서로 맞게."""
    C0, A0, D0 = 679.89, 4.0, 9.0
    buy_rsi, sell, refuge = rsi2.signal_prices(C0, A0, D0, 681.51 * 49, 700.0 * 199)
    return rsi2.Levels(date(2026, 11, 13), C0, rsi2.rsi_next(C0, C0, A0, D0), A0, D0, buy_rsi, refuge,
                       min(buy_rsi, refuge), sell, 57.68)


EMPTY = pd.DataFrame(columns=["entry", "exit", "reason", "days", "count_from"])


def test_hunt_view_wait_enter_tight_and_no_live():
    s, lv = date(2026, 11, 16), _lv()
    B = lv.buy
    assert rsi2.hunt_view(lv, True, EMPTY, None, B * 0.98, set()).kind is None       # 휴장 → 없음
    assert rsi2.hunt_view(lv, True, EMPTY, s, None, set()).kind is None             # 실시간 없음 → 대기·진입 없음
    assert rsi2.hunt_view(lv, False, EMPTY, s, B * 0.98, set()).kind is None         # 맑음 → 없음
    assert rsi2.hunt_view(lv, True, EMPTY, s, B * 1.008, set()).kind == "wait"      # 기준 위 0.8%
    assert rsi2.hunt_view(lv, True, EMPTY, s, B * 1.016, set()).kind is None        # 1.6% 위 → 아직
    v = rsi2.hunt_view(lv, True, EMPTY, s, B * 0.98, set())
    assert v.kind == "enter" and v.live_rsi < 10 and not v.tight
    v = rsi2.hunt_view(lv, True, EMPTY, s, B * 0.999, set())
    assert v.kind == "enter" and v.tight                                            # 0.3% 안 → 애매


def test_hunt_view_hunting_exit_and_skip():
    lv = _lv()
    ep = pd.DataFrame([{"entry": pd.Timestamp("2026-11-05"), "exit": None, "reason": "진행 중", "days": 1,
                        "count_from": pd.Timestamp("2026-11-05")}])
    v = rsi2.hunt_view(lv, True, ep, date(2026, 11, 9), lv.buy, set())
    assert v.kind == "hunting" and v.day == 2 and v.day5 == date(2026, 11, 12)
    assert rsi2.hunt_view(lv, True, ep, date(2026, 11, 9), lv.sell + 1, set()).kind == "exit"     # RSI2>50
    v = rsi2.hunt_view(lv, True, ep, date(2026, 11, 12), None, set())
    assert v.kind == "exit" and v.note == "5일째"                                         # 실시간 없어도 5일째
    assert rsi2.hunt_view(lv, True, ep, date(2026, 11, 9), lv.buy, {"2026-11-05"}).kind is None   # 건너뜀


def test_skip_storage(tmp_path):
    db = tmp_path / "s.db"
    rsi2.set_skip(date(2026, 11, 5), True, db)
    assert rsi2.skipped(db) == {"2026-11-05"}
    rsi2.set_skip(date(2026, 11, 5), False, db)
    assert rsi2.skipped(db) == set()


# ── 오늘 화면: 장중 (실시간 없음 / 실시간 있음) ───
@pytest.mark.parametrize("price, expect", [(None, "실시간 없음"), (640.0, "사냥 진입")])
def test_today_page_live(monkeypatch, real, price, expect):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from t6 import live, ui
    from t6.config import ROOT

    monkeypatch.setattr(ui, "now_utc", lambda: datetime(2026, 11, 17, 1, 0, tzinfo=KST))   # 월요일 장중
    monkeypatch.setattr(live, "last_price", lambda sym: price)
    st.cache_data.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    at.switch_page("views/today.py")
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert expect in text and "RSI2 확정" in text and "사냥 확인" in text
    st.cache_data.clear()


def test_today_page_holiday_hides_hunt(monkeypatch, real):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from t6 import live, ui
    from t6.config import ROOT

    monkeypatch.setattr(ui, "now_utc", lambda: datetime(2026, 11, 27, 1, 0, tzinfo=KST))   # 추수감사절 낮 (ET)
    monkeypatch.setattr(live, "last_price", lambda sym: 640.0)
    st.cache_data.clear()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    at.switch_page("views/today.py")
    at.run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "RSI2 확정" in text
    assert "🦇" not in text and "사냥 확인" not in text and "실시간" not in text
    st.cache_data.clear()
