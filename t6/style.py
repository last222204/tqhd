"""사이트 전체 공통 스타일: 색 의미, 숫자 표기, 차트(Plotly) 모양.

모든 페이지가 여기 있는 것만 가져다 쓴다. 색·표기·차트 모양을 바꾸려면 이 파일만 고치면 된다.
"""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go

WEEKDAY = "월화수목금토일"
FONT = "Pretendard, 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif"

# ── 색 의미 (사이트 전체 공통) ────────────────────
SUN = "#eb6834"          # ☀️ TQQQ 보유 · TQQQ 그냥 적립
RAIN = "#6f86c9"         # ☂️ 피신 (SGOV)
RAIN_FILL = "rgba(111,134,201,0.24)"   # 피신 기간 배경 (밝은·어두운 화면 모두 보이게)
UMBRELLA = "#2a78d6"     # ☂️ 우산 전략
QQQ = "#8f8e88"          # QQQ (1배 기준선) — 회색, 밝은·어두운 화면 모두 보임
QLD = "#a46ae0"          # QLD 2배
GAIN = "#1f9d55"         # 보험금 · 이득
LOSS = "#d03b3b"         # 보험료 · 손해
WARN = "#f0a500"         # 경고 (경계선·경고등)
NEUTRAL = "#9a9890"      # 보통 · 진행 중
SMA50 = "#e0a100"        # 50일선
SMA200 = "#d55181"       # 200일선
CANDLE_UP, CANDLE_DOWN = "#e34948", "#2a78d6"   # 한국식 캔들
INVESTED = "rgba(128,128,128,0.75)"           # 넣은 돈 (점선)
FX = "#3d8fb0"           # 원/달러 환율 (전략 색과 겹치지 않는 청록)
SOX = "#b9b7ae"          # 반도체 지수 비교선

STRATEGY = {"UMBRELLA": UMBRELLA, "TQQQ": SUN, "QLD": QLD, "QQQ": QQQ}
CLASS = {"green": GAIN, "red": LOSS, "gray": NEUTRAL}
CLASS_FILL = {"green": "rgba(31,157,85,0.14)", "red": "rgba(208,59,59,0.14)"}

H_BIG, H_SMALL = 420, 280
CONFIG = {"displaylogo": False, "displayModeBar": False, "scrollZoom": True}   # 도구 막대는 겹쳐서 숨김


# ── 숫자 표기 ────────────────────────────────────
def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x)) and np.isfinite(x)


def won(x, short: bool = True) -> str:
    """원화. short=True 면 1억 이상은 '1.23억원', 그 아래는 '12,345,678원'."""
    if not _ok(x):
        return "–"
    if short and abs(x) >= 1e8:
        return f"{x / 1e8:,.2f}억원"
    return f"{x:,.0f}원"


def won_full(x) -> str:
    """'1.23억원 (123,456,789원)'"""
    if not _ok(x):
        return "–"
    return won(x) if abs(x) < 1e8 else f"{won(x)} ({x:,.0f}원)"


def usd(x, cents: bool = True) -> str:
    if not _ok(x):
        return "–"
    return f"${x:,.2f}" if cents else f"${x:,.0f}"


def mult(x) -> str:
    return "–" if not _ok(x) else f"{x:.2f}배"


def pct(x, sign: bool = True) -> str:
    """수익률·변화: '+12.3%'"""
    return "–" if not _ok(x) else (f"{x:+.1%}" if sign else f"{x:.1%}")


def ratio(x) -> str:
    """비율·비중: '19%'"""
    return "–" if not _ok(x) else f"{x:.0%}"


def d(x) -> str:
    """'2026-11-13'"""
    if x is None or (not isinstance(x, (date, datetime)) and pd.isna(x)):
        return "–"
    return pd.Timestamp(x).strftime("%Y-%m-%d")


def dw(x) -> str:
    """'2026-11-13 (금)'"""
    if x is None or pd.isna(x):
        return "–"
    t = pd.Timestamp(x)
    return f"{t:%Y-%m-%d} ({WEEKDAY[t.weekday()]})"


def years(x) -> str:
    return "–" if not _ok(x) else f"{x:.1f}년"


def tdays(n) -> str:
    return "–" if n is None else f"{int(n)}거래일"


# ── 차트 ─────────────────────────────────────────
DATE_TICKS = [
    dict(dtickrange=[None, "M1"], value="%m-%d"),
    dict(dtickrange=["M1", "M12"], value="%Y-%m"),
    dict(dtickrange=["M12", None], value="%Y"),
]


