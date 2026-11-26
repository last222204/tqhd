"""🎲 월요일 아침 QQQ·TQQQ 출발 예상가 (재미용). 우산 신호·계산 엔진과 완전히 따로 동작한다.

재료는 나스닥 관련만:
  금요일 정규장 종가 → 애프터마켓 마지막 가격 → 주말 나스닥100 무기한 선물(코인 거래소) → 나스닥 선물(열리면)

예상 갭 (우선순위가 높은 것 하나를 쓴다):
  1. 나스닥 선물이 열렸으면      : 나스닥 선물 지금 ÷ 금요일 미국 마감 시각 나스닥 선물 − 1
  2. 애프터마켓 + 무기한 선물    : (1 + 애프터마켓 변화) × (1 + 애프터마켓 끝난 뒤 무기한 선물 변화) − 1
  3. 무기한 선물만               : 무기한 선물 지금 ÷ 금요일 미국 마감 시각 − 1
  4. 애프터마켓만                : 애프터마켓 마지막 ÷ 정규장 종가 − 1
QQQ 출발가 = 금요일 종가 × (1 + 예상 갭),  TQQQ 출발가 = 금요일 종가 × (1 + 3 × 예상 갭)
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from . import market_time as mt
from . import store

LEVERAGE = 3            # TQQQ
FLAT = 0.003            # 예상 갭이 ±0.3% 안이면 '보합'
UP, FLAT_L, DOWN = "갭상승", "보합", "갭하락"
METHODS = {
    "nq": "나스닥 선물",
    "ah_perp": "애프터마켓 + 주말 무기한 선물",
    "perp": "주말 무기한 선물",
    "ah": "애프터마켓",
    "none": "재료 없음 (금요일 종가 그대로)",
}


# ── 시간표 ───────────────────────────────────────
@dataclass
class Times:
    us_anchor: date            # 마지막으로 마감한 미국 거래일 (보통 금요일)
    us_next: date              # 다음 미국 거래일 (출발가를 맞힐 날)
    us_close: datetime         # 미국 정규장 마감 (UTC)
    ah_end: datetime           # 애프터마켓 끝
    fut_open: datetime         # 나스닥 선물 다시 열리는 시각
    us_open: datetime          # 다음 미국 정규장 시작
    weekend: bool              # 거래일 사이가 주말·휴장으로 3일 이상 벌어졌나
    us_monday_holiday: bool    # 주말 바로 뒤 월요일이 미국 휴장


def _monday_after(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7 or 7)


def times(now: datetime) -> Times:
    us_anchor = mt.last_completed_session(now)
    us_next = mt.next_session_after(us_anchor)
    us_close = mt.session_close_utc(us_anchor)
    us_open = mt.schedule().loc[pd.Timestamp(us_next), "market_open"].to_pydatetime()
    # CME 나스닥 선물은 다음 거래일 전날 18:00 ET 에 다시 열린다 (보통 일요일 저녁)
    fut_open = datetime.combine(us_next - timedelta(days=1), time(18, 0), tzinfo=mt.ET).astimezone(timezone.utc)
    weekend = (us_next - us_anchor).days >= 3
    return Times(us_anchor, us_next, us_close, us_close + timedelta(hours=4), fut_open, us_open, weekend,
                 weekend and not mt.is_session(_monday_after(us_anchor)))


# ── 예상 ─────────────────────────────────────────
def change(now_px, ref_px) -> float | None:
    if now_px is None or ref_px is None or ref_px == 0 or not np.isfinite(now_px) or not np.isfinite(ref_px):
        return None
    return float(now_px) / float(ref_px) - 1


def label_of(x: float | None) -> str | None:
    if x is None or not math.isfinite(x):
        return None
    return UP if x > FLAT else (DOWN if x < -FLAT else FLAT_L)


@dataclass
class Estimate:
    gap: float | None
    method: str                                  # METHODS 의 키
    steps: list = field(default_factory=list)    # (설명, 변화율) — 화면에 계산 과정을 보여주기용


def estimate_gap(ah: float | None = None, perp_close: float | None = None, perp_after_ah: float | None = None,
                 nq: float | None = None) -> Estimate:
    """ah: 애프터마켓 변화(종가 대비), perp_close: 무기한 선물 금요일 마감 이후 변화,
    perp_after_ah: 무기한 선물 애프터마켓 끝난 뒤 변화, nq: 나스닥 선물 금요일 마감 이후 변화."""
    ok = (lambda x: x is not None and math.isfinite(x))
    if ok(nq):
        return Estimate(nq, "nq", [("나스닥 선물 (금요일 미국 마감 이후)", nq)])
    if ok(ah) and ok(perp_after_ah):
        g = (1 + ah) * (1 + perp_after_ah) - 1
        return Estimate(g, "ah_perp", [("애프터마켓 (정규장 종가 → 20:00 ET)", ah),
                                       ("주말 무기한 선물 (애프터마켓 끝 → 지금)", perp_after_ah)])
    if ok(perp_close):
        return Estimate(perp_close, "perp", [("주말 무기한 선물 (금요일 마감 → 지금)", perp_close)])
    if ok(ah):
        return Estimate(ah, "ah", [("애프터마켓 (정규장 종가 → 20:00 ET)", ah)])
    return Estimate(0.0, "none", [])


def open_prices(est: Estimate, qqq_close: float | None, tqqq_close: float | None) -> tuple[float | None, float | None]:
    q = qqq_close * (1 + est.gap) if qqq_close is not None and est.gap is not None else None
    t = tqqq_close * (1 + LEVERAGE * est.gap) if tqqq_close is not None and est.gap is not None else None
    return q, t


# ── 가격 도우미 ──────────────────────────────────
def price_at(series: pd.Series, when: datetime) -> float | None:
    """when 시각 이전 마지막 값 (series 인덱스는 시간대가 있는 시각)."""
    if series is None or series.empty:
        return None
    s = series[series.index <= pd.Timestamp(when)]
    return float(s.iloc[-1]) if len(s) else None


def ah_last(intraday: pd.DataFrame, close_utc: datetime) -> float | None:
    """정규장 마감 뒤 4시간(애프터마켓) 안의 마지막 가격."""
    if intraday is None or intraday.empty:
        return None
    ix = intraday.index.tz_convert("UTC")
    m = (ix >= pd.Timestamp(close_utc)) & (ix < pd.Timestamp(close_utc) + pd.Timedelta(hours=4))
    s = intraday["close"][m].dropna()
    return float(s.iloc[-1]) if len(s) else None


# ── 과거 데이터로: 같은 방법을 썼다면 얼마나 맞았나 ──
def weekend_anchors(sessions: pd.DatetimeIndex, start: str = "2018-01-01") -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """다음 거래일까지 3일 이상 벌어진 거래일(보통 금요일)과 그다음 거래일."""
    s = sessions[sessions >= pd.Timestamp(start)]
    return [(a, b) for a, b in zip(s[:-1], s[1:]) if (b - a).days >= 3]


def gap_of(daily: pd.DataFrame, anchor, nxt) -> float | None:
    try:
        return float(daily.loc[pd.Timestamp(nxt), "open"] / daily.loc[pd.Timestamp(anchor), "close"] - 1)
    except KeyError:
        return None


def perp_cutoff(anchor: date) -> datetime:
    """무기한 선물 가격을 고정하는 시각: 그 주말 일요일 18:00 ET (= 월요일 08:00 KST 겨울 / 07:00 여름,
    나스닥 선물이 열리는 순간). 월요일이 휴장이어도 같은 시각을 쓴다."""
    sunday = anchor + timedelta(days=(6 - anchor.weekday()) % 7 or 7)
    return datetime.combine(sunday, time(18, 0), tzinfo=mt.ET).astimezone(timezone.utc)


def price_before(series: pd.Series, when: datetime, max_age: timedelta = timedelta(hours=2)) -> float | None:
    """when 직전 값. when 이후 가격은 절대 쓰지 않고, 직전 값이 max_age 보다 오래됐으면 None (낡은 값 방지)."""
    if series is None or series.empty:
        return None
    s = series[series.index <= pd.Timestamp(when)]
    if s.empty or pd.Timestamp(when) - s.index[-1] > max_age:
        return None
    return float(s.iloc[-1])


def backtest(qqq: pd.DataFrame, qqq_60m: pd.DataFrame | None, perp_1h: pd.Series | None, sessions) -> pd.DataFrame:
    """주말마다 예측과 실제 갭.
      ah      (가) 애프터마켓만
      ah_perp (나) 애프터마켓 + 무기한 선물 (애프터마켓 끝 → 월요일 08:00 KST 직전)
      flat    (다) 보합 0%
      perp    (참고) 무기한 선물만 (금요일 마감 → 월요일 08:00 KST 직전)
    무기한 선물은 월요일 08:00 KST(여름 07:00) 직전 값으로 고정하고, 그 이후 가격은 쓰지 않는다."""
    rows = []
    for a, b in weekend_anchors(sessions):
        actual = gap_of(qqq, a, b)
        if actual is None:
            continue
        close = qqq.loc[a, "close"]
        t_close = mt.session_close_utc(a.date())
        t_ah = t_close + timedelta(hours=4)
        t_cut = perp_cutoff(a.date())
        ah = None
        if qqq_60m is not None and not qqq_60m.empty and pd.Timestamp(t_close) >= qqq_60m.index[0]:
            ah = change(ah_last(qqq_60m, t_close), close)
        p_close = p_ah = None
        if perp_1h is not None and not perp_1h.empty and pd.Timestamp(t_close) >= perp_1h.index[0]:
            cut = price_before(perp_1h, t_cut)
            p_close = change(cut, price_before(perp_1h, t_close))
            p_ah = change(cut, price_before(perp_1h, t_ah))
        rows.append({
            "anchor": a, "actual": actual,
            "ah": ah,
            "ah_perp": estimate_gap(ah=ah, perp_after_ah=p_ah).gap if ah is not None and p_ah is not None else None,
            "flat": 0.0,
            "perp": p_close,
        })
    return pd.DataFrame(rows, columns=["anchor", "actual", "ah", "ah_perp", "flat", "perp"])


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """적중률의 95% 범위 (윌슨 구간)."""
    if n <= 0:
        return None
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


BIG_GAP = 0.01


def _dir(d: pd.DataFrame, method: str) -> dict:
    """방향 적중: 예상과 실제의 부호가 같은 비율. 예상이 0(보합)인 방법은 방향이 없어서 계산하지 않는다."""
    nz = d[(d[method] != 0) & (d["actual"] != 0)]
    if nz.empty:
        return {"n": 0, "k": 0, "hit": None, "ci": None}
    k = int((np.sign(nz[method]) == np.sign(nz["actual"])).sum())
    return {"n": len(nz), "k": k, "hit": k / len(nz), "ci": wilson(k, len(nz))}


def accuracy(bt: pd.DataFrame, method: str, rows: pd.Index | None = None) -> dict:
    """한 예측 방법의 성적. rows 를 주면 그 주말들만 (세 방법을 같은 표본으로 비교할 때).

    n        표본 수 (주말)
    hit, ci  방향 적중률과 95% 범위 (보합 예측은 없음)
    hit3     3단계 적중률: 갭상승·보합·갭하락(±0.3%) 구간이 같은 비율 (보합 예측도 계산됨)
    corr     상관계수 (보합 예측은 없음)
    mae      평균 오차 = |예상 갭 − 실제 갭| 의 평균 (비율, 0.0065 = 0.65%p)
    big      갭이 1% 넘은 주만: 방향 적중률·95% 범위·표본 수
    """
    empty = {"n": 0, "mae": None, "hit": None, "ci": None, "hit3": None, "corr": None,
             "big": {"n": 0, "hit": None, "ci": None}}
    if bt is None or bt.empty or method not in bt:
        return empty
    d = bt.loc[rows] if rows is not None else bt
    d = d[["actual", method]].dropna()
    if len(d) < 3:
        return {**empty, "n": len(d)}
    dr = _dir(d, method)
    big = _dir(d[d["actual"].abs() > BIG_GAP], method)
    lab = d[method].map(label_of) == d["actual"].map(label_of)
    corr = float(np.corrcoef(d[method], d["actual"])[0, 1]) if d[method].std() > 0 else None
    return {"n": len(d), "mae": float((d[method] - d["actual"]).abs().mean()), "hit": dr["hit"], "ci": dr["ci"],
            "hit3": float(lab.mean()), "corr": corr,
            "big": {"n": big["n"] if dr["hit"] is not None else int((d["actual"].abs() > BIG_GAP).sum()),
                    "hit": big["hit"], "ci": big["ci"]}}


def compare(bt: pd.DataFrame) -> tuple[dict, pd.Index]:
    """(가) 애프터마켓만 · (나) 애프터마켓 + 무기한 선물 · (다) 보합 을 같은 주말들로 비교."""
    if bt is None or bt.empty:
        return {}, pd.Index([])
    common = bt.dropna(subset=["actual", "ah", "ah_perp"]).index
    return {m: accuracy(bt, m, common) for m in ("ah", "ah_perp", "flat")}, common


# ── 예상가 장부 (SQLite 별도 표) ─────────────────
LEDGER = """
CREATE TABLE IF NOT EXISTS open_ledger (
    week        TEXT PRIMARY KEY,     -- 미국 기준일 (보통 금요일)
    us_next     TEXT,                 -- 출발가를 맞힐 날
    updated_at  TEXT,
    method      TEXT,
    gap_est     REAL,
    qqq_close REAL, qqq_est REAL, qqq_open REAL,
    tqqq_close REAL, tqqq_est REAL, tqqq_open REAL,
    inputs      TEXT
);
"""


def ensure_table(path=None) -> None:
    with store.connect(path) as con:
        con.executescript(LEDGER)


def save_estimate(t: Times, est: Estimate, qqq_close, tqqq_close, inputs: dict, now: datetime, path=None) -> bool:
    """주말 한 줄. 미국 정규장이 열리기 전까지만 최신 예상으로 덮어쓴다. 저장했으면 True."""
    ensure_table(path)
    if now >= t.us_open:
        return False
    q, tq = open_prices(est, qqq_close, tqqq_close)
    with store.connect(path) as con:
        con.execute("INSERT OR IGNORE INTO open_ledger (week, us_next) VALUES (?, ?)",
                    (t.us_anchor.isoformat(), t.us_next.isoformat()))
        con.execute("UPDATE open_ledger SET updated_at=?, method=?, gap_est=?, qqq_close=?, qqq_est=?, "
                    "tqqq_close=?, tqqq_est=?, inputs=? WHERE week=?",
                    (now.astimezone(timezone.utc).isoformat(timespec="seconds"), est.method, est.gap,
                     qqq_close, q, tqqq_close, tq, json.dumps(inputs), t.us_anchor.isoformat()))
    return True


def settle(qqq: pd.DataFrame | None, tqqq: pd.DataFrame | None, path=None) -> int:
    """다음 거래일 시가가 나온 주는 실제 시가를 채운다. 채운 칸 수를 돌려준다."""
    ensure_table(path)
    n = 0
    with store.connect(path) as con:
        for week, nxt, qo, to in con.execute("SELECT week, us_next, qqq_open, tqqq_open FROM open_ledger").fetchall():
            for col, have, df in (("qqq_open", qo, qqq), ("tqqq_open", to, tqqq)):
                if have is None and df is not None:
                    try:
                        v = float(df.loc[pd.Timestamp(nxt), "open"])
                    except KeyError:
                        continue
                    con.execute(f"UPDATE open_ledger SET {col}=? WHERE week=?", (v, week))
                    n += 1
    return n


def ledger(path=None) -> pd.DataFrame:
    ensure_table(path)
    with store.connect(path) as con:
        df = pd.read_sql_query("SELECT * FROM open_ledger ORDER BY week DESC", con)
    for c in ("gap_est", "qqq_close", "qqq_est", "qqq_open", "tqqq_close", "tqqq_est", "tqqq_open"):
        df[c] = pd.to_numeric(df[c])
    df["qqq_err"] = df["qqq_est"] / df["qqq_open"] - 1
    df["tqqq_err"] = df["tqqq_est"] / df["tqqq_open"] - 1
    df["dir_hit"] = [None if pd.isna(o) or pd.isna(g) else bool(np.sign(g) == np.sign(o / c - 1))
                     for g, o, c in zip(df["gap_est"], df["qqq_open"], df["qqq_close"])]
    return df


def ledger_stats(df: pd.DataFrame) -> dict:
    done = df[df["qqq_open"].notna()]
    if done.empty:
        return {"n": 0, "qqq_mae": None, "tqqq_mae": None, "hit": None}
    return {"n": len(done), "qqq_mae": float(done["qqq_err"].abs().mean()),
            "tqqq_mae": float(done["tqqq_err"].abs().mean()) if done["tqqq_err"].notna().any() else None,
            "hit": float(done["dir_hit"].dropna().astype(bool).mean()) if done["dir_hit"].notna().any() else None}
