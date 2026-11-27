"""매일 한 번 (GitHub Actions, 한국시간 07:00): 시세를 받아 data/state.json 을 만들고 data/history.csv 에 한 줄 쌓는다.

사용: python scripts/update_state.py            (data/ 에 씀)
      python scripts/update_state.py --out DIR  (다른 폴더에 씀)
소유자는 아무것도 입력하지 않는다. 기존 history.csv 줄은 절대 고치지 않고 새 날짜만 덧붙인다.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tqhd as T  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HISTORY_START = "1999-01-01"
RECENT_DAYS = 60
CHART_DAYS = 400
HISTORY_COLS = ["date", "qqq_close", "sma50", "sma200", "rsi2", "state", "weight", "recorded_at", "source"]
ET = "America/New_York"


# ── 장 달력 ─────────────────────────────────────
def _cal():
    import pandas_market_calendars as mcal
    return mcal.get_calendar("NYSE")


def schedule(start, end) -> pd.DataFrame:
    """NYSE 거래일별 개장·마감 시각 (UTC). 조기 폐장 반영."""
    return _cal().schedule(start_date=str(start), end_date=str(end))


def holiday_name(d: date) -> str:
    """평일 휴장일의 한국어 이름 (화면 표시용)."""
    m, day, wd = d.month, d.day, d.weekday()
    if m == 1 and day <= 2:
        return "새해 첫날"
    if m == 1 and wd == 0 and 15 <= day <= 21:
        return "마틴 루터 킹 데이"
    if m == 2 and wd == 0 and 15 <= day <= 21:
        return "대통령의 날"
    if m in (3, 4) and wd == 4:
        return "성금요일"
    if m == 5 and wd == 0 and day >= 25:
        return "메모리얼 데이"
    if m == 6 and 18 <= day <= 20:
        return "준틴스"
    if m == 7 and 3 <= day <= 5:
        return "독립기념일"
    if m == 9 and wd == 0 and day <= 7:
        return "노동절"
    if m == 11 and wd == 3 and 22 <= day <= 28:
        return "추수감사절"
    if m == 12 and 24 <= day <= 26:
        return "크리스마스"
    return "임시 휴장"


def calendar_block(as_of: date, days_ahead: int = 40) -> dict:
    """as_of 거래일부터 앞으로의 거래일(개장·마감 UTC)과 평일 휴장일."""
    sch = schedule(as_of, as_of + timedelta(days=days_ahead))
    sessions = [{"date": str(idx.date()),
                 "open_utc": row["market_open"].tz_convert("UTC").isoformat().replace("+00:00", "Z"),
                 "close_utc": row["market_close"].tz_convert("UTC").isoformat().replace("+00:00", "Z")}
                for idx, row in sch.iterrows()]
    open_days = {s["date"] for s in sessions}
    holidays = []
    d = as_of
    while d <= as_of + timedelta(days=days_ahead):
        if d.weekday() < 5 and str(d) not in open_days:
            holidays.append({"date": str(d), "name": holiday_name(d)})
        d += timedelta(days=1)
    return {"sessions": sessions, "holidays": holidays}


def completed_sessions(index: pd.DatetimeIndex, now: datetime) -> pd.DatetimeIndex:
    """마감이 지난 거래일만 (장중에 돌려도 오늘 미완성 막대를 쓰지 않게)."""
    sch = schedule(index[0].date(), now.date() + timedelta(days=1))
    closed = sch.index[sch["market_close"] <= pd.Timestamp(now)]
    return index[index.isin(closed)]


# ── 시세 받기 ───────────────────────────────────
def fetch_daily(symbol: str, start: str = HISTORY_START) -> pd.Series:
    import yfinance as yf
    df = yf.download(symbol, start=start, auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"{symbol} 일봉을 받지 못했습니다")
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s = s.dropna()
    s.index = pd.DatetimeIndex(s.index).tz_localize(None).normalize()
    return s.astype(float)


def nq_at_close(close_utc: pd.Timestamp):
    """그 거래일 현물 마감 시각(=CME 정산 시각)의 NQ=F 가격. 5분봉 → 없으면 일봉 종가."""
    import yfinance as yf
    try:
        df = yf.download("NQ=F", period="10d", interval="5m", auto_adjust=False, progress=False, threads=False)
        c = df["Close"]
        if isinstance(c, pd.DataFrame):
            c = c.iloc[:, 0]
        c = c.dropna()
        idx = pd.DatetimeIndex(c.index)
        idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
        c.index = idx
        before = c[c.index < close_utc]                       # 마감 직전 5분봉의 종가 = 마감 시각 가격
        if len(before) and close_utc - before.index[-1] <= pd.Timedelta(minutes=10):
            return float(before.iloc[-1]), close_utc.isoformat().replace("+00:00", "Z"), "5분봉"
    except Exception as e:  # noqa: BLE001
        print("NQ 5분봉 실패:", e)
    s = fetch_daily("NQ=F", start=str((close_utc - pd.Timedelta(days=10)).date()))
    d = close_utc.tz_convert(ET).normalize().tz_localize(None)
    if d in s.index:
        return float(s.loc[d]), close_utc.isoformat().replace("+00:00", "Z"), "일봉 종가"
    return None, None, "없음"


def fetch_fx():
    import yfinance as yf
    df = yf.download("KRW=X", period="10d", interval="1d", auto_adjust=False, progress=False, threads=False)
    c = df["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    c = c.dropna()
    return {"price": round(float(c.iloc[-1]), 2), "date": str(pd.Timestamp(c.index[-1]).date())}


# ── 계산 ────────────────────────────────────────
def compute(closes: pd.Series) -> pd.DataFrame:
    """전체 기간의 이동평균·RSI2·상태. 장중 계산과 같은 공식을 쓴다."""
    c = closes.to_numpy(dtype=float)
    n = len(c)
    rsi, ag, al = T.wilder_rsi2(list(c))
    sma50 = [math.nan] * n
    sma200 = [math.nan] * n
    for i in range(n):                       # 장중과 똑같이: (직전 n-1일 합 + 오늘) / n
        if i >= T.FAST - 1:
            sma50[i] = T.live_sma(sum(c[i - T.FAST + 1:i]), T.FAST, c[i])
        if i >= T.SLOW - 1:
            sma200[i] = T.live_sma(sum(c[i - T.SLOW + 1:i]), T.SLOW, c[i])
    state, weight = [None] * n, [None] * n
    prev_s, prev_w = None, 0
    for i in range(n):
        if math.isnan(sma200[i]) or math.isnan(rsi[i]):
            continue
        s, w = T.next_state(prev_s, prev_w, T.is_night(c[i], sma50[i], sma200[i]), rsi[i])
        state[i], weight[i] = s, w
        prev_s, prev_w = s, w
    return pd.DataFrame({"close": c, "sma50": sma50, "sma200": sma200, "rsi2": rsi,
                         "avg_gain": ag, "avg_loss": al, "state": state, "weight": weight}, index=closes.index)


def base_at(closes: pd.Series, frame: pd.DataFrame, i: int) -> dict:
    """i 번째 거래일 종가까지의 누적값 = 다음 거래일 장중 계산의 재료."""
    c = closes.to_numpy(dtype=float)
    return {
        "qqq_prev_close": float(c[i]),
        "sum_prev_49": float(sum(c[i - T.FAST + 2:i + 1])),
        "sum_prev_199": float(sum(c[i - T.SLOW + 2:i + 1])),
        "wilder_avg_gain": float(frame["avg_gain"].iloc[i]),
        "wilder_avg_loss": float(frame["avg_loss"].iloc[i]),
        "prev_state": frame["state"].iloc[i],
        "prev_weight": int(frame["weight"].iloc[i]),
    }


def night_ratio(frame: pd.DataFrame) -> dict:
    st = frame["state"].dropna()
    out = {}
    for k, n in (("1m", 21), ("3m", 63), ("12m", 252)):
        tail = st.iloc[-n:]
        out[k] = round(float((tail != T.DAY).mean()) * 100, 1)
    return out


def _r(x, k=6):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), k)


def build_state(qqq: pd.Series, tqqq: pd.Series, now: datetime, nq=None, fx=None) -> tuple[dict, pd.DataFrame]:
    qqq = qqq.loc[completed_sessions(qqq.index, now)]
    tqqq = tqqq.loc[tqqq.index.isin(qqq.index)]
    frame = compute(qqq)
    i = len(qqq) - 1
    as_of = qqq.index[i].date()
    sch = schedule(as_of, as_of)
    close_utc = sch["market_close"].iloc[0].tz_convert("UTC")
    base = base_at(qqq, frame, i)
    last = frame.iloc[i]
    nq_price, nq_time, nq_src = nq if nq else (None, None, "없음")
    state = {
        "version": 1,
        "generated_at": now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "as_of": str(as_of),
        "as_of_close_utc": close_utc.isoformat().replace("+00:00", "Z"),
        "price_basis": "배당조정 종가 (yfinance auto_adjust)",
        **base,
        "tqqq_prev_close": float(tqqq.loc[qqq.index[i]]) if qqq.index[i] in tqqq.index else None,
        "nq_prev_settle": nq_price,
        "nq_prev_settle_time": nq_time,
        "nq_prev_settle_source": nq_src,
        "confirmed": {"date": str(as_of), "close": _r(last["close"]), "sma50": _r(last["sma50"]),
                      "sma200": _r(last["sma200"]), "rsi2": _r(last["rsi2"]),
                      "state": last["state"], "weight": int(last["weight"])},
        "usdkrw": fx,
        "night_ratio": night_ratio(frame),
        "recent": [{"date": str(d.date()), "close": _r(r["close"], 4), "rsi2": _r(r["rsi2"], 2),
                    "state": r["state"], "weight": int(r["weight"])}
                   for d, r in frame.iloc[-RECENT_DAYS:].iterrows()],
        "calendar": calendar_block(as_of),
        "params": {"fast": T.FAST, "slow": T.SLOW, "hunt_half": T.HUNT_HALF,
                   "hunt_full": T.HUNT_FULL, "hunt_exit": T.HUNT_EXIT},
    }
    return state, frame


def append_history(path: Path, frame: pd.DataFrame, now: datetime, backfill: int = RECENT_DAYS) -> int:
    """새 날짜만 덧붙인다. 파일이 없으면 최근 backfill 일을 '역산'으로 채워 시작한다."""
    rows = []
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            have = {r["date"] for r in csv.DictReader(f)}
        todo = frame[[str(d.date()) not in have and str(d.date()) > max(have, default="") for d in frame.index]]
        todo = todo.dropna(subset=["state"])
        source = "자동"
    else:
        todo = frame.dropna(subset=["state"]).iloc[-backfill:]
        source = "역산"
    for d, r in todo.iterrows():
        rows.append({"date": str(d.date()), "qqq_close": f"{r['close']:.4f}", "sma50": f"{r['sma50']:.4f}",
                     "sma200": f"{r['sma200']:.4f}", "rsi2": f"{r['rsi2']:.2f}", "state": r["state"],
                     "weight": int(r["weight"]), "recorded_at": stamp, "source": source})
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_COLS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)
    return len(rows)


def recent_from_history(path: Path, n: int = RECENT_DAYS) -> list:
    """화면의 60일 띠 = history.csv 에 자동으로 쌓인 마지막 n 줄 (그날 기록된 그대로)."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))[-n:]
    return [{"date": r["date"], "close": float(r["qqq_close"]), "rsi2": float(r["rsi2"]),
             "state": r["state"], "weight": int(r["weight"]), "source": r["source"]} for r in rows]


