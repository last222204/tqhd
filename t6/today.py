"""'오늘' 화면에 보여줄 내용을 계산한다 (화면 그리기와 분리해서 테스트할 수 있게)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

import pandas as pd

from . import market_time as mt
from .config import REFUGE_LABEL, RISK_OFF, RISK_ON
from .strategy import alert_level


@dataclass
class TodayView:
    as_of: date                    # 판정에 쓴 미국 종가 날짜
    signal: str                    # 'TQQQ' / 'SGOV'
    prev_signal: str | None
    switched: bool
    close: float
    sma_fast: float
    sma_slow: float
    dist_fast: float
    dist_slow: float
    border: bool
    vol: float
    alert: str | None              # 'red' / 'yellow' / None
    raw: dict                      # 배당 미조정 기준 참고값
    steps: list[str] = field(default_factory=list)
    when: list[str] = field(default_factory=list)
    next_judgement_kst: datetime | None = None
    next_contribution: date | None = None
    next_contribution_kst: mt.SessionKST | None = None
    session: mt.SessionKST | None = None
    next_session: mt.SessionKST | None = None


def build(sf: pd.DataFrame, sf_raw: pd.DataFrame, now: datetime | None = None) -> TodayView:
    now = now or datetime.now(timezone.utc)
    sf = sf.dropna(subset=["signal"])
    last = sf.iloc[-1]
    prev = sf.iloc[-2] if len(sf) > 1 else None
    d = sf.index[-1].date()
    r = sf_raw.loc[sf.index[-1]]

    v = TodayView(
        as_of=d,
        signal=last["signal"],
        prev_signal=None if prev is None else prev["signal"],
        switched=bool(last["switch"]),
        close=float(last["close"]),
        sma_fast=float(last["sma_fast"]),
        sma_slow=float(last["sma_slow"]),
        dist_fast=float(last["dist_fast"]),
        dist_slow=float(last["dist_slow"]),
        border=bool(last["border"]),
        vol=float(last["vol"]),
        alert=alert_level(bool(last["close"] >= last["sma_slow"]), float(last["vol"])),
        raw={
            "close": float(r["close"]),
            "sma_fast": float(r["sma_fast"]),
            "sma_slow": float(r["sma_slow"]),
            "dist_fast": float(r["dist_fast"]),
            "dist_slow": float(r["dist_slow"]),
            "signal": r["signal"],
            "border": bool(r["border"]),
        },
    )

    s = mt.session_kst(d)
    v.session = s
    nxt = mt.session_kst(mt.next_session_after(d))
    v.next_session = nxt
    v.next_judgement_kst = nxt.close_kst

    if v.switched:
        if v.signal == RISK_OFF:          # 피신: 피신 자금은 현금(달러)으로 둔다
            v.steps = [
                f"{RISK_ON} 전량 매도 (지정가)",
                f"매도 대금은 {REFUGE_LABEL}으로 보유",
                "체결 후 '매매 기록'에 수량·체결가·환율 입력",
            ]
        else:
            v.steps = [
                f"피신 {REFUGE_LABEL} 전액으로 {RISK_ON} 매수 (지정가)",
                "체결 후 '매매 기록'에 수량·체결가·환율 입력",
            ]
        after = f"애프터마켓 {mt.fmt_kst(s.after_start_kst)} ~ {mt.fmt_kst(s.after_end_kst, False)}"
        regular = f"정규장 {mt.fmt_kst(nxt.open_kst)} ~ {mt.fmt_kst(nxt.close_kst)}"
        if now < s.after_end_kst:
            v.when = [f"1순위: {after}", f"못 하면: 그날 밤 {regular}에서 마무리"]
        else:
            v.when = [f"애프터마켓은 끝났습니다 ({after})", f"지금 할 일: {regular}에서 마무리"]

    v.next_contribution = mt.next_contribution_date(d)
    v.next_contribution_kst = mt.session_kst(v.next_contribution)
    return v
