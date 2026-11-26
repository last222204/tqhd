"""피신 기간별 손익: 피신(SGOV)한 덕분에 TQQQ에 그대로 있었을 때보다 얼마나 이득이나 손해였나.

한 번의 피신 = SGOV로 교체한 날 종가에 들어가서, TQQQ로 돌아온 날 종가에 나온 구간.
  피신 효과 = (1 + SGOV 수익률) / (1 + TQQQ 수익률) - 1
    → +면 피신이 이득 (계좌가 그만큼 더 많음), −면 피신이 손해 (그대로 있었으면 더 많았음)

데이터가 없는 옛날 구간:
  TQQQ 상장(2010-02) 전 → QQQ 일간 수익률 × 3 으로 합성 (운용보수·차입비용 미반영)
  SGOV 상장(2020-05) 전 → 0% (현금으로 가정, 이자 미반영)
"""
from __future__ import annotations

import pandas as pd

from .strategy import refuge_periods


def _ret(series: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> float | None:
    """a 종가 → b 종가 수익률. 둘 중 하나라도 없으면 None."""
    if a not in series.index or b not in series.index:
        return None
    return float(series.loc[b] / series.loc[a] - 1.0)


def synthetic_3x(qqq: pd.Series, a: pd.Timestamp, b: pd.Timestamp) -> float:
    """QQQ 일간 수익률 × 3 을 매일 복리로 이은 수익률 (비용 미반영)."""
    r = qqq.loc[a:b].pct_change().dropna()
    return float((1 + 3 * r).prod() - 1.0)


def refuge_table(sf: pd.DataFrame, qqq: pd.Series, tqqq: pd.Series, sgov: pd.Series) -> pd.DataFrame:
    """피신 한 번당 한 줄.

    sf   : signal_frame() 결과 (공식 신호)
    qqq, tqqq, sgov : 배당조정 종가 (adj_close)
    """
    sig = sf.dropna(subset=["signal"])
    idx = sig.index
    rows = []
    for first, last in refuge_periods(sig):
        entry = first                                    # SGOV로 교체한 날 (그날 종가에 들어감)
        pos = idx.get_loc(last)
        ongoing = pos == len(idx) - 1
        exit_ = last if ongoing else idx[pos + 1]        # TQQQ로 돌아온 날 (그날 종가에 나옴)

        q = _ret(qqq, entry, exit_)
        t = _ret(tqqq, entry, exit_)
        t_synth = t is None
        if t_synth:
            t = synthetic_3x(qqq, entry, exit_)
        s = _ret(sgov, entry, exit_)
        s_cash = s is None
        if s_cash:
            s = 0.0

        rows.append({
            "start": entry,
            "end": exit_,
            "days": int(idx.get_loc(exit_) - idx.get_loc(entry)),
            "ongoing": ongoing,
            "qqq": q,
            "tqqq": t,
            "sgov": s,
            "effect": (1 + s) / (1 + t) - 1.0,
            "tqqq_synthetic": t_synth,
            "sgov_cash": s_cash,
        })
    return pd.DataFrame(rows)


def summary(tbl: pd.DataFrame) -> dict:
    """이득·손해 집계. 아직 진행 중인 피신은 판정하지 않고 따로 센다 (시뮬레이터와 같은 규칙)."""
    ongoing = int(tbl["ongoing"].sum()) if "ongoing" in tbl and len(tbl) else 0
    done = tbl[~tbl["ongoing"]] if "ongoing" in tbl and len(tbl) else tbl
    if done.empty:
        return {"n": 0, "wins": 0, "losses": 0, "total": 0.0, "best": None, "worst": None, "ongoing": ongoing}
    e = done["effect"]
    return {
        "n": len(done),
        "wins": int((e > 0).sum()),
        "losses": int((e <= 0).sum()),
        "total": float((1 + e).prod() - 1.0),   # 모든 피신 효과를 이어 곱한 값
        "best": done.loc[e.idxmax()],
        "worst": done.loc[e.idxmin()],
        "ongoing": ongoing,
    }