def figure(rows: int = 1, heights=None, shared_x: bool = True) -> go.Figure:
    if rows == 1:
        return go.Figure()
    from plotly.subplots import make_subplots

    return make_subplots(rows=rows, cols=1, shared_xaxes=shared_x, row_heights=heights, vertical_spacing=0.04)


def date_hover(fig: go.Figure, x, y, row=None, col=None) -> None:
    """마우스를 올리면 맨 위에 '2026-11-13 (금)'이 나오게 하는 보이지 않는 선 (Plotly는 한글 요일을 못 써서)."""
    idx = pd.DatetimeIndex(x)
    tr = go.Scatter(x=idx, y=y, mode="lines", line=dict(width=0, color="rgba(0,0,0,0)"), showlegend=False,
                    customdata=[dw(t) for t in idx], hovertemplate="<b>%{customdata}</b><extra></extra>",
                    name="날짜")
    if row is not None:
        fig.add_trace(tr, row=row, col=col or 1)
    else:
        fig.add_trace(tr)


def style(fig: go.Figure, height: int = H_BIG, legend: bool = True, dates: bool = True,
          unified: bool = True, y_title: str | None = None, y_fmt: str | None = None) -> go.Figure:
    """모든 차트 공통 모양: 제목 없음(차트 위 Streamlit 소제목), 범례는 아래 가로, 같은 글꼴·여백."""
    fig.update_layout(
        height=height, title=None, font=dict(family=FONT, size=13),
        margin=dict(l=8, r=12, t=12, b=(78 if legend else 12)),
        showlegend=legend, dragmode="pan",
        hovermode=("x unified" if unified else "closest"),
        hoverlabel=dict(font=dict(family=FONT, size=13)),
        legend=dict(orientation="h", x=0, xanchor="left", y=0, yanchor="bottom", yref="container",
                    title=None, font=dict(size=12), itemclick="toggle", itemdoubleclick="toggleothers"),
    )
    if dates:
        fig.update_xaxes(tickformatstops=DATE_TICKS, hoverformat="%Y-%m-%d",
                         unifiedhovertitle=dict(text=" "))
    if y_title:
        fig.update_yaxes(title_text=y_title, title_standoff=6)
    if y_fmt:
        fig.update_yaxes(tickformat=y_fmt)
    return fig


def add_refuge(fig: go.Figure, periods, row="all", legend: bool = True) -> None:
    """피신 기간 배경 + 범례에 '☂️ 피신 기간' 항목."""
    for a, b in periods:
        kw = dict(row=row, col=1) if row is not None else {}
        fig.add_vrect(x0=pd.Timestamp(a) - pd.Timedelta(hours=12), x1=pd.Timestamp(b) + pd.Timedelta(hours=12),
                      fillcolor=RAIN_FILL, line_width=0, layer="below", **kw)
    if legend:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name="☂️ 피신 기간",
                                 marker=dict(symbol="square", size=13, color=RAIN_FILL.replace("0.24", "0.6"))))


def won_axis(fig: go.Figure, values, row=None) -> None:
    """원화 축 눈금을 '1억', '5,000만' 처럼."""
    parts = values if isinstance(values, (list, tuple)) else [values]
    flat = np.concatenate([np.ravel(np.asarray(p, float)) for p in parts]) if parts else np.array([])
    v = flat[np.isfinite(flat)]
    if not len(v):
        return
    hi = float(v.max())
    step = 10 ** math.floor(math.log10(max(hi, 1) / 4))
    for s in (1, 2, 2.5, 5, 10):
        if hi / (step * s) <= 6:
            step *= s
            break
    ticks = np.arange(0, hi + step, step)
    text = [("0" if t == 0 else f"{t / 1e8:g}억" if t >= 1e8 else f"{t / 1e4:,.0f}만") for t in ticks]
    kw = dict(row=row, col=1) if row is not None else {}
    fig.update_yaxes(tickvals=ticks, ticktext=text, **kw)


def log_mult_axis(fig: go.Figure, lo: float, hi: float) -> None:
    """배수 로그 축 눈금을 0.5·1·2·3·5·10배로 고정."""
    ticks = [t for t in (0.25, 0.5, 0.75, 1, 1.5, 2, 3, 5, 7, 10, 15, 20, 30, 50) if lo * 0.8 <= t <= hi * 1.25]
    fig.update_yaxes(type="log", tickvals=ticks, ticktext=[f"{t:g}배" for t in ticks])
