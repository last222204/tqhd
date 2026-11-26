"""하루 한 번 받기: 장중 막대 버리기, 다시 받을지 판단, 실패 시 마지막 날짜 유지."""
from datetime import datetime

import pandas as pd

from t6 import market_time as mt
from t6 import refresh, store


def _px(dates):
    idx = pd.DatetimeIndex(pd.to_datetime(dates))
    p = pd.Series(range(len(idx)), index=idx, dtype=float) + 100
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "adj_close": p, "volume": p})


def test_drop_unfinished_bar():
    df = _px(["2026-11-12", "2026-11-13"])
    # 금요일 장중 (토 01:00 KST) → 13일 막대는 버림
    out = refresh.drop_unfinished(df, datetime(2026, 11, 14, 1, 0, tzinfo=mt.KST))
    assert list(out.index.strftime("%Y-%m-%d")) == ["2026-11-12"]
    out = refresh.drop_unfinished(df, datetime(2026, 11, 14, 6, 1, tzinfo=mt.KST))
    assert len(out) == 2


class _FakeSource:
    name = "fake"

    def __init__(self, fail=False):
        self.fail = fail

    def fetch_daily(self, symbol, start):
        if self.fail:
            raise ConnectionError("인터넷 끊김")
        return _px(["2026-11-12", "2026-11-13"])


