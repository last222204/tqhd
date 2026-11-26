"""청산 시나리오: 언제 파느냐.

청산일 시장 상태 (QQQ 배당조정 종가, 전고점 = 1999년 이후 그날까지 최고 종가)
  🟢 상승장 청산: 전고점 대비 green_dd(−5%) 이내 그리고 200일선 위
  🔴 하락장 청산: 전고점 대비 red_dd(−20%) 이하
  ⚪ 보통 청산  : 나머지

청산 규칙 (엔진의 '그날 팔았다면 세후' 칸으로 계산 — 새 엔진 없음)
  fixed  : 시작 + N년 (그 직전 거래일)
  ath    : 졸업 A — 시작 + N년(t_N, 당일 포함)부터 QQQ 종가 ≥ 그날까지 최고 종가인 첫날. 없으면 M년 강제
  target : 졸업 B — 시작 후 252거래일 지나서, 세전 평가액 ÷ 넣은 돈 ≥ X 인 첫날 (그날 적립 뒤 판정). 없으면 M년 강제
  crash  : 하락장 강제 — t_N 부터 전고점 대비 red_dd 이하에 처음 닿는 날. 없으면 M년
  random : t_N ~ M년 사이 아무 거래일 (시드 고정)
M년이 데이터보다 뒤면 데이터 마지막 날 청산 → '미졸업(데이터 끝)'.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .data import Market, pay_mask
from .engine import Params, Result, run
from .metrics import xirr

GREEN, RED, GRAY = "green", "red", "gray"
CLASS_LABEL = {GREEN: "🟢 상승장 청산", RED: "🔴 하락장 청산", GRAY: "⚪ 보통 청산"}
TARGET_MIN_DAYS = 252          # 졸업 B: 첫 1년(252거래일) 안에는 판정하지 않음

RULE_LABEL = {"fixed": "고정 기간", "ath": "졸업 A: 전고점 졸업", "target": "졸업 B: 목표 배수 졸업",
              "crash": "하락장 강제 청산", "random": "무작위 청산"}
STATUS_LABEL = {"grad": "졸업", "fixed": "고정 기간 만료", "date": "직접 고른 종료일", "cap": "최대 기간 강제 청산",
                "data_end": "미졸업 (데이터 끝)"}


@dataclass(frozen=True)
class Thresholds:
    green_dd: float = -0.05
    red_dd: float = -0.20


@dataclass(frozen=True)
class Rule:
    kind: str = "fixed"
    min_years: float = 5
    max_years: float = 15
    target: float = 2.0
    seed: int = 0


# ── 시장 상태 ────────────────────────────────────
def market_state(m: Market) -> pd.DataFrame:
    q = m.qqq_adj
    ath = q.cummax()
    return pd.DataFrame({"dd": (q / ath - 1).to_numpy(), "above200": (q > m.sma_slow).to_numpy(),
                         "newhigh": (q >= ath).to_numpy()}, index=m.idx)


def classify(dd: np.ndarray, above200: np.ndarray, th: Thresholds = Thresholds()) -> np.ndarray:
    out = np.full(len(dd), GRAY, object)
    out[(dd >= th.green_dd) & above200] = GREEN
    out[dd <= th.red_dd] = RED
    return out


# ── 청산일 찾기 ──────────────────────────────────
def _offset(m: Market, a: int, years: float) -> tuple[int, bool]:
    """시작 + years 년 (그 직전 거래일), 데이터를 넘었는지."""
    whole = int(years)
    date = m.idx[a] + pd.DateOffset(years=whole) + pd.Timedelta(days=round((years - whole) * 365.25))
    return m.i_on_or_before(date), date > m.idx[-1]


def horizon(m: Market, a: int, rule: Rule) -> tuple[int, bool]:
    """이 규칙에서 가장 늦을 수 있는 청산일 (엔진을 여기까지 돌리면 된다)."""
    years = rule.min_years if rule.kind == "fixed" else rule.max_years
    return _offset(m, a, years)


def find_exit(m: Market, a: int, rule: Rule, ms: pd.DataFrame, th: Thresholds,
              res: Result | None = None) -> tuple[int, str]:
    """청산일 인덱스와 상태(grad/fixed/cap/data_end)."""
    cap, over = horizon(m, a, rule)
    end_status = "data_end" if over else ("fixed" if rule.kind == "fixed" else "cap")
    if rule.kind == "fixed":
        return cap, end_status
    tn, _ = _offset(m, a, rule.min_years)
    if rule.kind == "ath":
        hits = np.where(ms["newhigh"].to_numpy()[tn:cap + 1])[0]
        return (tn + int(hits[0]), "grad") if len(hits) else (cap, end_status)
    if rule.kind == "crash":
        hits = np.where(ms["dd"].to_numpy()[tn:cap + 1] <= th.red_dd)[0]
        return (tn + int(hits[0]), "grad") if len(hits) else (cap, end_status)
    if rule.kind == "random":
        rng = np.random.default_rng([rule.seed, a])
        return int(rng.integers(min(tn, cap), cap + 1)), "grad"
    if rule.kind == "target":
        if res is None:
            raise ValueError("목표 배수 졸업은 전략별 계산 결과가 필요합니다")
        ratio = res.value_krw / res.invested
        k0 = TARGET_MIN_DAYS
        hits = np.where(ratio[k0:] >= rule.target)[0]
        return (a + k0 + int(hits[0]), "grad") if len(hits) else (cap, end_status)
    raise ValueError(rule.kind)


# ── 한 시작일 · 한 전략 ──────────────────────────
@dataclass
class ExitOutcome:
    strategy: str
    a: int
    e: int
    status: str
    cls: str
    multiple: float
    irr: float
    years: float
    low: float
    under_share: float
    final_krw: float
    invested: float


def outcome_from(m: Market, res: Result, a: int, e: int, status: str, cls: str) -> ExitOutcome:
    k = e - a
    inv = float(res.invested[k])
    final = float(res.exit_krw[k])
    flows = -res.flow[: k + 1].copy()
    flows[-1] += final
    ratio = res.value_krw[: k + 1] / res.invested[: k + 1]
    return ExitOutcome(res.strategy, a, e, status, cls, final / inv if inv else float("nan"),
                       xirr(res.dates[: k + 1], flows), (m.idx[e] - m.idx[a]).days / 365.25,
                       float(np.nanmin(ratio)), float(np.mean(ratio < 1)), final, inv)


def run_rule(m: Market, strategy: str, p: Params, a: int, rule: Rule, ms: pd.DataFrame, th: Thresholds,
             pay: np.ndarray, cls_arr: np.ndarray) -> tuple[ExitOutcome, Result]:
    cap, _ = horizon(m, a, rule)
    res = run(m, strategy, Params(**{**p.__dict__, "start": m.idx[a], "end": m.idx[cap]}), pay, (a, cap))
    e, status = find_exit(m, a, rule, ms, th, res)
    return outcome_from(m, res, a, e, status, cls_arr[e]), res


# ── 모든 시작 월 (검산·분포용) ────────────────────
def start_months(m: Market, first: str, min_years: float) -> list[int]:
    out = []
    month = pd.Timestamp(first)
    while True:
        a = m.i_on_or_after(month)
        if a >= len(m.idx) or m.idx[a] + pd.DateOffset(years=int(min_years)) > m.idx[-1]:
            break
        out.append(a)
        month += pd.DateOffset(months=1)
    return out


def scan_rule(m: Market, strategies: list[str], p: Params, rule: Rule, th: Thresholds,
              first: str = "2010-03-01") -> pd.DataFrame:
    ms = market_state(m)
    cls_arr = classify(ms["dd"].to_numpy(), ms["above200"].to_numpy(), th)
    pay = pay_mask(m, p.pay_day)
    rows = []
    for a in start_months(m, first, rule.min_years):     # 시작 + N년이 데이터 안에 있는 시작 월만
        for s in strategies:
            o, _ = run_rule(m, s, p, a, rule, ms, th, pay, cls_arr)
            rows.append(o.__dict__ | {"start": m.idx[a], "exit": m.idx[o.e]})
    return pd.DataFrame(rows)
