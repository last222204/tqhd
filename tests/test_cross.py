"""검증 2 (파이썬 ↔ JS 60일 대조, 1e-9) · 검증 4 (JS 임계 왕복) · 검증 5 (실시간 끊김·멈춤·휴장 처리)."""
import copy
from datetime import date, datetime, timezone

import pytest

import tqhd as T
import update_state as U

TOL = 1e-9


def ms(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


# ── 검증 2: 과거 60일 전부 대조 ────────────────
def test_python_js_same_on_last_60_days(prices, js):
    q = prices["qqq"]
    frame = U.compute(q)
    n = len(q)
    checked = 0
    for t in range(n - 60, n):
        base = U.base_at(q, frame, t - 1)
        price = float(q.iloc[t])
        want = frame.iloc[t]
        py = T.evaluate(base, price)
        jv = js("evaluate", base, price)
        for k in ("sma50", "sma200", "rsi2"):
            assert abs(py[k] - want[k]) <= TOL, (q.index[t], k, py[k], want[k])
            assert abs(jv[k] - py[k]) <= TOL, (q.index[t], k, jv[k], py[k])
        assert py["state"] == jv["state"] == want["state"], q.index[t]
        assert py["weight"] == jv["weight"] == want["weight"], q.index[t]
        jl = js("levels", base)                                   # 임계 가격도 같은지
        assert abs(jl["sma50"] - T.cross_price(base["sum_prev_49"], 50)) <= TOL
        assert abs(jl["sma200"] - T.cross_price(base["sum_prev_199"], 200)) <= TOL
        for key, tg in (("hunt_half", 15.0), ("hunt_full", 5.0), ("hunt_exit", 50.0)):
            pyp = T.rsi_price(base["qqq_prev_close"], base["wilder_avg_gain"], base["wilder_avg_loss"], tg)
            assert abs(jl[key] - pyp) <= TOL
        checked += 1
    assert checked == 60


def test_js_wilder_step_matches_python_known_values(js):
    c = [10, 11, 10.5, 12, 11]
    rsi, ag, al = T.wilder_rsi2(c)
    for i in range(3, 5):
        r = js("rsiStep", c[i - 1], ag[i - 1], al[i - 1], c[i])
        assert abs(r["rsi"] - rsi[i]) <= TOL and r["g"] == ag[i] and r["l"] == al[i]
    assert js("rsiFrom", 1, 0) == 100


@pytest.mark.parametrize("prev, w, night, rsi", [
    ("day", 100, True, 14.99), ("night", 0, True, 15), ("night", 0, True, 5), ("hunt", 50, True, 4.9),
    ("hunt", 50, True, 50), ("hunt", 50, True, 50.01), ("hunt", 50, False, 80), ("day", 100, True, 4.99)])
def test_js_next_state_same_as_python(js, prev, w, night, rsi):
    s, wt = T.next_state(prev, w, night, rsi)
    assert js("nextState", prev, w, night, rsi) == {"state": s, "weight": wt}


# ── 검증 4: JS 임계 가격을 넣으면 정말 바뀌는지 ──
def test_js_changes_round_trip(prices, js):
    q = prices["qqq"]
    frame = U.compute(q)
    found = 0
    for t in range(len(q) - 60, len(q)):
        base = U.base_at(q, frame, t - 1)
        for price in (float(q.iloc[t]), base["qqq_prev_close"]):
            cur = js("evaluate", base, price)
            ch = js("changes", base, price)
            for side, f in (("down", 1 - 1e-7), ("up", 1 + 1e-7)):
                c = ch[side]
                if c is None:
                    continue
                found += 1
                e = js("evaluate", base, c["price"] * f)
                assert (e["state"], e["weight"]) == (c["state"], c["weight"])
                assert (e["state"], e["weight"]) != (cur["state"], cur["weight"])
                pe = T.evaluate(base, c["price"] * f)
                assert (pe["state"], pe["weight"]) == (c["state"], c["weight"])
                # 지금 가격과 그 가격 사이에서는 상태가 안 바뀐다
                mid = js("evaluate", base, (price + c["price"]) / 2)
                assert (mid["state"], mid["weight"]) == (cur["state"], cur["weight"])
    assert found > 100


# ── 검증 5: 실시간 끊김 · 멈춤 · 휴장 ───────────
def quotes(t_qqq, qqq=640.0, tqqq=46.5, nq=(26200.0, None), fx=1345.0):
    nq_p, nq_t = nq
    return {"fetched_at": t_qqq / 1000, "quotes": {
        "QQQ": {"price": qqq, "time": t_qqq / 1000},
        "TQQQ": {"price": tqqq, "time": t_qqq / 1000},
        "NQ": {"price": nq_p, "time": (nq_t or t_qqq) / 1000},
        "USDKRW": {"price": fx, "time": t_qqq / 1000}}}


LIVE_NOW = ms(2026, 11, 27, 16, 0)            # 11/27(금) 11:00 ET 장중 (13:00 조기 폐장)


def test_live_ok(state, js):
    v = js("buildView", state, quotes(LIVE_NOW - 20_000), LIVE_NOW)
    assert v["mode"] == "live" and v["live"]["ok"] and v["ref"]["kind"] == "now"
    assert v["qqq"]["price"] == 640.0 and v["card"]["rsi2"] is not None
    py = T.evaluate(state, 640.0)
    assert v["live"]["eval"]["state"] == py["state"] and abs(v["live"]["eval"]["rsi2"] - py["rsi2"]) <= TOL


def test_proxy_failure_never_shows_old_price(state, js):
    v = js("buildView", state, None, LIVE_NOW)
    assert v["mode"] == "live" and not v["proxyOk"]
    assert v["live"] == {"ok": False, "why": "disconnected", "text": "실시간 연결 끊김, 전일 종가 기준만 유효"}
    assert v["qqq"] is None and v["tqqq"] is None and v["ref"] is None
    assert v["card"]["basisIsPrev"] and v["card"]["rsi2"] is None


@pytest.mark.parametrize("t_qqq, last", [
    (ms(2026, 11, 25, 21, 0), "11/26 06:00"),        # 어제 종가 시각 그대로 → 지금 값이 아님
    (LIVE_NOW - 10 * 60_000, "11/28 00:50"),          # 10분째 그대로
])
def test_frozen_quote_shows_stop_and_time(state, js, t_qqq, last):
    v = js("buildView", state, quotes(t_qqq), LIVE_NOW)
    assert not v["live"]["ok"] and v["live"]["why"] == "frozen"
    assert v["live"]["text"].startswith("데이터 멈춤 · 마지막 갱신 " + last)
    assert v["qqq"] is None and v["ref"] is None and v["card"]["basisIsPrev"]


def test_after_close_uses_closing_print(state, js):
    now = ms(2026, 11, 27, 18, 30)
    v = js("buildView", state, quotes(ms(2026, 11, 27, 18, 0)), now)
    assert v["mode"] == "closed" and v["live"]["ok"] and v["live"]["closing"]


def test_thanksgiving_gap_estimate(state, js):
    now = ms(2026, 11, 26, 15, 0)
    nq_t = now - 11 * 60_000
    v = js("buildView", state, quotes(now, nq=(state["nq_prev_settle"] * 1.01, nq_t)), now)
    assert v["mode"] == "gap" and v["reason"] == {"kind": "holiday", "name": "추수감사절"}
    g = v["gap"]
    assert g["ok"] and not g["frozen"]
    assert g["qqqOpen"] == pytest.approx(state["qqq_prev_close"] * 1.01, abs=1e-9)
    assert g["eval"]["state"] == T.evaluate(state, g["qqqOpen"])["state"]
    assert v["ref"]["kind"] == "open" and v["live"] is None


def test_futures_closed_too(state, js):
    now = ms(2026, 11, 26, 20, 0)
    v = js("buildView", state, quotes(now, nq=(26100.0, ms(2026, 11, 25, 20, 55))), now)
    assert not v["gap"]["ok"] and v["gap"]["frozen"]
    assert v["gap"]["text"].startswith("선물도 휴장 · 마지막 값 11/26 05:55")
    v = js("buildView", state, quotes(now, nq=(26300.0, ms(2026, 11, 26, 18, 0))), now)    # 2시간째 그대로
    assert v["gap"]["ok"] and v["gap"]["frozen"]
    assert "선물도 휴장" in v["gap"]["frozenText"] and "11/27 03:00" in v["gap"]["frozenText"]


def test_gap_proxy_failure(state, js):
    now = ms(2026, 11, 26, 15, 0)
    v = js("buildView", state, None, now)
    assert v["mode"] == "gap" and not v["gap"]["ok"] and "연결 끊김" in v["gap"]["text"] and v["ref"] is None


def test_stale_state_is_flagged(state, js):
    now = ms(2026, 12, 1, 15, 0)                     # 11/27·11/30 이 지났는데 as_of 는 11/25
    v = js("buildView", state, quotes(now), now)
    assert v["mode"] == "stale" and v["live"] is None and "card" not in v
    assert "기준 데이터가 멈췄습니다" in v["warnings"][0] and "2026-11-25" in v["warnings"][0]


def _as_of(state, d):
    s = copy.deepcopy(state)
    s["as_of"] = str(d)
    s["calendar"] = U.calendar_block(d)
    return s


def test_weekend_and_premarket(state, js):
    s = _as_of(state, date(2026, 11, 27))
    v = js("buildView", s, quotes(ms(2026, 11, 28, 15, 0)), ms(2026, 11, 28, 15, 0))
    assert v["mode"] == "gap" and v["reason"]["kind"] == "weekend"
    v = js("buildView", s, quotes(ms(2026, 11, 30, 13, 0)), ms(2026, 11, 30, 13, 0))
    assert v["mode"] == "gap" and v["reason"]["kind"] == "premarket"
    v = js("buildView", s, quotes(ms(2026, 11, 30, 15, 0)), ms(2026, 11, 30, 15, 0))
    assert v["mode"] == "live"


def test_dst_aware_et_date(js):
    assert js("etDate", ms(2026, 3, 9, 3, 30)) == "2026-03-08"      # 서머타임 시작 일요일 밤
    assert js("etDate", ms(2026, 11, 27, 4, 30)) == "2026-11-26"
    assert js("fmtKst", ms(2026, 11, 26, 15, 0)) == "11/27 00:00"