def test_refresh_and_failure(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    store.init_db(db)
    now = datetime(2026, 11, 14, 7, 0, tzinfo=mt.KST)
    assert refresh.needs_refresh(now, db)

    monkeypatch.setattr(refresh, "get_source", lambda: _FakeSource())
    res = refresh.refresh_all(now, db)
    assert all(r.ok for r in res if r.symbol != "DEXKOUS")   # FRED 는 테스트에서 막아 둠
    assert store.last_price_date("QQQ", db) == "2026-11-13"
    assert not refresh.needs_refresh(now, db)
    assert not refresh.freshness(now, db)["stale"]

    # 다음 거래일 마감 뒤 받기 실패 → 저장된 13일 값 유지, 화면은 '오래됨'
    later = datetime(2026, 11, 17, 7, 0, tzinfo=mt.KST)
    assert refresh.needs_refresh(later, db)
    monkeypatch.setattr(refresh, "get_source", lambda: _FakeSource(fail=True))
    res = refresh.refresh_all(later, db)
    assert not any(r.ok for r in res)
    f = refresh.freshness(later, db)
    assert f["stale"] and str(f["have"]) == "2026-11-13" and str(f["expected"]) == "2026-11-16"
    assert "인터넷 끊김" in f["last_try"]["error"]


def test_manual_cooldown(tmp_path, monkeypatch):
    """외부 공개 상태라 연타해도 Yahoo 에는 1분에 한 번만 요청한다."""
    from datetime import timedelta

    db = tmp_path / "t.db"
    store.init_db(db)
    calls = []

    class _Counting(_FakeSource):
        def fetch_daily(self, symbol, start):
            calls.append(symbol)
            return super().fetch_daily(symbol, start)

    monkeypatch.setattr(refresh, "get_source", lambda: _Counting())
    assert refresh.cooldown_left(path=db) == 0
    assert refresh.try_refresh(path=db) is not None
    n = len(calls)
    assert refresh.try_refresh(path=db) is None          # 바로 또 누름 → 무시
    assert len(calls) == n
    assert 55 <= refresh.cooldown_left(path=db) <= 60
    later = datetime.now(mt.KST) + timedelta(seconds=61)
    assert refresh.cooldown_left(later, db) == 0
    assert refresh.try_refresh(later, db) is not None


# ── 잠정 종가 (일봉 종가가 늦게 올라올 때 1분봉으로) ─────────────────
class _LateSource:
    """일봉은 daily_until 까지만 있고, 1분봉은 minute_until(ET 시각)까지 있는 가짜 출처."""
    name = "fake"

    def __init__(self, daily_until="2026-11-12", minute_until="15:59", last_close=679.90):
        self.daily_until, self.minute_until, self.last_close = daily_until, minute_until, last_close

    def fetch_daily(self, symbol, start):
        days = [d for d in ["2026-11-11", "2026-11-12", "2026-11-13"] if d <= self.daily_until]
        return _px(days)

    def fetch_minute_bars(self, symbol, day):
        idx = pd.date_range(f"{day} 09:30", f"{day} {self.minute_until}", freq="1min", tz=mt.ET)
        c = pd.Series(670.0, index=idx)
        c.iloc[-1] = self.last_close
        return pd.DataFrame({"open": 670.0, "high": c + 1, "low": c - 1, "close": c, "volume": 100.0})


def test_provisional_close_from_minute_bars(tmp_path, monkeypatch):
    from datetime import timedelta

    db = tmp_path / "t.db"
    store.init_db(db)
    now = datetime(2026, 11, 14, 6, 30, tzinfo=mt.KST)       # 금요일 장 마감 30분 뒤
    monkeypatch.setattr(refresh, "get_source", lambda: _LateSource())
    refresh.refresh_all(now, db)

    q = store.load_prices("QQQ", db)
    assert q.index[-1] == pd.Timestamp("2026-11-13")
    assert bool(q["provisional"].iloc[-1]) and not q["provisional"].iloc[:-1].any()
    assert q["close"].iloc[-1] == 679.90 and q["adj_close"].iloc[-1] == 679.90
    assert q["high"].iloc[-1] == 680.90 and q["open"].iloc[-1] == 670.0
    f = refresh.freshness(now, db)
    assert not f["stale"] and f["provisional"]
    # 잠정이면 15분 뒤 다시 받으러 간다
    assert not refresh.needs_refresh(now + timedelta(minutes=5), db)
    assert refresh.needs_refresh(now + timedelta(minutes=16), db)

    # 공식 일봉이 올라오면 잠정 표시가 사라진다
    monkeypatch.setattr(refresh, "get_source", lambda: _LateSource(daily_until="2026-11-13"))
    refresh.refresh_all(now + timedelta(minutes=16), db)
    q = store.load_prices("QQQ", db)
    assert not q["provisional"].any() and q["close"].iloc[-1] == 102.0
    assert not refresh.freshness(now, db)["provisional"]
    assert not refresh.needs_refresh(now + timedelta(minutes=40), db)


def test_no_provisional_if_minute_bars_incomplete(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    store.init_db(db)
    now = datetime(2026, 11, 14, 6, 30, tzinfo=mt.KST)
    monkeypatch.setattr(refresh, "get_source", lambda: _LateSource(minute_until="15:30"))
    refresh.refresh_all(now, db)
    assert store.last_price_date("QQQ", db) == "2026-11-12"
    assert refresh.freshness(now, db)["stale"]


def test_no_provisional_if_more_than_one_day_missing(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    store.init_db(db)
    now = datetime(2026, 11, 14, 6, 30, tzinfo=mt.KST)
    monkeypatch.setattr(refresh, "get_source", lambda: _LateSource(daily_until="2026-11-11"))
    refresh.refresh_all(now, db)
    assert store.last_price_date("QQQ", db) == "2026-11-11"   # 중간이 비면 이동평균이 틀어지므로 채우지 않음


def test_fx_never_provisional(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    store.init_db(db)
    monkeypatch.setattr(refresh, "get_source", lambda: _LateSource())
    refresh.refresh_all(datetime(2026, 11, 14, 6, 30, tzinfo=mt.KST), db)
    assert not store.load_prices("KRW=X", db)["provisional"].any()


def test_old_db_gets_provisional_column(tmp_path):
    import sqlite3

    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE prices (symbol TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, "
                "adj_close REAL, volume REAL, PRIMARY KEY (symbol, date))")
    con.execute("INSERT INTO prices VALUES ('QQQ','2026-11-12',1,1,1,1,1,1)")
    con.commit()
    con.close()
    store.init_db(db)
    q = store.load_prices("QQQ", db)
    assert len(q) == 1 and not q["provisional"].iloc[0]


def test_provisional_sgov_also_triggers_recheck(tmp_path, monkeypatch):
    from datetime import timedelta

    class _SgovLate(_LateSource):
        def fetch_daily(self, symbol, start):
            return _px(["2026-11-12"] if symbol == "SGOV" else ["2026-11-12", "2026-11-13"])

    db = tmp_path / "t.db"
    store.init_db(db)
    now = datetime(2026, 11, 14, 6, 30, tzinfo=mt.KST)
    monkeypatch.setattr(refresh, "get_source", lambda: _SgovLate())
    refresh.refresh_all(now, db)
    assert store.last_is_provisional("SGOV", db) and not store.last_is_provisional("QQQ", db)
    assert refresh.needs_refresh(now + timedelta(minutes=16), db)
