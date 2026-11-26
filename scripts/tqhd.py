"""TQHD 판정 규칙 (파이썬 쪽). 같은 공식이 assets/core.js 에 있다 — 둘은 tests/test_cross.py 로 대조한다.

상태
  낮  day   : QQQ 종가가 50일선 또는 200일선 중 하나라도 위(초과 >) → TQQQ 100%
  밤  night : 두 선 다 같거나 아래(<=) → 현금
  사냥 hunt : 밤인 날 비중은 RSI2 가 정한다 (양방향)
              RSI2 < 5 → 100%, 5 ≤ RSI2 < 15 → 50%, 15 ≤ RSI2 ≤ 50 → 직전 비중 유지 (사냥 중일 때만),
              RSI2 > 50 → 전량 매도(밤). 사냥 중 선 회복 → 청산 없이 낮.
가격은 전부 배당조정(수정주가) 종가.
이동평균은 오늘 종가를 포함한 단순이동평균, RSI2 는 Wilder 방식(기간 2).
"""
from __future__ import annotations

import math

FAST, SLOW = 50, 200
HUNT_HALF, HUNT_FULL, HUNT_EXIT = 15.0, 5.0, 50.0
DAY, NIGHT, HUNT = "day", "night", "hunt"


# ── RSI2 (Wilder) ───────────────────────────────
def rsi_from(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def rsi_step(prev_close: float, avg_gain: float, avg_loss: float, price: float):
    """직전 종가까지의 Wilder 평균에서 '오늘 종가 = price' 로 한 걸음. (rsi, 새 평균 상승폭, 새 평균 하락폭)"""
    diff = price - prev_close
    gain = diff if diff > 0 else 0.0
    loss = -diff if diff < 0 else 0.0
    g = avg_gain + (gain - avg_gain) / 2.0
    l = avg_loss + (loss - avg_loss) / 2.0
    return rsi_from(g, l), g, l


def wilder_rsi2(closes):
    """종가 목록 → (rsi, avg_gain, avg_loss) 목록. 첫 평균은 처음 두 변화의 단순평균, 그 뒤는 Wilder 재귀."""
    n = len(closes)
    rsi, ag, al = [math.nan] * n, [math.nan] * n, [math.nan] * n
    if n < 3:
        return rsi, ag, al
    d1, d2 = closes[1] - closes[0], closes[2] - closes[1]
    ag[2] = (max(d1, 0.0) + max(d2, 0.0)) / 2.0
    al[2] = (max(-d1, 0.0) + max(-d2, 0.0)) / 2.0
    rsi[2] = rsi_from(ag[2], al[2])
    for i in range(3, n):
        rsi[i], ag[i], al[i] = rsi_step(closes[i - 1], ag[i - 1], al[i - 1], closes[i])
    return rsi, ag, al


# ── 이동평균 · 판정 ─────────────────────────────
def live_sma(sum_prev: float, n: int, price: float) -> float:
    """직전 n-1 일 종가 합 + 오늘 가격 → n 일 이동평균."""
    return (sum_prev + price) / n


def is_night(price: float, sma_fast: float, sma_slow: float) -> bool:
    """두 선 다 같거나 아래(<=)면 밤. 하나라도 위(>)면 낮."""
    return price <= sma_fast and price <= sma_slow


def next_state(prev_state: str | None, prev_weight: int, night: bool, rsi: float):
    """전날 상태 + 오늘 (밤 여부, RSI2) → (상태, TQQQ 비중 %)."""
    if not night:
        return DAY, 100                          # 사냥 중 선 회복도 청산 없이 낮
    if rsi < HUNT_FULL:                          # 밤이 되는 날에도 바로 사냥
        return HUNT, 100
    if rsi < HUNT_HALF:                          # 100% 였어도 5~15 로 올라오면 50% 로 줄임
        return HUNT, 50
    if prev_state == HUNT:
        if rsi > HUNT_EXIT:
            return NIGHT, 0
        return HUNT, prev_weight                 # 15~50: 직전 비중 유지
    return NIGHT, 0


def evaluate(base: dict, price: float) -> dict:
    """state.json 의 '직전 종가까지 누적값' + 가격 하나 → 그 가격이 오늘 종가라면의 판정."""
    s50 = live_sma(base["sum_prev_49"], FAST, price)
    s200 = live_sma(base["sum_prev_199"], SLOW, price)
    rsi, _, _ = rsi_step(base["qqq_prev_close"], base["wilder_avg_gain"], base["wilder_avg_loss"], price)
    night = is_night(price, s50, s200)
    state, weight = next_state(base["prev_state"], base["prev_weight"], night, rsi)
    return {"sma50": s50, "sma200": s200, "rsi2": rsi, "night": night, "state": state, "weight": weight}


# ── 임계 가격 ───────────────────────────────────
def cross_price(sum_prev: float, n: int) -> float:
    """가격 = 그 가격을 포함한 n일선 이 되는 가격. 이 가격 이하로 마감하면 그 선 이하(밤 쪽)."""
    return sum_prev / (n - 1)


def rsi_price(prev_close: float, avg_gain: float, avg_loss: float, target: float) -> float:
    """RSI2 가 정확히 target 이 되는 오늘 종가 (닫힌 형태). RSI2 는 가격에 대해 증가함수."""
    flat = rsi_from(avg_gain / 2.0, avg_loss / 2.0)        # 보합일 때
    rs = target / (100.0 - target)
    if target > flat:                                      # 올라야 함: 2g' = ag + d, 2l' = al
        return prev_close + (rs * avg_loss - avg_gain)
    if target < flat:                                      # 내려야 함: 2g' = ag, 2l' = al + d
        return prev_close - (avg_gain / rs - avg_loss)
    return prev_close
