"""RSI2 와 사냥 (내부용). T6 판정 로직은 건드리지 않고, T6 피신 여부만 읽어서 쓴다.

사냥 진입: T6 피신(QQQ 종가가 50·200일선 둘 다 아래) + 그날 QQQ RSI2 < 10 → 피신 현금 전액으로 TQQQ
사냥 종료: RSI2 > 50, 또는 진입 후 5거래일째 종가 (그날 RSI2 < 10 이면 계속 보유하고 그날부터 다시 5일),
          사냥 중 T6 가 맑음으로 바뀌면 TQQQ 는 그대로 두고 사냥만 끝
매매: 미국 정규장 마감 10분 전 가격 기준 (사용자가 직접)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from . import market_time as mt
from . import store

RSI_BUY, RSI_SELL, HOLD_DAYS = 10.0, 50.0, 5
NEAR = 0.01            # 매수 기준 1% 안으로 다가오면 '사냥 대기'
TIGHT = 0.003          # 기준과 0.3% 안이면 '애매'
CHECK_BEFORE = timedelta(minutes=10)


# ── 계산 (백테스트와 똑같은 방식) ─────────────────
def rsi2_state(closes):            # closes: QQQ 일봉 종가 (수정 종가, 오래된 순)
    au = ad = 0.0; out = []        # noqa: E702
    for t in range(len(closes)):
        if t == 0: out.append((50.0, 0.0, 0.0)); continue                  # noqa: E701,E702
        d = closes[t] - closes[t-1]; u = max(d, 0.0); v = max(-d, 0.0)     # noqa: E226,E702
        if t == 1: au, ad = u, v                                            # noqa: E701
        else: au, ad = 0.5*au + 0.5*u, 0.5*ad + 0.5*v                       # noqa: E226,E701
        rsi = 100.0 if ad == 0 else 100 - 100/(1 + au/ad)                   # noqa: E226
        out.append((rsi, au, ad))
    return out                     # (RSI2, au, ad)


def rsi_next(price: float, C0: float, A0: float, D0: float) -> float:
    """어제 종가 C0·au A0·ad D0 에서, 오늘 종가가 price 라면 RSI2."""
    d = price - C0
    au, ad = 0.5 * A0 + 0.5 * max(d, 0.0), 0.5 * D0 + 0.5 * max(-d, 0.0)
    return 100.0 if ad == 0 else 100 - 100 / (1 + au / ad)


def signal_prices(C0, A0, D0, s49, s199):
    # RSI2 < 10이 되는 오늘 종가 상한
    k = 10/90; x = k*D0 - A0                                    # noqa: E226,E702
    buy = C0 + x if x > 0 else C0 + (D0 - A0/k)                 # noqa: E226
    # RSI2 > 50이 되는 오늘 종가 하한 (사냥 중일 때 매도 기준)
    y = D0 - A0
    sell = C0 + y if y >= 0 else C0 + (D0 - A0)
    # 오늘 종가가 이 값보다 낮으면 50·200일선 둘 다 아래 (피신 유지)
    refuge = min(s49/49, s199/199)   # s49 = 최근 49개 종가 합, s199 = 최근 199개 종가 합 (어제까지)  # noqa: E226
    return buy, sell, refuge


@dataclass
class Levels:
    as_of: date                 # 확정 종가 날짜 (어제)
    close: float                # QQQ 어제 종가 C0
    rsi: float                  # 확정 RSI2
    au: float
    ad: float
    buy_rsi: float              # RSI2 < 10 가격
    refuge: float               # 피신 유지 가격
    buy: float                  # 사냥 매수 기준 = min(buy_rsi, refuge)
    sell: float                 # 사냥 매도 기준 (RSI2 > 50)
    tqqq_close: float | None

    def tqqq_at(self, qqq_price: float) -> float | None:
        """TQQQ 대략 가격 = TQQQ 전일 종가 × (1 + 3 × (QQQ 가격 ÷ QQQ 전일 종가 − 1))."""
        if self.tqqq_close is None:
            return None
        return self.tqqq_close * (1 + 3 * (qqq_price / self.close - 1))


def levels(qqq_adj: pd.Series, tqqq_close: float | None = None) -> Levels:
    c = qqq_adj.astype(float).tolist()
    r, A0, D0 = rsi2_state(c)[-1]
    buy_rsi, sell, refuge = signal_prices(c[-1], A0, D0, sum(c[-49:]), sum(c[-199:]))
    return Levels(qqq_adj.index[-1].date(), c[-1], r, A0, D0, buy_rsi, refuge, min(buy_rsi, refuge), sell, tqqq_close)


def rsi_series(qqq_adj: pd.Series) -> pd.Series:
    return pd.Series([x[0] for x in rsi2_state(qqq_adj.astype(float).tolist())], index=qqq_adj.index)


# ── 사냥 회차 (종가 기록으로 자동 계산) ───────────
def hunts(rsi: pd.Series, refuge: pd.Series) -> pd.DataFrame:
    """rsi: 날짜별 RSI2, refuge: 날짜별 T6 피신 여부(True=피신). 거래일 순서대로.

    돌려주는 열: entry, exit(None=진행 중), reason, days(진입~종료 거래일 수), count_from(5일을 세기 시작한 날)
    """
    idx = rsi.index
    R, F = rsi.to_numpy(), refuge.reindex(idx).fillna(False).to_numpy(bool)
    rows, cur = [], None
    for i in range(len(idx)):
        if cur is None:
            if F[i] and R[i] < RSI_BUY:
                cur = {"e": i, "c": i}
            continue
        reason = None
        if not F[i]:
            reason = "T6 맑음 (TQQQ 그대로)"
        elif R[i] > RSI_SELL:
            reason = "RSI2>50"
        elif i - cur["c"] >= HOLD_DAYS:
            if R[i] < RSI_BUY:
                cur["c"] = i                         # 5일째에도 RSI2<10 → 그날부터 다시 5일
            else:
                reason = "5일"
        if reason:
            rows.append((idx[cur["e"]], idx[i], reason, i - cur["e"], idx[cur["c"]]))
            cur = None
    if cur is not None:
        rows.append((idx[cur["e"]], None, "진행 중", len(idx) - 1 - cur["e"], idx[cur["c"]]))
    return pd.DataFrame(rows, columns=["entry", "exit", "reason", "days", "count_from"])


def reverse_check(qqq_adj: pd.Series, refuge: pd.Series) -> pd.DataFrame:
    """역산 확인: 날마다 '종가 ≤ 어제 기준으로 계산한 사냥 매수 기준'과 'RSI2 < 10 그리고 피신'이 같은지.
    돌려주는 표: date, close, buy, by_price, by_rule, ok"""
    c = qqq_adj.astype(float).tolist()
    st_ = rsi2_state(c)
    rows = []
    F = refuge.reindex(qqq_adj.index)
    for t in range(200, len(c)):
        if pd.isna(F.iloc[t]):
            continue
        _, A0, D0 = st_[t - 1]
        buy_rsi, _, ref = signal_prices(c[t - 1], A0, D0, sum(c[t - 49:t]), sum(c[t - 199:t]))
        by_price = c[t] <= min(buy_rsi, ref)
        by_rule = st_[t][0] < RSI_BUY and bool(F.iloc[t])
        rows.append((qqq_adj.index[t], c[t], min(buy_rsi, ref), by_price, by_rule, by_price == by_rule))
    return pd.DataFrame(rows, columns=["date", "close", "buy", "by_price", "by_rule", "ok"])


# ── 시간 ─────────────────────────────────────────
def today_session(now: datetime) -> date | None:
    """지금 미국 날짜(ET)가 거래일이고 그날 장이 아직 안 끝났으면 그 날짜. 휴장일·주말·마감 뒤면 None."""
    et_day = now.astimezone(mt.ET).date()
    if not mt.is_session(et_day):
        return None
    if now >= mt.session_close_utc(et_day):
        return None
    return et_day


def check_time(session: date) -> datetime:
    """사냥 확인 시각 = 그날 정규장 마감 10분 전 (겨울 05:50 KST, 여름 04:50 KST, 조기 폐장일도 맞춤)."""
    return mt.session_close_utc(session) - CHECK_BEFORE


def market_open(now: datetime, session: date | None) -> bool:
    if session is None:
        return False
    op = mt.schedule().loc[pd.Timestamp(session), "market_open"].to_pydatetime()
    return op <= now < mt.session_close_utc(session)


# ── 오늘의 사냥 상태 ─────────────────────────────
@dataclass
class HuntView:
    kind: str | None            # None / "wait" ① / "enter" ② / "hunting" ③ / "exit" ④
    lv: Levels
    live: float | None
    live_rsi: float | None
    day: int | None = None      # 사냥 중 며칠째 (오늘 기준)
    day5: date | None = None    # 5일째 날짜
    entry: pd.Timestamp | None = None
    tight: bool = False         # 기준과 0.3% 안 (애매)
    note: str = ""


def hunt_view(lv: Levels, refuge_now: bool, episodes: pd.DataFrame, session: date | None,
              live: float | None, skipped: set) -> HuntView:
    """확정 데이터(어제까지)와 실시간 가격으로 오늘 보여줄 사냥 칸을 정한다. 휴장일(session=None)이면 없음."""
    lr = rsi_next(live, lv.close, lv.au, lv.ad) if live is not None else None
    v = HuntView(None, lv, live, lr)
    if session is None:
        return v
    cur = episodes[episodes["exit"].isna()] if not episodes.empty else episodes
    if len(cur):
        ep = cur.iloc[-1]
        v.entry = ep["entry"]
        if ep["entry"].date().isoformat() in skipped:
            return v
        sess = mt.sessions()
        i0 = sess.get_loc(pd.Timestamp(ep["count_from"]))
        it = sess.get_loc(pd.Timestamp(session))
        v.day = int(sess.get_loc(pd.Timestamp(session)) - sess.get_loc(pd.Timestamp(ep["entry"])))
        v.day5 = sess[i0 + HOLD_DAYS].date()
        is_day5 = it - i0 >= HOLD_DAYS
        if lr is not None and lr > RSI_SELL:
            v.kind, v.note = "exit", f"RSI2 {lr:.1f}"
        elif is_day5 and (lr is None or lr >= RSI_BUY):
            v.kind, v.note = "exit", "5일째"
        else:
            v.kind = "hunting"
            if live is not None and live >= lv.refuge:
                v.note = "선 회복 중 → 마감에 맑음이면 TQQQ 그대로, 사냥만 끝"
        return v
    if not refuge_now or live is None:
        return v
    v.tight = abs(live / lv.buy - 1) < TIGHT
    if lr < RSI_BUY and live < lv.refuge:
        v.kind = "enter"
    elif 0 <= live / lv.buy - 1 <= NEAR:
        v.kind = "wait"
    return v


# ── 이번 사냥 건너뜀 (SQLite) ────────────────────
SKIP = "CREATE TABLE IF NOT EXISTS hunt_skip (entry TEXT PRIMARY KEY, at TEXT)"


def skipped(path=None) -> set:
    with store.connect(path) as con:
        con.execute(SKIP)
        return {r[0] for r in con.execute("SELECT entry FROM hunt_skip")}


def set_skip(entry: date, on: bool, path=None) -> None:
    with store.connect(path) as con:
        con.execute(SKIP)
        if on:
            con.execute("INSERT OR REPLACE INTO hunt_skip (entry, at) VALUES (?, ?)",
                        (entry.isoformat(), datetime.now(timezone.utc).isoformat(timespec="seconds")))
        else:
            con.execute("DELETE FROM hunt_skip WHERE entry = ?", (entry.isoformat(),))
