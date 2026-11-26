"""미국 거래일(NYSE 달력)과 한국 시간표, 적립일 계산."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

import pandas as pd

from .config import CONTRIBUTION_DAY

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")
WEEKDAY_KO = "월화수목금토일"


@lru_cache(maxsize=4)
def _schedule(start_year: int, end_year: int) -> pd.DataFrame:
    import pandas_market_calendars as mcal

    cal = mcal.get_calendar("NYSE")
    sch = cal.schedule(start_date=f"{start_year}-01-01", end_date=f"{end_year}-12-31")
    sch.index = pd.DatetimeIndex(sch.index).normalize()
    return sch[["market_open", "market_close"]]


def schedule() -> pd.DataFrame:
    """1998년부터 내년 말까지의 NYSE 개장일. 인덱스=거래일, 열=market_open/market_close (UTC)."""
    return _schedule(1998, date.today().year + 2)


def sessions() -> pd.DatetimeIndex:
    return schedule().index


def is_session(d: date) -> bool:
    return pd.Timestamp(d) in sessions()


def next_session_on_or_after(d: date) -> date:
    s = sessions()
    i = s.searchsorted(pd.Timestamp(d), side="left")
    return s[i].date()


def next_session_after(d: date) -> date:
    s = sessions()
    i = s.searchsorted(pd.Timestamp(d), side="right")
    return s[i].date()


def previous_session(d: date) -> date:
    s = sessions()
    i = s.searchsorted(pd.Timestamp(d), side="left")
    return s[i - 1].date()


def last_completed_session(now: datetime | None = None) -> date:
    """장 마감이 이미 지난 가장 최근 거래일 (미국 날짜)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now 에는 시간대가 있어야 합니다")
    sch = schedule()
    closed = sch[sch["market_close"] <= pd.Timestamp(now).tz_convert("UTC")]
    return closed.index[-1].date()


def session_close_utc(d: date) -> datetime:
    return schedule().loc[pd.Timestamp(d), "market_close"].to_pydatetime()


# ── 적립일 ───────────────────────────────────────
def contribution_date(year: int, month: int) -> date:
    """그 달 17일. 미국 휴장일(주말 포함)이면 다음 거래일."""
    return next_session_on_or_after(date(year, month, CONTRIBUTION_DAY))


def next_contribution_date(after: date) -> date:
    """after(미국 날짜) 보다 뒤에 오는 첫 적립일. 보통 after=마지막으로 마감한 거래일."""
    y, m = after.year, after.month
    for _ in range(3):
        d = contribution_date(y, m)
        if d > after:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    raise RuntimeError("적립일을 찾지 못했습니다")


def contribution_dates(start: date, end: date) -> list[date]:
    out = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        d = contribution_date(y, m)
        if start <= d <= end:
            out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


# ── 한국 시간표 ───────────────────────────────────
@dataclass(frozen=True)
class SessionKST:
    session: date            # 미국 거래일
    summer: bool             # 미국 서머타임 여부
    early_close: bool        # 조기 폐장일 (예: 추수감사절 다음 날)
    open_kst: datetime
    close_kst: datetime
    after_start_kst: datetime
    after_end_kst: datetime


def session_kst(d: date) -> SessionKST:
    """미국 거래일 d 의 정규장·애프터마켓을 한국 시간으로.

    정규장 09:30 ET ~ 마감(보통 16:00, 조기폐장 13:00), 애프터마켓은 마감 후 4시간.
    서머타임은 zoneinfo 가 날짜별로 알아서 적용한다.
    """
    row = schedule().loc[pd.Timestamp(d)]
    close_et = row["market_close"].tz_convert(ET).to_pydatetime()
    open_et = datetime.combine(d, time(9, 30), tzinfo=ET)
    after_end_et = close_et + timedelta(hours=4)
    return SessionKST(
        session=d,
        summer=bool(open_et.dst()),
        early_close=close_et.time() != time(16, 0),
        open_kst=open_et.astimezone(KST),
        close_kst=close_et.astimezone(KST),
        after_start_kst=close_et.astimezone(KST),
        after_end_kst=after_end_et.astimezone(KST),
    )


# ── 표시용 ───────────────────────────────────────
def fmt_date(d: date) -> str:
    return f"{d:%Y-%m-%d} ({WEEKDAY_KO[d.weekday()]})"


def fmt_kst(dt: datetime, with_date: bool = True) -> str:
    dt = dt.astimezone(KST)
    if with_date:
        return f"{dt.month}/{dt.day}({WEEKDAY_KO[dt.weekday()]}) {dt:%H:%M}"
    return f"{dt:%H:%M}"
