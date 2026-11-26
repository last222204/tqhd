"""시뮬레이션 결과에서 지표·표를 만든다."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import REFUGE, Market
from .engine import Result

WHIPSAW_DAYS = 10


# ── 수익률 ───────────────────────────────────────
def xirr(dates: pd.DatetimeIndex, flows: np.ndarray) -> float:
    """연환산 내부수익률. flows: 넣은 돈은 음수, 마지막 회수는 양수."""
    flows = np.asarray(flows, float)
    nz = flows != 0                       # 돈이 오간 날만 (적립일·처음·마지막)
    t = np.asarray((dates - dates[0]).days, float)[nz] / 365.25
    flows = flows[nz]
    if not (flows < 0).any() or not (flows > 0).any():
        return float("nan")

    def npv(r):
        return float(np.dot(flows, (1 + r) ** -t))

    lo, hi = -0.99, 10.0
    f_lo = npv(lo)
    if f_lo * npv(hi) > 0:
        return float("nan")
    for _ in range(60):                   # 2^-60 × 11 → 충분히 정확
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if f_lo * f_mid <= 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def net_values(r: Result) -> np.ndarray:
    """평가액, 단 마지막 날은 세후 최종 금액 (매도 비용·세금 반영)."""
    v = r.value_krw.copy()
    v[-1] = r.final_krw
    return v


def twr(r: Result) -> pd.Series:
    """적립금 효과를 뺀 시간가중 일간 수익률."""
    v = net_values(r)
    prev = np.r_[np.nan, v[:-1]]
    with np.errstate(divide="ignore", invalid="ignore"):
        ret = (v - r.flow) / prev - 1
    ret[0] = 0.0
    ret = np.where(np.isfinite(ret), ret, 0.0)
    return pd.Series(ret, index=r.dates)


def summary(r: Result) -> dict:
    v = net_values(r)
    inv = r.invested
    flows = -r.flow.copy()
    flows[-1] += r.final_krw
    irr = xirr(r.dates, flows)

    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(inv > 0, v / inv, np.nan)
    low_i = int(np.nanargmin(ratio)) if np.isfinite(ratio).any() else 0

    idx = (1 + twr(r)).cumprod()
    peak = idx.cummax()
    dd = idx / peak - 1
    t_i = int(dd.values.argmin())
    p_i = int(idx.values[: t_i + 1].argmax())
    rec = np.where(idx.values[t_i:] >= idx.values[p_i])[0]
    rec_date = r.dates[t_i + rec[0]] if len(rec) else None

    under = ratio < 1
    longest, cur, best_end = 0, 0, None
    for i, u in enumerate(under):
        cur = cur + 1 if u else 0
        if cur > longest:
            longest, best_end = cur, i
    lstart = r.dates[best_end - longest + 1] if longest else None
    lend = r.dates[best_end] if longest else None

    return {
        "invested": r.invested_total,
        "final_krw": r.final_krw,
        "final_usd": r.final_usd,
        "multiple": r.multiple,
        "irr": irr,
        "low": float(ratio[low_i]) if np.isfinite(ratio).any() else float("nan"),
        "low_date": r.dates[low_i],
        "mdd": float(dd.values[t_i]),
        "mdd_peak": r.dates[p_i],
        "mdd_trough": r.dates[t_i],
        "mdd_recover": rec_date,
        "under_share": float(np.nanmean(under)) if len(under) else 0.0,
        "under_longest": longest,
        "under_start": lstart,
        "under_end": lend,
        "cap_tax": r.cap_tax,
        "div_tax": r.div_tax,
        "fees": r.fees,
        "switches": sum(1 for t in r.trades if t["kind"] == "교체"),
    }


def yearly(r: Result) -> pd.DataFrame:
    v = net_values(r)
    ret = twr(r)
    years = r.dates.year
    rows = []
    prev_end = None
    for y in sorted(set(years)):
        mask = years == y
        ii = np.where(mask)[0]
        start_val = prev_end if prev_end is not None else r.flow[0]
        end_val = v[ii[-1]]
        put = r.flow[mask].sum() - (r.flow[0] if ii[0] == 0 else 0)
        sw = sum(1 for t in r.trades if t["kind"] == "교체" and t["date"].year == y)
        rows.append({
            "연도": int(y),
            "연초 평가액": start_val,
            "넣은 돈": put,
            "연말 평가액": end_val,
            "수익률": float((1 + ret[mask]).prod() - 1),
            "교체": sw,
            "피신한 날": float((~r.on[mask]).mean()),
            "낸 세금": r.tax_by_year.get(int(y), 0.0) + r.div_tax_by_year.get(int(y), 0.0),
        })
        prev_end = end_val
    return pd.DataFrame(rows)


# ── 피신 기록 (보험금 / 보험료) ───────────────────
def refuge_records(m: Market, a: int, b: int) -> pd.DataFrame:
    """기간 안의 피신 한 번당 한 줄. 진입=SGOV로 바꾼 날 종가, 복귀=TQQQ로 돌아온 날 종가."""
    on = m.sig_on
    T, F, Q = m.assets["TQQQ"].tr, m.assets[REFUGE].tr, m.assets["QQQ"].tr
    rows = []
    i = a
    while i <= b:
        if on[i]:
            i += 1
            continue
        s = i
        while i <= b and not on[i]:
            i += 1
        ongoing = i > b
        e = b if ongoing else i
        sl = slice(s + 1, e + 1)
        t = float(np.prod(1 + T[sl]) - 1)
        f = float(np.prod(1 + F[sl]) - 1)
        q = float(np.prod(1 + Q[sl]) - 1)
        eff = (1 + f) / (1 + t) - 1
        rows.append({
            "start": m.idx[s], "end": m.idx[e], "days": e - s, "ongoing": ongoing,
            "from_start": s == a and a > 0 and not on[a - 1],
            "tqqq": t, "refuge": f, "qqq": q, "effect": eff,
            "verdict": "진행 중" if ongoing else ("보험금" if eff > 0 else "보험료"),
            "synthetic": bool(m.assets["TQQQ"].syn[s:e + 1].any()),
        })
        i = e + 1 if ongoing else e
    return pd.DataFrame(rows)


def refuge_summary(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"n": 0}
    ongoing = t[t["ongoing"]]
    t = t[~t["ongoing"]]                 # 진행 중인 피신은 아직 판정하지 않는다
    if t.empty:
        return {"n": 0, "gain_n": 0, "gain_total": 0.0, "gain_median_days": None, "pay_n": 0, "pay_total": 0.0,
                "pay_median_days": None, "total": 0.0, "total_without_best": 0.0, "best": None,
                "ongoing_n": len(ongoing)}
    g, p = t[t["effect"] > 0], t[t["effect"] <= 0]
    comp = lambda x: float((1 + x["effect"]).prod() - 1) if len(x) else 0.0
    total = comp(t)
    ex = t.drop(index=g["effect"].idxmax()) if len(g) else t
    return {
        "n": len(t),
        "gain_n": len(g), "gain_total": comp(g), "gain_median_days": float(g["days"].median()) if len(g) else None,
        "pay_n": len(p), "pay_total": comp(p), "pay_median_days": float(p["days"].median()) if len(p) else None,
        "total": total,
        "total_without_best": comp(ex),
        "best": g.loc[g["effect"].idxmax()] if len(g) else None,
        "ongoing_n": len(ongoing),
    }


# ── 보유 구간 · 헛걸음 ────────────────────────────
def holding_segments(m: Market, a: int, b: int) -> pd.DataFrame:
    """☀️ TQQQ 보유 구간: 시작(진입일 종가) ~ 끝(피신으로 바꾼 날 종가)."""
    on = m.sig_on
    T = m.assets["TQQQ"].tr
    rows = []
    i = a
    while i <= b:
        if not on[i]:
            i += 1
            continue
        s = i
        while i <= b and on[i]:
            i += 1
        ongoing = i > b
        e = b if ongoing else i
        rows.append({"start": m.idx[s], "end": m.idx[e], "days": e - s, "ongoing": ongoing,
                     "ret": float(np.prod(1 + T[s + 1:e + 1]) - 1)})
        i = e + 1 if ongoing else e
    return pd.DataFrame(rows)


def whipsaws(m: Market, a: int, b: int, days: int = WHIPSAW_DAYS) -> int:
    """교체 후 days 거래일 안에 되돌아간 횟수."""
    on = m.sig_on[a:b + 1]
    sw = np.where(on[1:] != on[:-1])[0] + 1
    return int(sum(1 for x, y in zip(sw[:-1], sw[1:]) if y - x <= days))
