"""시뮬레이션용 시장 데이터를 QQQ 거래일 기준으로 한 줄로 맞춘다.

종목별로 날마다
  tr  : 총수익률 (배당 포함, 배당조정 종가 기준)
  pr  : 가격수익률 (배당 미포함)
  div : 그날 배당 수익률 (= (1+tr)/(1+pr) − 1, 배당락일에만 0이 아님)
  syn : 가상 데이터인 날인가

가상 레버리지 (실제 상품 상장 전):  하루 = L × QQQ 총수익률 − (L−1) × 단기금리 − 연 0.95%
피난처: SGOV (2020-06-01~) → BIL (2007-05-30~) → 단기금리 현금 (그 이전)
환율: Yahoo KRW=X (2003-12~) → FRED DEXKOUS (그 이전)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import store
from ..config import FRED_FX, FX_SYMBOL, SIGNAL_SYMBOL, SMA_FAST, SMA_SLOW

LEV_FEE = 0.0095            # 레버리지 ETF 연 운용보수
IRX_FILL = 4.5              # 단기금리가 비어 있는 날 (코랩과 같게)
SGOV_FROM = pd.Timestamp("2020-06-01")
RISKY = {"QQQ": 1, "QLD": 2, "TQQQ": 3}
REFUGE = "REF"              # 피난처 (SGOV / BIL / 현금)


@dataclass
class Asset:
    tr: np.ndarray
    pr: np.ndarray
    div: np.ndarray
    syn: np.ndarray          # bool
    cash: np.ndarray         # bool, 현금(단기금리)인 날 — 양도차익 없음
    label: np.ndarray        # 날마다 실제 종목 이름 (피난처: SGOV/BIL/현금)


@dataclass
class Market:
    idx: pd.DatetimeIndex
    assets: dict[str, Asset]
    fx: np.ndarray           # 원/달러
    rf: np.ndarray           # 일간 단기금리
    sig_on: np.ndarray       # 그날 종가 판정: True=TQQQ(위험), False=피난처. 준비 전(200일 미만)은 True
    ready: np.ndarray        # 200일선 계산 가능
    qqq_adj: pd.Series
    sma_fast: pd.Series
    sma_slow: pd.Series
    year: np.ndarray = field(init=False)
    month: np.ndarray = field(init=False)
    pos: dict = field(init=False)

    def __post_init__(self):
        self.year = self.idx.year.to_numpy()
        self.month = self.idx.month.to_numpy()
        self.pos = {d: i for i, d in enumerate(self.idx)}

    def i_on_or_after(self, d) -> int:
        return int(self.idx.searchsorted(pd.Timestamp(d), side="left"))

    def i_on_or_before(self, d) -> int:
        return int(self.idx.searchsorted(pd.Timestamp(d), side="right")) - 1


def _ret(s: pd.Series) -> np.ndarray:
    return s.pct_change().fillna(0.0).to_numpy()


def _real(sym: str, idx: pd.DatetimeIndex):
    """실제 종목: 상장일 이후만 (그 전은 NaN)."""
    p = store.load_prices(sym)
    if p.empty:
        return None, None, None
    first = p.index[0]
    adj = p["adj_close"].reindex(idx).ffill()
    raw = p["close"].reindex(idx).ffill()
    return adj, raw, first


def build() -> Market:
    q = store.load_prices(SIGNAL_SYMBOL)
    idx = q.index
    qadj = q["adj_close"]
    q_tr = _ret(qadj)
    q_pr = _ret(q["close"])

    irx = store.load_prices("^IRX")["close"].reindex(idx).ffill().fillna(IRX_FILL)
    rf = (irx / 100 / 252).to_numpy()

    n = len(idx)
    assets: dict[str, Asset] = {}
    for sym, lev in RISKY.items():
        if sym == "QQQ":
            tr, pr, syn = q_tr, q_pr, np.zeros(n, bool)
        else:
            adj, raw, first = _real(sym, idx)
            syn_tr = lev * q_tr - (lev - 1) * rf - LEV_FEE / 252
            if adj is None:
                tr, pr, syn = syn_tr, syn_tr, np.ones(n, bool)
            else:
                syn = np.asarray(idx < first)
                # 상장 첫날 수익률은 전날 실제 값이 없으므로 그날까지 가상, 다음 날부터 실제
                use_syn = np.asarray(idx <= first)
                tr = np.where(use_syn, syn_tr, _ret(adj))
                pr = np.where(use_syn, syn_tr, _ret(raw))
        div = np.where(np.abs((1 + tr) / (1 + pr) - 1) > 1e-5, (1 + tr) / (1 + pr) - 1, 0.0)
        assets[sym] = Asset(tr, pr, div, syn.astype(bool), np.zeros(n, bool), np.full(n, sym, object))

    # 피난처
    sg_adj, sg_raw, sg_first = _real("SGOV", idx)
    bil_adj, bil_raw, bil_first = _real("BIL", idx)
    tr = rf.copy()
    pr = np.zeros(n)
    label = np.full(n, "현금", object)
    cash = np.ones(n, bool)
    if bil_adj is not None:
        m = (idx > bil_first)
        tr = np.where(m, _ret(bil_adj), tr)
        pr = np.where(m, _ret(bil_raw), pr)
        label = np.where(idx >= bil_first, "BIL", label)
        cash = np.where(idx > bil_first, False, cash)
    if sg_adj is not None:
        m = (idx >= SGOV_FROM) & (idx > sg_first)
        tr = np.where(m, _ret(sg_adj), tr)
        pr = np.where(m, _ret(sg_raw), pr)
        label = np.where((idx >= SGOV_FROM) & (idx >= sg_first), "SGOV", label)
    div = np.where(cash, tr, np.where(np.abs((1 + tr) / (1 + pr) - 1) > 1e-5, (1 + tr) / (1 + pr) - 1, 0.0))
    pr = np.where(cash, 0.0, pr)
    assets[REFUGE] = Asset(tr, pr, div, np.zeros(n, bool), cash.astype(bool), label)

    # 환율
    fx = store.load_prices(FX_SYMBOL)["close"]
    fred = store.load_prices(FRED_FX)["close"]
    fxs = fx.reindex(idx).ffill()
    if not fred.empty:
        fxs = fxs.fillna(fred.reindex(idx).ffill())
    fxs = fxs.bfill().ffill()

    # 신호 (QQQ 배당조정 종가, 단순이동평균)
    s50 = qadj.rolling(SMA_FAST).mean()
    s200 = qadj.rolling(SMA_SLOW).mean()
    ready = s200.notna().to_numpy()
    off = ((qadj < s50) & (qadj < s200)).to_numpy() & ready

    return Market(idx, assets, fxs.to_numpy(float), rf, ~off, ready, qadj, s50, s200)


def pay_mask(m: Market, day: int) -> np.ndarray:
    """매월 day일 이상인 첫 거래일 = True."""
    out = np.zeros(len(m.idx), bool)
    s = pd.Series(np.arange(len(m.idx)), index=m.idx)
    for _, g in s.groupby([m.idx.year, m.idx.month]):
        ok = g[g.index.day >= day]
        if len(ok):
            out[ok.iloc[0]] = True
    return out
