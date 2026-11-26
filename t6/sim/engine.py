"""계좌 시뮬레이션 엔진 (그림자 계좌도 이 엔진을 쓴다).

두 가지 모드
  현실 모드 (기본)   — 날마다 마감 시점에: 그날 수익 → 배당(15.4% 떼고 재투자) → 새해면 전년 세금 확정
                        → 5월 마지막 거래일 세금 납부(보유분 일부 매도, 그 차익도 과세) → 교체 → 적립
                        환율 반영(원화 → 그날 환율로 달러), 양도차익은 원화 기준(환차익 포함), 이동평균 취득가
  검산 모드 (코랩)   — 사용자의 코랩 run() 과 한 줄씩 같은 순서·같은 단순화 (환율 고정, 피난처 수익 × (1−0.154),
                        세금은 5월 첫 거래일에 평가액에서 차감, 납부용 매도 수수료·차익 없음, 마지막 매도 0.2%)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from .data import REFUGE, Market, pay_mask

UMBRELLA = "UMBRELLA"
STRATEGY_NAMES = {UMBRELLA: "☂️ 나스닥 우산", "TQQQ": "TQQQ 그냥 적립", "QLD": "QLD 그냥 적립",
                  "QQQ": "QQQ 그냥 적립"}


@dataclass
class Costs:
    switch: float = 0.003      # 교체: 매도·매수 각각 (편도)
    buy: float = 0.002         # 처음 돈·적립 매수
    tax_sale: float = 0.003    # 세금 납부용 매도 (현실 모드)
    final: float = 0.003       # 마지막 날 전량 매도 (검산 모드는 0.002 고정)


@dataclass
class Taxes:
    cap_rate: float = 0.22
    deduction: float = 2_500_000
    div_rate: float = 0.154


@dataclass
class Params:
    start: date
    end: date
    initial_krw: float = 10_000_000
    monthly_krw: float = 1_000_000
    pay_day: int = 17
    fx_mode: str = "real"          # 'real' 그날 환율 / 'fixed' 시작일 환율 고정 (= 달러 기준)
    liquidate: bool = True         # 마지막 날 전부 매도 후 세금 정산 / False = 보유 유지(세전 평가)
    colab: bool = False            # 검산 모드
    costs: Costs = field(default_factory=Costs)
    taxes: Taxes = field(default_factory=Taxes)


@dataclass
class Result:
    strategy: str
    dates: pd.DatetimeIndex
    value_krw: np.ndarray          # 그날 마감 후 평가액 (원)
    invested: np.ndarray           # 누적 넣은 돈 (원)
    flow: np.ndarray               # 그날 넣은 돈 (원, 처음 돈 포함)
    on: np.ndarray                 # 그날 마감 후 위험자산 보유 여부
    fx: np.ndarray                 # 계산에 쓴 환율
    trades: list = field(default_factory=list)
    tax_by_year: dict = field(default_factory=dict)   # 그해에 낸 양도세 (원)
    div_tax: float = 0.0
    div_tax_by_year: dict = field(default_factory=dict)
    fees: float = 0.0
    final_krw: float = 0.0         # 마지막 날 (세후 또는 세전 평가)
    final_usd: float = 0.0
    synthetic: bool = False
    exit_krw: np.ndarray | None = None   # 그날 마감 뒤 전부 팔았다면 세후 받는 돈 (청산 시나리오용)

    @property
    def invested_total(self) -> float:
        return float(self.invested[-1])

    @property
    def multiple(self) -> float:
        return self.final_krw / self.invested_total if self.invested_total else float("nan")

    @property
    def cap_tax(self) -> float:
        return float(sum(self.tax_by_year.values()))


def window(m: Market, start, end) -> tuple[int, int]:
    """시작일 이후 첫 거래일 ~ 종료일 이전 마지막 거래일."""
    a = m.i_on_or_after(start)
    b = m.i_on_or_before(end)
    if a >= len(m.idx) or b <= a:
        raise ValueError("기간 안에 거래일이 없습니다")
    if not m.ready[a]:
        raise ValueError("시작일이 너무 이릅니다 (200일선을 계산할 데이터가 없음)")
    return a, b


def run(m: Market, strategy: str, p: Params, pay: np.ndarray | None = None,
        ab: tuple[int, int] | None = None) -> Result:
    a, b = ab or window(m, p.start, p.end)
    pay = pay if pay is not None else pay_mask(m, p.pay_day)
    if p.colab:
        return _run_colab(m, strategy, a, b, p, pay)
    return _run_real(m, strategy, a, b, p, pay)


def _uses_synthetic(m: Market, strategy: str, a: int, b: int) -> bool:
    sym = "TQQQ" if strategy == UMBRELLA else strategy
    return bool(m.assets[sym].syn[a:b + 1].any())


def _may_tax_days(m: Market, last_in_may: bool) -> dict[int, int]:
    """연도 → 세금 납부일 인덱스 (5월 첫 거래일 또는 마지막 거래일). 시장마다 한 번만 계산."""
    cache = m.__dict__.setdefault("_may_cache", {})
    if last_in_may in cache:
        return cache[last_in_may]
    out = {}
    s = pd.Series(np.arange(len(m.idx)), index=m.idx)
    may = s[m.idx.month == 5]
    for y, g in may.groupby(may.index.year):
        out[int(y)] = int(g.iloc[-1] if last_in_may else g.iloc[0])
    cache[last_in_may] = out
    return out


# ── 현실 모드 ────────────────────────────────────
def _run_real(m: Market, strategy: str, a: int, b: int, p: Params, pay: np.ndarray) -> Result:
    c, t = p.costs, p.taxes
    plain = strategy != UMBRELLA
    R = m.assets["TQQQ" if not plain else strategy]
    F = m.assets[REFUGE]
    fx = m.fx[a:b + 1].copy() if p.fx_mode == "real" else np.full(b - a + 1, m.fx[a])
    tax_day = _may_tax_days(m, last_in_may=True)
    n = b - a + 1
    sl = slice(a, b + 1)
    # 빠르게: 넘파이 원소를 하루씩 읽으면 느려서 파이썬 리스트로 바꿔 둔다 (계산 내용은 같음)
    YR = m.year[sl].tolist(); PAY = pay[sl].tolist(); FX = fx.tolist()
    SIG = [True] * n if plain else m.sig_on[sl].tolist()
    Rpr, Rdiv = R.pr[sl].tolist(), R.div[sl].tolist()
    Fpr, Fdiv, Fcash = F.pr[sl].tolist(), F.div[sl].tolist(), F.cash[sl].tolist()
    taxk = {y: i - a for y, i in tax_day.items() if a <= i <= b}
    val, inv_l, flow_l, on_l, ex = [0.0] * n, [0.0] * n, [0.0] * n, [False] * n, [0.0] * n
    trades, tax_by_year, dty = [], {}, {}
    sw_c, buy_c, ts_c, fin_c = c.switch, c.buy, c.tax_sale, c.final
    dr, ded, rate, mon = t.div_rate, t.deduction, t.cap_rate, p.monthly_krw

    on = SIG[0]
    V = p.initial_krw / FX[0] * (1 - buy_c)    # 달러 평가액
    B = p.initial_krw                          # 원화 취득가 (수수료 포함)
    fees = p.initial_krw * buy_c
    inv = p.initial_krw
    div_tax = 0.0
    realized, yr, due = 0.0, YR[0], 0.0
    flow_l[0] = p.initial_krw
    if p.initial_krw:
        trades.append({"date": m.idx[a], "kind": "처음 매수", "to": _label(R, F, on, a, strategy),
                       "krw": p.initial_krw, "fee": fees, "realized": 0.0})

    for k in range(n):
        f = FX[k]
        if k:
            if on:
                V *= 1 + Rpr[k]; d = Rdiv[k]
            else:
                V *= 1 + Fpr[k]; d = Fdiv[k]
            if d and V > 0:
                g = V * d
                net = g * (1 - dr)
                V += net
                B += net * f
                div_tax += g * dr * f
                dty[YR[k]] = dty.get(YR[k], 0.0) + g * dr * f
            if YR[k] != yr:                        # 새해 첫 거래일: 전년 세금 확정
                due = max(realized - ded, 0.0) * rate
                realized, yr = 0.0, YR[k]
            if due and taxk.get(yr) == k and V > 0:   # 5월 마지막 거래일 납부
                gross = min(due / f / (1 - ts_c), V)
                frac = gross / V
                gain = 0.0 if (not on and Fcash[k]) else gross * (1 - ts_c) * f - B * frac
                realized += gain
                fees += gross * ts_c * f
                B *= 1 - frac
                V -= gross
                tax_by_year[yr] = tax_by_year.get(yr, 0.0) + due
                trades.append({"date": m.idx[a + k], "kind": "세금 납부용 매도", "to": "",
                               "krw": gross * f, "fee": gross * ts_c * f, "realized": gain, "tax": due})
                due = 0.0
            now = SIG[k]
            if now != on:                          # 교체 (그날 종가)
                proceeds = V * (1 - sw_c)
                gain = 0.0 if (not on and Fcash[k]) else proceeds * f - B
                realized += gain
                fee = V * sw_c * f + proceeds * sw_c * f
                fees += fee
                V = proceeds * (1 - sw_c)
                B = proceeds * f
                on = now
                trades.append({"date": m.idx[a + k], "kind": "교체", "to": _label(R, F, on, a + k, strategy),
                               "krw": proceeds * f, "fee": fee, "realized": gain})
            if PAY[k] and mon:                     # 적립 (그날 종가, 그날 보유 쪽 = 교체 후)
                V += mon / f * (1 - buy_c)
                B += mon
                fees += mon * buy_c
                inv += mon
                flow_l[k] = mon
        val[k] = V * f
        inv_l[k] = inv
        on_l[k] = on
        pr_ = V * (1 - fin_c)
        g_ = 0.0 if (not on and Fcash[k]) else pr_ * f - B
        ex[k] = pr_ * f - (max(realized + g_ - ded, 0.0) * rate + due)

    # 마지막 날
    f = FX[-1]
    if p.liquidate:
        proceeds = V * (1 - fin_c)
        gain = 0.0 if (not on and Fcash[-1]) else proceeds * f - B
        realized += gain
        fees += V * fin_c * f
        tax_now = max(realized - ded, 0.0) * rate + due
        tax_by_year[YR[-1]] = tax_by_year.get(YR[-1], 0.0) + tax_now
        final_krw = proceeds * f - tax_now
        trades.append({"date": m.idx[b], "kind": "마지막 전량 매도", "to": "", "krw": proceeds * f,
                       "fee": V * fin_c * f, "realized": gain, "tax": tax_now})
    else:
        final_krw = V * f
    return Result(strategy, m.idx[a:b + 1], np.array(val), np.array(inv_l), np.array(flow_l), np.array(on_l),
                  fx, trades, tax_by_year, div_tax, dty, fees, final_krw, final_krw / f,
                  _uses_synthetic(m, strategy, a, b), np.array(ex))


def _label(R, F, on, i, strategy):
    if on:
        return str(R.label[i])
    return str(F.label[i])


# ── 검산 모드 (코랩 run() 그대로) ─────────────────
def _run_colab(m: Market, strategy: str, a: int, b: int, p: Params, pay: np.ndarray) -> Result:
    TAX, DEDUCT, DIV_TAX = p.taxes.cap_rate, p.taxes.deduction, p.taxes.div_rate
    BUY_COST, AH_COST = 0.002, 0.003
    SEED, MONTHLY = p.initial_krw, p.monthly_krw
    plain = strategy != UMBRELLA
    R3 = m.assets["TQQQ" if not plain else strategy].tr
    RF = m.assets[REFUGE].tr
    # H[i] = 그날 보유 상태 = 전날 종가 판정 (코랩: ~raw_off 를 하루 밀고 첫날 True)
    n = b - a + 1
    sl = slice(a, b + 1)
    YEAR, MONTH = m.year[sl].tolist(), m.month[sl].tolist()
    R3l, RFl, PAY = R3[sl].tolist(), RF[sl].tolist(), pay[sl].tolist()
    if plain:
        HH = [True] * n
        SIGc = [True] * n
    else:
        HH = m.sig_on[a - 1:b].tolist() if a > 0 else [True] + m.sig_on[a:b].tolist()
        SIGc = m.sig_on[sl].tolist()
    val, inv_l, flow_l, on_l, ex = [0.0] * n, [0.0] * n, [0.0] * n, [False] * n, [0.0] * n
    trades, tax_by_year, dty = [], {}, {}
    fees, div_tax, ds_year = 0.0, 0.0, 0.0

    on = HH[0]
    L, S = (SEED * (1 - BUY_COST), 0.0) if on else (0.0, float(SEED))
    fees += SEED * BUY_COST if on else 0.0
    bL = SEED if on else 0.0
    inv, realized, due, prev, yr = SEED, 0.0, 0.0, on, YEAR[0]
    flow_l[0] = SEED
    for k in range(n):
        if YEAR[k] != yr:
            dty[yr] = dty.get(yr, 0.0) + ds_year; ds_year = 0.0
            due = max(realized - DEDUCT, 0) * TAX; realized = 0.0; yr = YEAR[k]
        if due and MONTH[k] >= 5:
            if S >= due:
                S -= due
            else:
                rest = due - S; S = 0.0; bL *= (1 - rest / L) if L > 0 else 1; L -= rest
            tax_by_year[yr] = tax_by_year.get(yr, 0.0) + due
            trades.append({"date": m.idx[a + k], "kind": "세금 납부", "to": "", "krw": due, "fee": 0.0,
                           "realized": 0.0, "tax": due})
            due = 0.0
        now = HH[k]
        if now != prev:
            if not now:
                pr = L * (1 - AH_COST); g = pr - bL; realized += g
                fees += L * AH_COST + pr * AH_COST
                S += pr * (1 - AH_COST); L = 0.0; bL = 0.0
            else:
                pr = S * (1 - AH_COST); g = 0.0
                fees += S * AH_COST + pr * AH_COST
                L += pr * (1 - AH_COST); bL += pr; S = 0.0
            prev = now
            # 코랩은 '다음 날 아침'에 교체하지만 수익률 계산상 전날 종가 체결과 같다
            trades.append({"date": m.idx[a + k - 1], "kind": "교체",
                           "to": "TQQQ" if now else str(m.assets[REFUGE].label[a + k]),
                           "krw": pr, "fee": 0.0, "realized": g})
        L *= 1 + R3l[k]
        if S:
            ds = S * RFl[k] * DIV_TAX
            div_tax += ds
            ds_year += ds
            S *= 1 + RFl[k] * (1 - DIV_TAX)
        if PAY[k] and k:
            inv += MONTHLY
            flow_l[k] = MONTHLY
            if not now:
                S += MONTHLY
            else:
                L += MONTHLY * (1 - BUY_COST); bL += MONTHLY; fees += MONTHLY * BUY_COST
        val[k] = L + S
        inv_l[k] = inv
        g_ = realized + (L * (1 - BUY_COST) - bL)
        ex[k] = L * (1 - BUY_COST) + S - max(g_ - DEDUCT, 0) * TAX - due
        on_l[k] = SIGc[k]
    dty[yr] = dty.get(yr, 0.0) + ds_year
    gain = realized + (L * (1 - BUY_COST) - bL)
    tax_now = max(gain - DEDUCT, 0) * TAX + due
    tax_by_year[YEAR[-1]] = tax_by_year.get(YEAR[-1], 0.0) + tax_now
    fees += L * BUY_COST
    final = L * (1 - BUY_COST) + S - tax_now
    fx_fixed = float(m.fx[a])
    return Result(strategy, m.idx[a:b + 1], np.array(val), np.array(inv_l), np.array(flow_l), np.array(on_l),
                  np.full(n, fx_fixed), trades, tax_by_year, div_tax, dty, fees, final, final / fx_fixed,
                  _uses_synthetic(m, strategy, a, b), np.array(ex))
