"""시세 출처 고르기.

.env 의 PRICE_SOURCE 로 바꿀 수 있다 (지금은 yfinance 하나뿐).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

from ..config import ROOT
from .base import COLUMNS, PriceSource

load_dotenv(ROOT / ".env")


def get_source() -> PriceSource:
    name = os.environ.get("PRICE_SOURCE", "yfinance").strip().lower()
    if name == "yfinance":
        from .yfinance_src import YFinanceSource

        return YFinanceSource()
    # 나중에 예:  if name == "polygon": return PolygonSource(api_key=os.environ["POLYGON_API_KEY"])
    raise ValueError(f"모르는 시세 출처: {name}")


def get_fred_source():
    from .fred_src import FredSource

    return FredSource()


__all__ = ["COLUMNS", "PriceSource", "get_source", "get_fred_source"]
