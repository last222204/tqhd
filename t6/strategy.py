"""T6 신호 계산.

규칙: QQQ 종가가 50일선 그리고 200일선 둘 다 '아래'면 SGOV, 하나라도 위(같음 포함)면 TQQQ.
'아래'는 엄격하게 작다(<)는 뜻이다. 종가가 이동평균과 정확히 같으면 아래가 아니다.

손절·장중 판단·확인 일수 같은 필터는 규칙에 없으므로 여기에도 없다.
경고등(변동성)은 정보일 뿐 신호를 바꾸지 않는다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .config import BORDER_PCT, RISK_OFF, RISK_ON, SMA_FAST, SMA_SLOW, VOL_ALERT, VOL_WINDOW


def decide(close: float, sma_fast: float, sma_slow: float) -> str:
    """하루치 판정. 둘 다 아래면 SGOV, 아니면 TQQQ."""
    if close < sma_fast and close < sma_slow:
        return RISK_OFF
    return RISK_ON


def near_line(close: float, sma: float, pct: float = BORDER_PCT) -> bool:
    """종가가 선의 ±pct 이내인가 (경계선)."""
    return abs(close / sma - 1.0) <= pct + 1e-12


def realized_vol(close: pd.Series, window: int = VOL_WINDOW) -> pd.Series:
    """일간 수익률 표준편차(표본) × √252."""
    return close.pct_change().rolling(window).std() * math.sqrt(252)


def alert_level(above_slow: bool, vol: float, threshold: float = VOL_ALERT) -> str | None:
    """경고등. 'red' = 200일선 위 + 고변동성, 'yellow' = 200일선 아래 + 고변동성."""
    if vol is None or (isinstance(vol, float) and math.isnan(vol)) or vol < threshold:
        return None
    return "red" if above_slow else "yellow"


def signal_frame(px: pd.DataFrame, col: str = "adj_close") -> pd.DataFrame:
    """QQQ 일봉으로 날짜별 신호표를 만든다.

    px: open/high/low/close/adj_close 열을 가진 일봉 (오름차순)
    col: 'adj_close'(배당 조정, 공식 신호) 또는 'close'(배당 미조정, 참고용)
    """
    c = px[col].astype(float)
    out = pd.DataFrame(index=px.index)
    out["close"] = c
    out["sma_fast"] = c.rolling(SMA_FAST, min_periods=SMA_FAST).mean()
    out["sma_slow"] = c.rolling(SMA_SLOW, min_periods=SMA_SLOW).mean()
    out["dist_fast"] = c / out["sma_fast"] - 1.0
    out["dist_slow"] = c / out["sma_slow"] - 1.0
    ready = out["sma_slow"].notna()
    below = (c < out["sma_fast"]) & (c < out["sma_slow"])
    out["signal"] = np.where(below, RISK_OFF, RISK_ON)
    out.loc[~ready, "signal"] = None
    out["border"] = ready & (
        (out["dist_fast"].abs() <= BORDER_PCT + 1e-12) | (out["dist_slow"].abs() <= BORDER_PCT + 1e-12)
    )
    # 변동성은 항상 배당 조정 종가로 계산 (배당일 가격 하락이 변동성으로 잡히지 않게)
    out["vol"] = realized_vol(px["adj_close"].astype(float))
    prev = out["signal"].shift(1)
    out["switch"] = ready & prev.notna() & (out["signal"] != prev)
    return out


def switches(sf: pd.DataFrame) -> pd.DataFrame:
    """교체일 목록: 날짜, 새 신호, 종가."""
    return sf.loc[sf["switch"], ["signal", "close"]].rename(columns={"signal": "to"})


def refuge_periods(sf: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """SGOV 신호가 이어진 구간 [첫날, 마지막날] 목록 (차트 배경용)."""
    sig = sf["signal"]
    is_off = (sig == RISK_OFF).to_numpy()
    idx = sf.index
    periods, start = [], None
    for i, off in enumerate(is_off):
        if off and start is None:
            start = idx[i]
        elif not off and start is not None:
            periods.append((start, idx[i - 1]))
            start = None
    if start is not None:
        periods.append((start, idx[-1]))
    return periods
