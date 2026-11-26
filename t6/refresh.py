"""하루 한 번 시세 받기.

- 사이트를 열 때 저장된 마지막 날짜가 '마지막으로 마감한 미국 거래일'보다 오래됐으면 받는다.
- 미국 종목은 아직 장 마감 전인 날(장중 막대)을 잘라내서, 신호는 항상 확정 종가로만 낸다.
- 실패하면 저장된 값을 그대로 쓰고, 화면이 '마지막으로 받은 날짜 기준'이라고 크게 알린다.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import market_time as mt
from . import store
from .config import (FRED_FX, FX_SYMBOL, HISTORY_START, MANUAL_COOLDOWN_SEC, PROVISIONAL_SYMBOLS, RETRY_MINUTES,
                     SIGNAL_SYMBOL, SYMBOLS)
from .sources import get_fred_source, get_source


@dataclass
class FetchResult:
    symbol: str
    ok: bool
    last_date: str | None
    rows: int
    error: str | None = None


def drop_unfinished(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """장 마감이 지나지 않은 날의 막대를 버린다 (미국 종목 전용)."""
    last_done = pd.Timestamp(mt.last_completed_session(now))
    return df[df.index <= last_done]


def provisional_bar(src, symbol: str, day: date) -> pd.DataFrame | None:
    """일봉 종가가 아직 없을 때, 그날 정규장 1분봉으로 '잠정' 일봉 한 줄을 만든다.

    마지막 1분봉이 장 마감 직전(보통 15:59 ET) 것이어야만 쓴다. 장 전체가 있어야 종가라고 할 수 있으므로.
    배당조정 종가 = 종가 로 둔다 (가장 최근 날은 조정 계수가 1). 공식 일봉이 들어오면 통째로 바뀐다.
    """
    if not hasattr(src, "fetch_minute_bars"):
        return None
    bars = src.fetch_minute_bars(symbol, day)
    if bars is None or bars.empty:
        return None
    close_utc = pd.Timestamp(mt.session_close_utc(day))
    last_ts = pd.Timestamp(bars.index[-1])
    last_ts = last_ts.tz_convert("UTC") if last_ts.tzinfo else last_ts.tz_localize(mt.ET).tz_convert("UTC")
    if last_ts < close_utc - pd.Timedelta(minutes=1):
        return None  # 장 끝까지 1분봉이 없으면 종가로 쓰지 않는다
    c = float(bars["close"].iloc[-1])
    row = pd.DataFrame(
        {"open": float(bars["open"].iloc[0]), "high": float(bars["high"].max()),
         "low": float(bars["low"].min()), "close": c, "adj_close": c,
         "volume": float(bars["volume"].sum()), "provisional": True},
        index=pd.DatetimeIndex([pd.Timestamp(day)], name="date"),
    )
    return row


def refresh_all(now: datetime | None = None, path=None) -> list[FetchResult]:
    now = now or datetime.now(timezone.utc)
    src = get_source()
    expected = mt.last_completed_session(now)
    # 9종목을 동시에 받아서 시간을 줄인다 (저장은 아래에서 하나씩)
    def _get(sym):
        try:
            return src.fetch_daily(sym, HISTORY_START)
        except Exception as e:
            return e

    with ThreadPoolExecutor(max_workers=5) as ex:
        fetched = dict(zip(SYMBOLS, ex.map(_get, SYMBOLS)))

    results = []
    for sym in SYMBOLS:
        try:
            df = fetched[sym]
            if isinstance(df, Exception):
                raise df
            prov = False
            if sym != FX_SYMBOL:
                df = drop_unfinished(df, now)
                # 일봉에 마지막 거래일 종가가 아직 없고, 바로 전 거래일까지는 있으면 → 1분봉으로 잠정 종가
                if (sym in PROVISIONAL_SYMBOLS and not df.empty and df.index[-1].date() < expected
                        and df.index[-1].date() == mt.previous_session(expected)):
                    try:
                        row = provisional_bar(src, sym, expected)
                    except Exception:
                        row = None
                    if row is not None:
                        df = pd.concat([df.assign(provisional=False), row])
                        prov = True
            if df.empty:
                raise RuntimeError("마감된 데이터가 없습니다")
            store.save_prices(sym, df, path)
            last = df.index[-1].strftime("%Y-%m-%d")
            store.log_fetch(sym, src.name, True, last, len(df),
                            "잠정 종가(1분봉)" if prov else None, path=path, at=now)
            results.append(FetchResult(sym, True, last, len(df)))
        except Exception as e:  # 네트워크·출처 오류는 기록하고 다음 종목으로
            msg = f"{type(e).__name__}: {e}"[:500]
            store.log_fetch(sym, src.name, False, store.last_price_date(sym, path), None, msg, path=path, at=now)
            results.append(FetchResult(sym, False, store.last_price_date(sym, path), 0, msg))
    results.append(_refresh_fred(now, path))
    return results


def _refresh_fred(now: datetime, path=None) -> FetchResult:
    """FRED 환율 (2003년 이전 원/달러). 과거 값이라 한 번 받으면 다시 받지 않는다."""
    have = store.last_price_date(FRED_FX, path)
    if have is not None:
        return FetchResult(FRED_FX, True, have, 0)
    src = get_fred_source()
    try:
        df = src.fetch_daily(FRED_FX, HISTORY_START)
        store.save_prices(FRED_FX, df, path)
        last = df.index[-1].strftime("%Y-%m-%d")
        store.log_fetch(FRED_FX, src.name, True, last, len(df), path=path, at=now)
        return FetchResult(FRED_FX, True, last, len(df))
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"[:500]
        store.log_fetch(FRED_FX, src.name, False, store.last_price_date(FRED_FX, path), None, msg, path=path, at=now)
        return FetchResult(FRED_FX, False, store.last_price_date(FRED_FX, path), 0, msg)


# 사이트가 외부에 열려 있으므로, 여러 사람이 동시에/연달아 눌러도 Yahoo 에 한 번만 요청한다.
_lock = threading.Lock()


def cooldown_left(now: datetime | None = None, path=None) -> int:
    """수동 새로고침을 다시 누를 수 있을 때까지 남은 초 (0이면 가능)."""
    now = now or datetime.now(timezone.utc)
    last = store.last_fetch(path=path)
    if not last:
        return 0
    left = MANUAL_COOLDOWN_SEC - (now - last["fetched_at"]).total_seconds()
    return max(0, int(left) + (1 if left % 1 else 0))


def try_refresh(now: datetime | None = None, path=None) -> list[FetchResult] | None:
    """받는 중이 아니고 대기 시간이 지났을 때만 받는다. 아니면 None."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        if cooldown_left(now, path) > 0:
            return None
        return refresh_all(now, path)
    finally:
        _lock.release()


