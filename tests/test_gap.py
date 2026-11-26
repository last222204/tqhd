"""월요일 출발가 점치기: 시간표(서머타임)·휴장·예상 공식·빠진 재료·재현성·장부. 인터넷 없이 돈다."""
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from t6 import gap, gap_data
from t6 import market_time as mt
from t6.config import ROOT

KST = mt.KST


def hm(dt):
    d = dt.astimezone(KST)
    return (d.month, d.day, d.hour, d.minute)


# ── 시간표 ───────────────────────────────────────
def test_times_winter():
    t = gap.times(datetime(2026, 11, 14, 10, 0, tzinfo=KST))     # 토요일 아침
    assert t.us_anchor == date(2026, 11, 13) and t.us_next == date(2026, 11, 16) and t.weekend
    assert hm(t.us_close) == (11, 14, 6, 0) and hm(t.ah_end) == (11, 14, 10, 0)
    assert hm(t.fut_open) == (11, 16, 8, 0)          # 일요일 18:00 ET = 월 08:00 KST (겨울)
    assert hm(t.us_open) == (11, 16, 23, 30) and not t.us_monday_holiday


def test_times_summer():
    t = gap.times(datetime(2026, 7, 11, 10, 0, tzinfo=KST))
    assert hm(t.us_close) == (7, 11, 5, 0) and hm(t.ah_end) == (7, 11, 9, 0)
    assert hm(t.fut_open) == (7, 13, 7, 0) and hm(t.us_open) == (7, 13, 22, 30)


def test_times_dst_change_weekend():
    t = gap.times(datetime(2026, 3, 7, 12, 0, tzinfo=KST))       # 3/8(일) 서머타임 시작
    assert hm(t.us_close) == (3, 7, 6, 0) and hm(t.fut_open) == (3, 9, 7, 0) and hm(t.us_open) == (3, 9, 22, 30)


def test_us_monday_holiday():
    t = gap.times(datetime(2026, 1, 17, 10, 0, tzinfo=KST))      # 1/19 마틴 루터 킹 데이
    assert t.us_monday_holiday and t.us_next == date(2026, 1, 20)


# ── 예상 공식 ────────────────────────────────────
def test_estimate_priority_and_formula():
    e = gap.estimate_gap(ah=-0.008, perp_close=-0.007, perp_after_ah=0.001, nq=0.004)
    assert e.method == "nq" and e.gap == 0.004                       # 선물이 열렸으면 최우선
    e = gap.estimate_gap(ah=-0.008, perp_close=-0.007, perp_after_ah=0.001)
    assert e.method == "ah_perp" and math.isclose(e.gap, (1 - 0.008) * (1 + 0.001) - 1)
    e = gap.estimate_gap(perp_close=-0.007)
    assert e.method == "perp" and e.gap == -0.007
    e = gap.estimate_gap(ah=-0.008, perp_after_ah=None)
    assert e.method == "ah" and e.gap == -0.008
    e = gap.estimate_gap(ah=None, perp_close=float("nan"))          # 재료가 없으면 종가 그대로
    assert e.method == "none" and e.gap == 0.0


def test_open_prices_tqqq_three_times():
    e = gap.estimate_gap(ah=-0.01)
    q, t = gap.open_prices(e, 680.0, 57.68)
    assert math.isclose(q, 680 * 0.99) and math.isclose(t, 57.68 * (1 - 0.03))
    assert gap.open_prices(e, None, None) == (None, None)


# ── 과거 백테스트 · 재현성 ───────────────────────
def _fake():
    sess = mt.sessions()
    sess = sess[(sess >= "2026-01-01") & (sess <= "2026-03-31")]
    rng = np.random.default_rng(3)
    close = pd.Series(600 * np.cumprod(1 + rng.normal(0, 0.01, len(sess))), index=sess)
    qqq = pd.DataFrame({"open": close.shift(1).fillna(600) * (1 + rng.normal(0, 0.005, len(sess))), "close": close})
    hours = pd.date_range("2025-12-28", "2026-04-02", freq="1h", tz="UTC")
    perp = pd.Series(25000 * np.cumprod(1 + rng.normal(0, 0.001, len(hours))), index=hours)
    m60 = pd.DataFrame({"close": close.reindex(hours.tz_convert(mt.ET).normalize().tz_localize(None)).to_numpy()},
                       index=hours.tz_convert(mt.ET)).dropna()
    return sess, qqq, m60, perp


