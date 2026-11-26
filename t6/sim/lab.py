"""무작위 청산 시뮬레이션: 시작일과 보유 기간을 무작위로 뽑아, 모든 전략을 같은 시작일·같은 청산일로 계산."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import exits
from .data import Market, pay_mask
from .engine import Params, run
from .metrics import xirr
from .scan import REAL_FROM


@dataclass(frozen=True)
class Draws:
    a: np.ndarray            # 시작 인덱스
    e: np.ndarray            # 청산 인덱스
    years: np.ndarray        # 뽑은 보유 기간 (년)
    rejected: int            # 청산일이 데이터 끝을 넘어서 다시 뽑은 횟수


def first_start(m: Market, include_synthetic: bool) -> int:
    if include_synthetic:
        return int(np.argmax(m.ready))
    return m.i_on_or_after(REAL_FROM)


def draw(m: Market, n: int, seed: int, min_years: float, max_years: float, include_synthetic: bool,
         start_from=None, start_to=None) -> Draws:
    """같은 시드면 같은 결과. 청산일이 데이터 끝을 넘으면 그 표본은 버리고 다시 뽑는다."""
    rng = np.random.default_rng(seed)
    lo = first_start(m, include_synthetic)
    if start_from is not None:
        lo = max(lo, m.i_on_or_after(start_from))
    hi = len(m.idx) - 1 if start_to is None else m.i_on_or_before(start_to)
    if hi <= lo:
        raise ValueError("시작일 범위에 거래일이 없습니다")
    last = m.idx[-1]
    A, E, Y = [], [], []
    rejected = 0
    tries = 0
    while len(A) < n:
        k = max(256, 2 * (n - len(A)))
        a = rng.integers(lo, hi + 1, k)
        y = rng.uniform(min_years, max_years, k)
        end = m.idx[a] + pd.to_timedelta(np.round(y * 365.25), unit="D")
        ok = np.asarray(end <= last)
        rejected += int((~ok).sum())
        for ai, yi, en in zip(a[ok], y[ok], end[ok]):
            if len(A) >= n:
                break
            A.append(int(ai)); Y.append(float(yi)); E.append(m.i_on_or_before(en))
        tries += 1
        if tries > 200:
            raise ValueError("조건에 맞는 시작일·보유 기간을 뽑을 수 없습니다 (보유 기간을 줄여 보세요)")
    return Draws(np.array(A), np.array(E), np.array(Y), rejected)


def simulate(m: Market, strategies: list[str], p: Params, d: Draws, th: exits.Thresholds,
             progress=None) -> pd.DataFrame:
    """시작일마다 전략별로 엔진을 한 번만 돌리고, 청산일 값은 '그날 팔았다면 세후' 칸에서 꺼낸다."""
    ms = exits.market_state(m)
    cls = exits.classify(ms["dd"].to_numpy(), ms["above200"].to_numpy(), th)
    dd = ms["dd"].to_numpy()
    pay = pay_mask(m, p.pay_day)
    p = Params(**{**p.__dict__, "liquidate": True})
    order = pd.DataFrame({"draw": np.arange(len(d.a)), "a": d.a, "e": d.e, "years": d.years})
    groups = order.groupby("a")
    rows = []
    total = len(groups)
    for gi, (a, g) in enumerate(groups):
        emax = int(g["e"].max())
        for s in strategies:
            r = run(m, s, Params(**{**p.__dict__, "start": m.idx[a], "end": m.idx[emax]}), pay, (a, emax))
            for row in g.itertuples():
                k = row.e - a
                inv = r.invested[k]
                fin = r.exit_krw[k]
                flows = -r.flow[: k + 1].copy()
                flows[-1] += fin
                rows.append((row.draw, s, fin / inv, xirr(r.dates[: k + 1], flows),
                             float(np.min(r.value_krw[: k + 1] / r.invested[: k + 1])), r.synthetic))
        if progress is not None and (gi % 25 == 0 or gi == total - 1):
            progress((gi + 1) / total)
    res = pd.DataFrame(rows, columns=["draw", "strategy", "multiple", "irr", "low", "synthetic"])
    order["start"] = m.idx[order["a"]]
    order["exit"] = m.idx[order["e"]]
    order["cls"] = cls[order["e"]]
    order["dd"] = dd[order["e"]]
    return res.merge(order, on="draw")


def class_table(df: pd.DataFrame, strategies: list[str]) -> pd.DataFrame:
    """청산 분류 × 전략 표. 마지막에 '전체'."""
    out = []
    n_all = df["draw"].nunique()
    for c in (exits.GREEN, exits.RED, exits.GRAY, "all"):
        sub = df if c == "all" else df[df["cls"] == c]
        n = sub["draw"].nunique()
        if n == 0:
            continue
        stats = []
        for s in strategies:
            x = sub[sub["strategy"] == s]
            stats.append({"cls": c, "n": n, "share": n / n_all, "strategy": s,
                          "mean": x["multiple"].mean(), "median": x["multiple"].median(),
                          "p10": x["multiple"].quantile(0.10), "min": x["multiple"].min(),
                          "irr_mean": x["irr"].mean(), "loss": float((x["multiple"] < 1).mean())})
        t = pd.DataFrame(stats)
        t["rank_mean"] = t["mean"].rank(ascending=False, method="min").astype(int)
        t["rank_min"] = t["min"].rank(ascending=False, method="min").astype(int)
        out.append(t)
    return pd.concat(out, ignore_index=True)


def head_to_head(df: pd.DataFrame, a: str, b: str, cls: str | None) -> float:
    """cls 청산에서 전략 a 가 전략 b 보다 나았던 비율."""
    w = df.pivot(index="draw", columns="strategy", values="multiple")
    if cls is not None:
        draws = df[df["cls"] == cls]["draw"].unique()
        w = w.loc[w.index.isin(draws)]
    if w.empty:
        return float("nan")
    return float((w[a] > w[b]).mean())
