"""FRED (미국 연준 경제 데이터) — 키 없이 CSV 로 받는다. 2003년 이전 원/달러 환율용."""
from __future__ import annotations

import io

import pandas as pd

from .base import COLUMNS

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}&coed={end}"
# Yahoo 환율이 2003-12 부터 있으므로 그 직후까지만 받는다 (전체를 받으면 느림)
FRED_END = "2004-12-31"


class FredSource:
    name = "fred"

    def fetch_daily(self, series_id: str, start: str) -> pd.DataFrame:
        import requests

        r = requests.get(URL.format(sid=series_id, start=start, end=FRED_END), timeout=60)  # 사용자 지정 User-Agent 를 넣으면 FRED 가 응답하지 않음
        r.raise_for_status()
        raw = pd.read_csv(io.StringIO(r.text))
        raw.columns = ["date", "value"]
        raw["value"] = pd.to_numeric(raw["value"], errors="coerce")   # 휴일은 '.' → NaN
        raw = raw.dropna()
        raw["date"] = pd.to_datetime(raw["date"])
        raw = raw[raw["date"] >= pd.Timestamp(start)].set_index("date")
        if raw.empty:
            raise RuntimeError(f"{series_id}: 받은 데이터가 없습니다")
        v = raw["value"].astype(float)
        df = pd.DataFrame({c: v for c in ["open", "high", "low", "close", "adj_close"]})
        df["volume"] = 0.0
        df.index.name = "date"
        return df[COLUMNS]
