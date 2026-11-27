"""update_state.py: 미완성 막대 버리기, 휴장일 이름, 달력, history 는 덧붙이기만."""
import csv
from datetime import date, datetime, timezone

import pandas as pd

import update_state as U

UTC = timezone.utc


def test_completed_sessions_drops_intraday_bar():
    idx = pd.DatetimeIndex(["2026-11-24", "2026-11-25", "2026-11-27"])
    # 11/27 은 13:00 ET 조기 폐장 (= 18:00 UTC)
    assert list(U.completed_sessions(idx, datetime(2026, 11, 27, 17, 0, tzinfo=UTC))) == list(idx[:2])
    assert list(U.completed_sessions(idx, datetime(2026, 11, 27, 18, 1, tzinfo=UTC))) == list(idx)


def test_calendar_block_thanksgiving():
    cal = U.calendar_block(date(2026, 11, 25), 10)
    s = {x["date"]: x for x in cal["sessions"]}
    assert s["2026-11-25"]["close_utc"] == "2026-11-25T21:00:00Z"
    assert s["2026-11-27"]["close_utc"] == "2026-11-27T18:00:00Z"        # 조기 폐장
    assert "2026-11-26" not in s
    assert {"date": "2026-11-26", "name": "추수감사절"} in cal["holidays"]


def test_holiday_names_cover_nyse_holidays():
    sch = U.schedule("2015-01-01", "2030-12-31")
    open_days = set(sch.index.date)
    special = {date(2018, 12, 5), date(2025, 1, 9)}                       # 전직 대통령 국장
    d, seen = date(2015, 1, 1), 0
    while d <= date(2030, 12, 31):
        if d.weekday() < 5 and d not in open_days:
            name = U.holiday_name(d)
            assert (name == "임시 휴장") == (d in special), (d, name)
            seen += 1
        d = date.fromordinal(d.toordinal() + 1)
    assert seen > 150


def _frame(prices, upto):
    return U.compute(prices["qqq"].loc[:upto])


def test_history_only_appends(prices, tmp_path):
    path = tmp_path / "history.csv"
    now = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)
    f1 = _frame(prices, "2026-11-24")
    assert U.append_history(path, f1, now) == 60                          # 처음: 최근 60일 역산
    first = path.read_text(encoding="utf-8")
    assert U.append_history(path, f1, now) == 0                           # 같은 날 다시 돌려도 안 늘어남
    f2 = _frame(prices, "2026-11-25")
    assert U.append_history(path, f2, now) == 1
    after = path.read_text(encoding="utf-8")
    assert after.startswith(first)                                        # 앞 줄은 그대로
    rows = list(csv.DictReader(after.splitlines()))
    assert rows[-1]["date"] == "2026-11-25" and rows[-1]["source"] == "자동"
    assert rows[0]["source"] == "역산"


def test_build_state_fields(prices):
    now = datetime(2026, 11, 26, 22, 0, tzinfo=UTC)
    prices = prices.loc[:"2026-11-25"]
    st, frame = U.build_state(prices["qqq"], prices["tqqq"], now, (26105.5, "2026-11-25T21:00:00Z", "5분봉"),
                              {"price": 1343.25, "date": "2026-11-26"})
    assert st["as_of"] == "2026-11-25" and st["qqq_prev_close"] == prices["qqq"].iloc[-1]
    c = prices["qqq"].to_numpy()
    assert st["sum_prev_49"] == sum(c[-49:]) and st["sum_prev_199"] == sum(c[-199:])
    assert st["confirmed"]["state"] == frame["state"].iloc[-1]
    assert len(st["recent"]) == 60 and st["recent"][-1]["date"] == "2026-11-25"
    assert set(st["night_ratio"]) == {"1m", "3m", "12m"}


def test_strip_reads_history_log(prices, tmp_path):
    path = tmp_path / "history.csv"
    U.append_history(path, _frame(prices, "2026-11-25"), datetime(2026, 11, 26, 22, 0, tzinfo=UTC))
    rec = U.recent_from_history(path)
    assert len(rec) == 60 and rec[-1]["date"] == "2026-11-25" and rec[-1]["source"] == "역산"
    assert set(rec[-1]) == {"date", "close", "rsi2", "state", "weight", "source"}


def test_chart_rows_shape(prices):
    p = prices.loc[:"2026-11-25"]
    rows = U.chart_rows(U.compute(p["qqq"]), p["tqqq"])
    assert len(rows) == 400 and rows[-1]["date"] == "2026-11-25"
    assert set(rows[-1]) == {"date", "qqq", "tqqq", "sma50", "sma200", "rsi2", "state", "weight"}
    assert all(r["date"] < s["date"] for r, s in zip(rows, rows[1:]))


def test_chart_json_matches_confirmed_state():
    """data/chart.json 마지막 줄 = data/state.json 의 confirmed (같은 데이터·같은 계산)."""
    import json
    from pathlib import Path
    data = Path(__file__).resolve().parent.parent / "data"
    st = json.loads((data / "state.json").read_text(encoding="utf-8"))
    ch = json.loads((data / "chart.json").read_text(encoding="utf-8"))
    last, c = ch["rows"][-1], st["confirmed"]
    assert ch["as_of"] == st["as_of"] == last["date"] == c["date"]
    for k_chart, k_conf in (("qqq", "close"), ("sma50", "sma50"), ("sma200", "sma200"), ("rsi2", "rsi2")):
        assert abs(last[k_chart] - c[k_conf]) <= 1e-3, k_chart
    assert last["state"] == c["state"] and last["weight"] == c["weight"]
    assert abs(last["tqqq"] - st["tqqq_prev_close"]) <= 1e-3