def chart_rows(frame: pd.DataFrame, tqqq: pd.Series, n: int = CHART_DAYS) -> list:
    """차트용 최근 n 거래일. compute() 결과(배당조정 종가·50/200 단순이평·Wilder RSI2·상태)를 그대로 옮긴다."""
    f = frame.dropna(subset=["state"]).iloc[-n:]
    rows = []
    for d, r in f.iterrows():
        t = tqqq.get(d) if tqqq is not None else None
        rows.append({"date": str(d.date()), "qqq": _r(r["close"], 4),
                     "tqqq": None if t is None or pd.isna(t) else round(float(t), 4),
                     "sma50": _r(r["sma50"], 4), "sma200": _r(r["sma200"], 4), "rsi2": _r(r["rsi2"], 4),
                     "state": r["state"], "weight": int(r["weight"])})
    return rows


def write_chart(path: Path, frame: pd.DataFrame, tqqq: pd.Series, as_of: str):
    body = {"as_of": as_of, "rows": chart_rows(frame, tqqq)}
    path.write_text(json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


def write_prices(path: Path, qqq: pd.Series, tqqq: pd.Series):
    """오프라인 검증(교차 검증 60일)용 일봉 사본."""
    df = pd.DataFrame({"qqq": qqq, "tqqq": tqqq})
    df.index.name = "date"
    df.to_csv(path, float_format="%.6f", lineterminator="\n")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    qqq = fetch_daily("QQQ")
    tqqq = fetch_daily("TQQQ", start="2010-01-01")
    qqq_done = qqq.loc[completed_sessions(qqq.index, now)]
    as_of = qqq_done.index[-1].date()
    close_utc = schedule(as_of, as_of)["market_close"].iloc[0].tz_convert("UTC")
    try:
        nq = nq_at_close(close_utc)
    except Exception as e:  # noqa: BLE001
        print("NQ 실패:", e)
        nq = None
    try:
        fx = fetch_fx()
    except Exception as e:  # noqa: BLE001
        print("환율 실패:", e)
        fx = None
    state, frame = build_state(qqq, tqqq, now, nq, fx)
    added = append_history(out / "history.csv", frame, now)
    state["recent"] = recent_from_history(out / "history.csv")
    (out / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    write_prices(out / "prices.csv", qqq_done, tqqq.loc[tqqq.index.isin(qqq_done.index)])
    write_chart(out / "chart.json", frame, tqqq, state["as_of"])
    c = state["confirmed"]
    print(f"기준 {state['as_of']} · {c['state']} {c['weight']}% · RSI2 {c['rsi2']:.2f} · "
          f"history +{added}줄 · NQ {state['nq_prev_settle']} ({state['nq_prev_settle_source']})")


if __name__ == "__main__":
    main()
