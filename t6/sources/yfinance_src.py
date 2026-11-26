"""yfinance 출처 (API 키 필요 없음)."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .base import COLUMNS


class YFinanceSource:
    name = "yfinance"

    def fetch_daily(self, symbol: str, start: str) -> pd.DataFrame:
        import yfinance as yf

        # auto_adjust=False 로 받으면 Close(배당 미조정)와 Adj Close(배당 조정)를 한 번에 얻는다.
        # Adj Close 는 auto_adjust=True 로 받았을 때의 Close 와 같은 값이다.
        raw = yf.Ticker(symbol).history(
            start=start, interval="1d", auto_adjust=False, actions=False
        )
        if raw is None or raw.empty:
            raise RuntimeError(f"{symbol}: 받은 데이터가 없습니다")
        df = raw.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            }
        )
        if "adj_close" not in df:
            df["adj_close"] = df["close"]
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_localize(None)
        df.index = pd.DatetimeIndex(idx).normalize()
        df.index.name = "date"
        df = df[COLUMNS].astype(float)
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df.dropna(subset=["close", "adj_close"])

    def fetch_minute_bars(self, symbol: str, day: date) -> pd.DataFrame:
        """그날 정규장 1분봉 (시간대: 미국 동부). 열은 open/high/low/close/volume."""
        import yfinance as yf

        raw = yf.Ticker(symbol).history(
            start=day.isoformat(), end=(day + timedelta(days=1)).isoformat(),
            interval="1m", prepost=False, auto_adjust=False, actions=False,
        )
        if raw is None or raw.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                 "Close": "close", "Volume": "volume"})
        return df[["open", "high", "low", "close", "volume"]].astype(float).dropna(subset=["close"])
