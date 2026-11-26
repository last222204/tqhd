"""QQQ 1년 변동성 — 나스닥의 성격이 바뀌는지 감시.

1년 변동성 = 최근 252거래일 일간 수익률의 표준편차 × √252
기준값은 하드코딩하지 않고 데이터에서 계산한다:
  - QQQ 1년 변동성의 1999년 이후 중간값
  - 반도체 지수(^SOX) 1년 변동성의 1999년 이후 중간값  ← 경고 기준선
경고: 연말 기준 QQQ 1년 변동성 ≥ ^SOX 중간값 인 해가 2년 연속이면 빨간 경고.
경고는 정보일 뿐 신호를 바꾸지 않는다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from .config import VOL_BASE_FROM, VOL_LONG

REGIME_MSG = "나스닥이 반도체 지수만큼 거칠어짐. 헛걸음 증가 가능성. 변동성 브레이크를 새 데이터로 재검토할 시점"


def vol_1y(close: pd.Series, window: int = VOL_LONG) -> pd.Series:
    return (close.pct_change().rolling(window).std() * math.sqrt(252)).dropna()


@dataclass
class LongVol:
    qqq: pd.Series            # QQQ 1년 변동성 (날짜별)
    sox: pd.Series            # ^SOX 1년 변동성
    qqq_median: float
    sox_median: float         # 경고 기준선
    current: float
    current_date: pd.Timestamp
    percentile: float         # 1999년 이후 기록 중 current 이하인 비율 (0~1)
    years: pd.DataFrame       # 연도별 연말 값
    warning: bool             # 연말 기준 2년 연속 기준 이상
    warning_years: list[int]


def compute(qqq_close: pd.Series, sox_close: pd.Series, today_year: int | None = None) -> LongVol:
    q = vol_1y(qqq_close)
    s = vol_1y(sox_close)
    base = pd.Timestamp(VOL_BASE_FROM)
    qb, sb = q[q.index >= base], s[s.index >= base]
    qm, sm = float(qb.median()), float(sb.median())
    cur = float(q.iloc[-1])
    pct = float((qb <= cur).mean())

    last_year = today_year or q.index[-1].year
    rows = []
    for y, g in q.groupby(q.index.year):
        if y < base.year:
            continue
        d = g.index[-1]
        sv = s.loc[:d]
        rows.append({
            "year": int(y),
            "date": d,
            "qqq": float(g.iloc[-1]),
            "sox": float(sv.iloc[-1]) if len(sv) else float("nan"),
            "over": bool(g.iloc[-1] >= sm),
            # 지난 해이거나, 올해라도 마지막 거래일까지 마감했으면 '연말 확정'
            "complete": y < last_year or _is_year_end(d),
        })
    years = pd.DataFrame(rows).set_index("year")
    done = years[years["complete"]]
    warn_years = []
    flags = done["over"]
    for y in done.index:
        if flags.get(y, False) and flags.get(y - 1, False):
            warn_years.append(int(y))
    latest_done = int(done.index.max()) if len(done) else None
    warning = bool(latest_done is not None and latest_done in warn_years)
    return LongVol(q, s, qm, sm, cur, q.index[-1], pct, years, warning, warn_years)


def _is_year_end(d: pd.Timestamp) -> bool:
    """d 가 그해 마지막 거래일인가 (12/31 이 휴장이어도 맞게)."""
    from . import market_time as mt

    return mt.next_session_after(d.date()).year > d.year


def top_pct_text(percentile: float) -> str:
    """0.58 → '상위 42%' (높을수록 거친 것)."""
    top = max(1, round((1 - percentile) * 100))
    return f"상위 {top}%"