def test_backtest_by_hand_and_repeatable():
    sess, qqq, m60, perp = _fake()
    a = gap.backtest(qqq, m60, perp, sess)
    b = gap.backtest(qqq, m60, perp, sess)
    pd.testing.assert_frame_equal(a, b)                               # 같은 데이터 → 같은 값
    assert gap.accuracy(a, "perp") == gap.accuracy(b, "perp")
    row = a[a["anchor"] == pd.Timestamp("2026-01-09")].iloc[0]       # 금 → 월(1/12)
    assert math.isclose(row["actual"], qqq.loc["2026-01-12", "open"] / qqq.loc["2026-01-09", "close"] - 1)
    t_close = mt.session_close_utc(date(2026, 1, 9))
    t_pre = datetime(2026, 1, 11, 18, 0, tzinfo=mt.ET)                 # 일요일 18:00 ET = 월 08:00 KST
    assert math.isclose(row["perp"], gap.price_at(perp, t_pre) / gap.price_at(perp, t_close) - 1)
    # 1/19 마틴 루터 킹 데이: 금(1/16) → 화(1/20). 무기한 선물은 그래도 일요일 18:00 ET 에서 고정
    row2 = a[a["anchor"] == pd.Timestamp("2026-01-16")].iloc[0]
    assert math.isclose(row2["actual"], qqq.loc["2026-01-20", "open"] / qqq.loc["2026-01-16", "close"] - 1)
    t_pre2 = datetime(2026, 1, 18, 18, 0, tzinfo=mt.ET)
    assert math.isclose(row2["perp"], gap.price_at(perp, t_pre2) / gap.price_at(perp, mt.session_close_utc(date(2026, 1, 16))) - 1)


def test_accuracy_numbers():
    bt = pd.DataFrame({"actual": [0.01, -0.012, 0.005, -0.004], "ah": [0.008, 0.002, 0.004, -0.006],
                       "flat": 0.0})
    a = gap.accuracy(bt, "ah")
    assert a["n"] == 4 and math.isclose(a["mae"], (0.002 + 0.014 + 0.001 + 0.002) / 4) and a["hit"] == 0.75
    assert a["ci"] == gap.wilson(3, 4)
    assert a["big"]["n"] == 1 and a["big"]["hit"] == 0.0           # 갭 1% 넘은 주(−1.2%)는 방향 틀림
    assert a["hit3"] == 0.75                                       # 상승·하락·상승·하락 구간: 2번째만 틀림
    f = gap.accuracy(bt, "flat")
    assert f["hit"] is None and f["corr"] is None and f["hit3"] == 0.0     # 보합 예측: 방향 없음, ±0.3% 안 실제 갭 없음
    assert math.isclose(f["mae"], (0.01 + 0.012 + 0.005 + 0.004) / 4)


def test_wilson_interval():
    lo, hi = gap.wilson(14, 29)
    assert 0.30 < lo < 0.33 and 0.64 < hi < 0.67                    # 48%, N=29 → 대략 31%~66%
    assert gap.wilson(0, 0) is None


def test_perp_cutoff_is_monday_0800_kst():
    assert hm(gap.perp_cutoff(date(2026, 11, 13))) == (11, 16, 8, 0)     # 겨울
    assert hm(gap.perp_cutoff(date(2026, 7, 10))) == (7, 13, 7, 0)       # 여름
    assert hm(gap.perp_cutoff(date(2026, 1, 16))) == (1, 19, 8, 0)      # 월요일 휴장이어도 일요일 18:00 ET


def test_prices_after_cutoff_are_never_used():
    sess, qqq, m60, perp = _fake()
    base = gap.backtest(qqq, m60, perp, sess)
    wild = perp.copy()
    for a, _ in gap.weekend_anchors(sess):                         # 월요일 08:00 KST 이후 가격을 엉망으로
        cut = pd.Timestamp(gap.perp_cutoff(a.date()))
        m = (wild.index > cut) & (wild.index <= cut + pd.Timedelta(hours=40))
        wild[m] = wild[m] * 1.5
    pd.testing.assert_frame_equal(base, gap.backtest(qqq, m60, wild, sess))
    # 직전 값이 2시간보다 오래됐으면(자료 빠짐) 그 주는 계산하지 않는다
    cut = pd.Timestamp(gap.perp_cutoff(date(2026, 1, 9)))
    holey = perp[(perp.index <= cut - pd.Timedelta(hours=3)) | (perp.index > cut)]
    row = gap.backtest(qqq, m60, holey, sess).set_index("anchor").loc[pd.Timestamp("2026-01-09")]
    assert pd.isna(row["perp"]) and pd.isna(row["ah_perp"])


