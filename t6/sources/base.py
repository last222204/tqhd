"""시세 출처의 공통 규격.

새 출처(예: Polygon/Massive)를 붙이려면 이 규격대로 클래스를 하나 만들고
t6/sources/__init__.py 의 get_source() 에서 고르게 하면 된다.
API 키는 반드시 .env 에서 os.environ 으로 읽는다. 코드에 적지 않는다.
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

# 모든 출처가 돌려줘야 하는 열
#   open, high, low, close : 배당 미조정 가격 (분할은 반영)
#   adj_close              : 배당까지 조정한 종가 (yfinance auto_adjust=True 의 Close 와 같다)
#   volume
COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]


class PriceSource(Protocol):
    name: str

    def fetch_daily(self, symbol: str, start: str) -> pd.DataFrame:
        """일봉. 인덱스는 거래일(시간대 없는 날짜, 오름차순), 열은 COLUMNS."""
        ...

    # 선택 기능: 일봉 종가가 늦게 올라올 때 '잠정 종가'를 만들기 위한 1분봉.
    # 없는 출처는 이 메서드를 만들지 않으면 된다 (그러면 잠정 종가 없이 기다린다).
    # def fetch_minute_bars(self, symbol: str, day: date) -> pd.DataFrame:
    #     """그날 정규장 1분봉. 인덱스=시각(시간대 있음), 열=open/high/low/close/volume."""
