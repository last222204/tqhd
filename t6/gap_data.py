"""월요일 출발가 점치기용 데이터 받기 — 나스닥 관련만 (yfinance · Hyperliquid · Kraken 공개 API, 키 필요 없음).

받기에 실패한 것은 None 으로 두고, 화면은 '데이터 없음'으로 표시하고 예상에서 뺀다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from . import gap
from . import market_time as mt

HL_URL = "https://api.hyperliquid.xyz/info"
KRAKEN_TICKERS = "https://futures.kraken.com/derivatives/api/v3/tickers"
KRAKEN_CHART = "https://futures.kraken.com/api/charts/v1/trade/{sym}/1h?from={a}&to={b}"
HL_NQ, KRAKEN_NQ = "xyz:XYZ100", "PF_US100USD"
TIMEOUT = 15


def _safe(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception:  # noqa: BLE001  — 네트워크·출처 오류는 '데이터 없음'
        return None


def yf_daily(sym: str, start: str | None = None, period: str = "1mo") -> pd.DataFrame | None:
    import yfinance as yf

    h = yf.Ticker(sym).history(start=start, period=None if start else period, interval="1d",
                               auto_adjust=False, actions=False)
    if h is None or h.empty:
        return None
    h = h.rename(columns={"Open": "open", "Close": "close"})[["open", "close"]].dropna()
    idx = h.index.tz_localize(None) if h.index.tz is not None else h.index
    h.index = pd.DatetimeIndex(idx).normalize()
    return h[~h.index.duplicated(keep="last")]


def yf_intraday(sym: str, interval: str = "5m", period: str = "5d", prepost: bool = True) -> pd.DataFrame | None:
    import yfinance as yf

    h = yf.Ticker(sym).history(period=period, interval=interval, prepost=prepost, auto_adjust=False, actions=False)
    if h is None or h.empty:
        return None
    return h.rename(columns={"Close": "close"})[["close"]].dropna()


def hl_mark(coin: str) -> float | None:
    meta, ctx = requests.post(HL_URL, json={"type": "metaAndAssetCtxs", "dex": "xyz"}, timeout=TIMEOUT).json()
    for a, c in zip(meta["universe"], ctx):
        if a["name"] == coin and c.get("markPx"):
            return float(c["markPx"])
    return None


def hl_candles(coin: str, start: datetime, end: datetime) -> pd.Series:
    """1시간봉 종가. 인덱스 = 봉이 끝난 시각 (UTC). 거래소가 최근 5,000개만 준다."""
    out = []
    a, b = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    step = 4000 * 3600 * 1000
    while a < b:
        out += requests.post(HL_URL, json={"type": "candleSnapshot", "req": {
            "coin": coin, "interval": "1h", "startTime": a, "endTime": min(b, a + step)}}, timeout=TIMEOUT).json()
        a += step
    if not out:
        return pd.Series(dtype=float)
    s = pd.Series({pd.Timestamp(c["T"] + 1, unit="ms", tz="UTC"): float(c["c"]) for c in out})
    return s[~s.index.duplicated(keep="last")].sort_index()


def kraken_last(sym: str) -> float | None:
    for t in requests.get(KRAKEN_TICKERS, timeout=TIMEOUT).json().get("tickers", []):
        if t.get("symbol") == sym and t.get("last"):
            return float(t["last"])
    return None


def kraken_candles(sym: str, start: datetime, end: datetime) -> pd.Series:
    c = requests.get(KRAKEN_CHART.format(sym=sym, a=int(start.timestamp()), b=int(end.timestamp())),
                     timeout=TIMEOUT).json().get("candles", [])
    return pd.Series({pd.Timestamp(x["time"] + 3600_000, unit="ms", tz="UTC"): float(x["close"]) for x in c}).sort_index()


# ── 지금 상황 ────────────────────────────────────
@dataclass
class Snapshot:
    t: gap.Times
    now: datetime
    qqq: dict = field(default_factory=dict)      # close, ah, ah_chg
    tqqq: dict = field(default_factory=dict)
    perps: dict = field(default_factory=dict)    # 이름 → {at_close, at_ah, now, chg_close, chg_ah, note}
    nq: dict = field(default_factory=dict)       # opened, at_close, now, chg
    perp_used: str | None = None                 # 예상에 쓴 무기한 선물
    est: gap.Estimate | None = None


def _close_on(df, d):
    try:
        return float(df.loc[pd.Timestamp(d), "close"]) if df is not None else None
    except KeyError:
        return None


def snapshot(now: datetime | None = None) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    t = gap.times(now)
    since = t.us_close - timedelta(days=2)
    jobs = {
        "QQQ": (yf_daily, "QQQ"), "TQQQ": (yf_daily, "TQQQ"),
        "QQQi": (yf_intraday, "QQQ"), "TQQQi": (yf_intraday, "TQQQ"), "NQi": (yf_intraday, "NQ=F"),
        "HLm": (hl_mark, HL_NQ), "HLc": (hl_candles, HL_NQ, since, now),
        "KRm": (kraken_last, KRAKEN_NQ), "KRc": (kraken_candles, KRAKEN_NQ, since, now),
    }
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {k: ex.submit(_safe, *v) for k, v in jobs.items()}
        D = {k: f.result() for k, f in futs.items()}
    sn = Snapshot(t, now)

    for key, out in (("QQQ", sn.qqq), ("TQQQ", sn.tqqq)):
        c = _close_on(D[key], t.us_anchor)
        ah = gap.ah_last(D[key + "i"], t.us_close) if D[key + "i"] is not None else None
        out.update(close=c, ah=ah, ah_chg=gap.change(ah, c))

    for name, m, c, note in (("Hyperliquid XYZ100", D["HLm"], D["HLc"], "주말 거래 가장 많음"),
                             ("Kraken US100", D["KRm"], D["KRc"], "거래량 매우 얇음")):
        at_close = gap.price_at(c, t.us_close) if c is not None else None
        at_ah = gap.price_at(c, t.ah_end) if c is not None else None
        sn.perps[name] = {"at_close": at_close, "at_ah": at_ah, "now": m, "chg_close": gap.change(m, at_close),
                          "chg_ah": gap.change(m, at_ah) if now >= t.ah_end else None, "note": note}

    opened = now >= t.fut_open
    nqi = D["NQi"]
    at_close = gap.price_at(nqi["close"], t.us_close) if nqi is not None else None
    cur = None
    if opened and nqi is not None:
        after = nqi[nqi.index.tz_convert("UTC") >= pd.Timestamp(t.fut_open)]
        cur = float(after["close"].iloc[-1]) if len(after) else None
    sn.nq = {"opened": opened, "at_close": at_close, "now": cur, "chg": gap.change(cur, at_close)}

    # 무기한 선물은 Hyperliquid 우선, 없으면 Kraken
    use = next((n for n in sn.perps if sn.perps[n]["chg_close"] is not None), None)
    sn.perp_used = use
    p = sn.perps.get(use, {}) if use else {}
    sn.est = gap.estimate_gap(ah=sn.qqq["ah_chg"], perp_close=p.get("chg_close"),
                              perp_after_ah=p.get("chg_ah"), nq=sn.nq["chg"])
    return sn


# ── 과거 데이터 (같은 방법이었다면 얼마나 맞았나) ──
def history(qqq_daily: pd.DataFrame) -> pd.DataFrame:
    jobs = {"qqq60": (yf_intraday, "QQQ", "60m", "730d", True),
            "perp": (hl_candles, HL_NQ, datetime(2025, 10, 1, tzinfo=timezone.utc), datetime.now(timezone.utc))}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {k: ex.submit(_safe, *v) for k, v in jobs.items()}
        D = {k: f.result() for k, f in futs.items()}
    return gap.backtest(qqq_daily[["open", "close"]], D["qqq60"], D["perp"], mt.sessions())