def test_compare_uses_same_weekends():
    sess, qqq, m60, perp = _fake()
    bt = gap.backtest(qqq, m60, perp, sess)
    res, common = gap.compare(bt)
    assert set(res) == {"ah", "ah_perp", "flat"}
    assert res["ah"]["n"] == res["ah_perp"]["n"] == res["flat"]["n"] == len(common)


# ── 장부 ─────────────────────────────────────────
def test_ledger_save_lock_and_settle(tmp_path):
    db = tmp_path / "g.db"
    t = gap.times(datetime(2026, 11, 14, 10, 0, tzinfo=KST))
    assert gap.save_estimate(t, gap.estimate_gap(ah=-0.01), 680.0, 57.68, {}, datetime(2026, 11, 14, 10, 0, tzinfo=KST), db)
    # 일요일 저녁 다시 열면 최신 예상으로 덮어씀
    assert gap.save_estimate(t, gap.estimate_gap(ah=-0.01, perp_after_ah=0.005), 680.0, 57.68, {},
                             datetime(2026, 11, 15, 20, 0, tzinfo=KST), db)
    # 미국 장이 열린 뒤에는 고정
    assert not gap.save_estimate(t, gap.estimate_gap(nq=0.05), 680.0, 57.68, {},
                                 datetime(2026, 11, 17, 0, 0, tzinfo=KST), db)
    L = gap.ledger(db)
    assert len(L) == 1 and L.iloc[0]["method"] == "ah_perp"
    g = (1 - 0.01) * 1.005 - 1
    assert math.isclose(L.iloc[0]["qqq_est"], 680 * (1 + g)) and math.isclose(L.iloc[0]["tqqq_est"], 57.68 * (1 + 3 * g))
    idx = pd.to_datetime(["2026-11-13", "2026-11-16"])
    qqq = pd.DataFrame({"open": [681.0, 676.0], "close": [680.0, 677.0]}, index=idx)
    tq = pd.DataFrame({"open": [57.0, 56.8], "close": [57.68, 56.9]}, index=idx)
    assert gap.settle(qqq, tq, db) == 2
    L = gap.ledger(db)
    assert L.iloc[0]["qqq_open"] == 676.0 and math.isclose(L.iloc[0]["qqq_err"], 680 * (1 + g) / 676 - 1)
    assert bool(L.iloc[0]["dir_hit"]) is True                        # 예상 하락, 실제 676 < 680
    s = gap.ledger_stats(L)
    assert s["n"] == 1 and s["hit"] == 1.0


# ── 화면: 재료가 다 빠져도 깨지지 않는다 ─────────
def test_page_with_no_data(monkeypatch, tmp_path):
    from t6 import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "p.db")
    store.init_db()

    def empty(now=None):
        now = datetime(2026, 11, 14, 10, 0, tzinfo=KST)
        sn = gap_data.Snapshot(gap.times(now), now)
        sn.qqq = {"close": None, "ah": None, "ah_chg": None}
        sn.tqqq = dict(sn.qqq)
        sn.perps = {"Hyperliquid XYZ100": {"at_close": None, "at_ah": None, "now": None, "chg_close": None,
                                           "chg_ah": None, "note": "x"}}
        sn.nq = {"opened": False, "at_close": None, "now": None, "chg": None}
        sn.est = gap.estimate_gap()
        return sn

    monkeypatch.setattr(gap_data, "snapshot", empty)
    monkeypatch.setattr(gap_data, "history",
                        lambda q: pd.DataFrame(columns=["anchor", "actual", "ah", "ah_perp", "flat", "perp"]))
    st.cache_data.clear()
    at = AppTest.from_file(str(ROOT / "views" / "gap.py"), default_timeout=120)
    at.run()
    assert not at.exception, at.exception
    texts = " ".join(m.value for m in at.markdown)
    assert "재미용입니다" in texts and "출발 예상" in texts
    st.cache_data.clear()