def expected_last_date(now: datetime | None = None) -> date:
    return mt.last_completed_session(now or datetime.now(timezone.utc))


def needs_refresh(now: datetime | None = None, path=None) -> bool:
    """저장된 QQQ 가 오래됐거나 잠정 종가뿐이고, 최근에 시도한 적이 없으면 True."""
    now = now or datetime.now(timezone.utc)
    have = store.last_price_date(SIGNAL_SYMBOL, path)
    if (have is not None and date.fromisoformat(have) >= expected_last_date(now)
            and not any(store.last_is_provisional(s, path) for s in PROVISIONAL_SYMBOLS)):
        return False
    last_try = store.last_fetch(SIGNAL_SYMBOL, path=path)
    if last_try and now - last_try["fetched_at"] < timedelta(minutes=RETRY_MINUTES):
        return False
    return True


def freshness(now: datetime | None = None, path=None) -> dict:
    """화면에 보여줄 데이터 상태."""
    now = now or datetime.now(timezone.utc)
    have = store.last_price_date(SIGNAL_SYMBOL, path)
    expected = expected_last_date(now)
    last_try = store.last_fetch(SIGNAL_SYMBOL, path=path)
    last_ok = store.last_fetch(SIGNAL_SYMBOL, ok=True, path=path)
    return {
        "have": date.fromisoformat(have) if have else None,
        "expected": expected,
        "stale": have is None or date.fromisoformat(have) < expected,
        "provisional": have is not None and store.last_is_provisional(SIGNAL_SYMBOL, path),
        "last_try": last_try,
        "last_ok": last_ok,
    }
