"""장중 실시간 가격 (yfinance). 못 받으면 None — 화면은 '실시간 없음'으로 확정 값만 보여준다."""
from __future__ import annotations


def last_price(symbol: str) -> float | None:
    try:
        import yfinance as yf

        t = yf.Ticker(symbol)
        try:
            p = t.fast_info["lastPrice"]
            if p and p > 0:
                return float(p)
        except Exception:  # noqa: BLE001  — fast_info 가 안 되면 1분봉
            pass
        h = t.history(period="1d", interval="1m", prepost=False)
        if h is not None and not h.empty:
            return float(h["Close"].dropna().iloc[-1])
    except Exception:  # noqa: BLE001
        return None
    return None
