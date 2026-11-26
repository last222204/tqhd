"""'이 시작일은 운이 좋았나' — 같은 길이·같은 금액으로 가능한 모든 시작 월을 계산한다."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import Market, pay_mask
from .engine import Params, run

REAL_FROM = "2010-03-01"     # TQQQ 실제 상품 첫 온전한 달 (코랩 검산과 같음)


def start_months(m: Market, length: pd.DateOffset, include_synthetic: bool) -> list[tuple[int, int]]:
    first = pd.Timestamp(REAL_FROM) if not include_synthetic else m.idx[int(np.argmax(m.ready))]
    out = []
    month = pd.Timestamp(first.year, first.month, 1)
    if month < first:
        month += pd.DateOffset(months=1)
    while True:
        a = m.i_on_or_after(month)
        if a >= len(m.idx):
            break
        end = m.idx[a] + length
        if end > m.idx[-1]:
            break
        out.append((a, m.i_on_or_before(end)))
        month += pd.DateOffset(months=1)
    return out


def scan(m: Market, strategies: list[str], template: Params, length: pd.DateOffset,
         include_synthetic: bool) -> pd.DataFrame:
    pay = pay_mask(m, template.pay_day)
    rows = []
    for a, b in start_months(m, length, include_synthetic):
        for s in strategies:
            p = Params(**{**template.__dict__, "start": m.idx[a], "end": m.idx[b]})
            r = run(m, s, p, pay, (a, b))
            rows.append({"start": m.idx[a], "strategy": s, "multiple": r.multiple})
    return pd.DataFrame(rows)


def scan_detail(m: Market, strategies: list[str], template: Params, length: pd.DateOffset,
                include_synthetic: bool) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """모든 시작 월의 자세한 지표 + 평균 경로(계좌 ÷ 넣은 돈, 시작 후 경과일 기준)."""
    from . import metrics

    pay = pay_mask(m, template.pay_day)
    rows, paths = [], {s: [] for s in strategies}
    for a, b in start_months(m, length, include_synthetic):
        for s in strategies:
            p = Params(**{**template.__dict__, "start": m.idx[a], "end": m.idx[b]})
            r = run(m, s, p, pay, (a, b))
            x = metrics.summary(r)
            rows.append({"start": m.idx[a], "end": m.idx[b], "strategy": s, "multiple": r.multiple,
                         "final_krw": r.final_krw, "invested": r.invested_total, "irr": x["irr"],
                         "low": x["low"], "mdd": x["mdd"], "tax": x["cap_tax"] + x["div_tax"],
                         "fees": x["fees"], "under_share": x["under_share"], "switches": x["switches"],
                         "synthetic": r.synthetic})
            with np.errstate(divide="ignore", invalid="ignore"):
                paths[s].append(metrics.net_values(r) / np.where(r.invested > 0, r.invested, np.nan))
    out = {}
    for s, arrs in paths.items():
        if not arrs:
            continue
        n = min(len(x) for x in arrs)
        mat = np.vstack([x[:n] for x in arrs])
        out[s] = pd.DataFrame({
            "years": np.arange(n) / 252,
            "mean": np.nanmean(mat, axis=0),
            "p10": np.nanpercentile(mat, 10, axis=0),
            "p90": np.nanpercentile(mat, 90, axis=0),
        })
    return pd.DataFrame(rows), out


def average_table(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("strategy")
    return pd.DataFrame({
        "평균 배수": g["multiple"].mean(),
        "중간값": g["multiple"].median(),
        "운 나쁜 10%": g["multiple"].quantile(0.10),
        "운 좋은 10%": g["multiple"].quantile(0.90),
        "최악": g["multiple"].min(),
        "원금손실 확률": g["multiple"].apply(lambda x: float((x < 1).mean())),
        "평균 연환산": g["irr"].mean(),
        "평균 최하방": g["low"].mean(),
        "평균 최대 낙폭": g["mdd"].mean(),
        "평균 원금 아래 기간": g["under_share"].mean(),
        "평균 교체 횟수": g["switches"].mean(),
        "평균 낸 세금": g["tax"].mean(),
        "평균 수수료": g["fees"].mean(),
    })


def stats(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("strategy")["multiple"]
    return pd.DataFrame({
        "평균": g.mean(), "중간값": g.median(), "운 나쁜 10%": g.quantile(0.10),
        "최악": g.min(), "원금손실 확률": g.apply(lambda x: float((x < 1).mean())), "시작 월 수": g.size(),
    })


def luck_text(dist: np.ndarray, mine: float) -> tuple[float, str]:
    pct = float((dist <= mine).mean())
    if pct >= 0.5:
        return pct, f"운 좋은 상위 {max(1, round((1 - pct) * 100))}%"
    return pct, f"운 나쁜 하위 {max(1, round(pct * 100))}%"
