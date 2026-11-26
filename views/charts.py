"""📈 차트 — QQQ와 이동평균·피신 기간, TQQQ, 피신 기간별 손익, 환율."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from t6 import market_time as mt
from t6 import style as S
from t6 import rsi2, ui
from t6.config import FX_SYMBOL, RISK_OFF, RISK_ON, SIGNAL_SYMBOL, SMA_FAST, SMA_SLOW, VOL_ALERT
from t6.refuge import refuge_table
from t6.refuge import summary as refuge_summary
from t6.strategy import refuge_periods

PERIODS = {"3개월": 63, "1년": 252, "5년": 252 * 5, "전체": None}

ui.page_title("📈 차트", "확대: 두 손가락·마우스 휠 · 이동: 끌기 · 원래대로: 두 번 클릭 · 범례를 누르면 선을 켜고 끕니다.")
c1, c2 = st.columns([2, 1], vertical_alignment="center")
with c1:
    period = st.segmented_control("기간", list(PERIODS), default="1년", key="chart_period") or "1년"
with c2:
    raw_mode = st.toggle("배당 미조정 가격으로 보기", value=False,
                         help="신호는 항상 배당조정 종가로 판정합니다. 이 스위치는 그림만 바꿉니다.")
col = "close" if raw_mode else "adj_close"

qqq = ui.prices(SIGNAL_SYMBOL)
if qqq.empty:
    st.info("시세가 없습니다. 위의 '🔄 시세 새로고침'을 눌러 주세요.")
    ui.footer()
    st.stop()

sf_off = ui.signals("adj_close")          # 공식 신호 (피신 배경·교체 표시)
sf_show = ui.signals(col)                 # 그림에 쓸 이동평균


def window(df: pd.DataFrame) -> pd.DataFrame:
    n = PERIODS[period]
    return df if n is None else df.iloc[-n:]


def rangebreaks(idx: pd.DatetimeIndex) -> list:
    """주말과 미국 휴장일을 x축에서 빼서 캔들이 붙어 보이게."""
    if len(idx) == 0:
        return []
    holidays = pd.bdate_range(idx[0], idx[-1]).difference(idx)
    return [dict(bounds=["sat", "mon"]), dict(values=[x.strftime("%Y-%m-%d") for x in holidays])]


# ── QQQ ──────────────────────────────────────────
px = window(qqq)
sfw_show = sf_show.loc[px.index]
sfw_off = sf_off.loc[px.index]
if raw_mode:
    o, h, l, c = px["open"], px["high"], px["low"], px["close"]
else:
    k = px["adj_close"] / px["close"]
    o, h, l, c = px["open"] * k, px["high"] * k, px["low"] * k, px["adj_close"]

ui.section("QQQ 일봉과 이동평균",
           f"{'배당 미조정' if raw_mode else '배당조정'} 가격. 가운데 칸 = RSI2 (점선 10·50, ▲ 사냥 진입 ▼ 종료), "
           f"아래 칸 = 20거래일 변동성 (주황 점선 = 경고등 기준 {VOL_ALERT:.0%}).")
fig = S.figure(rows=3, heights=[0.6, 0.22, 0.18])
S.date_hover(fig, px.index, c, row=1)
fig.add_trace(go.Candlestick(
    x=px.index, open=o, high=h, low=l, close=c, name="QQQ",
    increasing=dict(line=dict(color=S.CANDLE_UP, width=1), fillcolor=S.CANDLE_UP),
    decreasing=dict(line=dict(color=S.CANDLE_DOWN, width=1), fillcolor=S.CANDLE_DOWN),
    text=[f"QQQ 시가 {S.usd(a)} · 고가 {S.usd(b)} · 저가 {S.usd(x)} · 종가 {S.usd(y)}" for a, b, x, y in zip(o, h, l, c)],
    hoverinfo="text",
), row=1, col=1)
fig.add_trace(go.Scatter(x=px.index, y=sfw_show["sma_fast"], name=f"{SMA_FAST}일선",
                         line=dict(color=S.SMA50, width=2), hovertemplate=f"{SMA_FAST}일선 %{{y:$,.2f}}<extra></extra>"),
              row=1, col=1)
fig.add_trace(go.Scatter(x=px.index, y=sfw_show["sma_slow"], name=f"{SMA_SLOW}일선",
                         line=dict(color=S.SMA200, width=2), hovertemplate=f"{SMA_SLOW}일선 %{{y:$,.2f}}<extra></extra>"),
              row=1, col=1)
S.add_refuge(fig, refuge_periods(sfw_off.dropna(subset=["signal"])), row="all")
sw = sfw_off[sfw_off["switch"]]
for to, sym, txt, colr in [(RISK_OFF, "triangle-down", "☂️ 피신으로 교체", S.RAIN),
                           (RISK_ON, "triangle-up", "☀️ TQQQ로 교체", S.SUN)]:
    dd = sw[sw["signal"] == to].index
    if len(dd):
        y = (h.loc[dd] * 1.03) if to == RISK_OFF else (l.loc[dd] * 0.97)
        fig.add_trace(go.Scatter(x=dd, y=y, mode="markers", name=txt,
                                 marker=dict(symbol=sym, size=12, color=colr, line=dict(width=1.2, color="white")),
                                 hovertemplate=f"{txt}<extra></extra>"), row=1, col=1)
# RSI2 (백테스트와 같은 계산, 항상 배당조정 종가 전체로 계산한 뒤 기간만 자름) + 사냥 진입·종료
rsi_all = rsi2.rsi_series(qqq["adj_close"])
rsi_w = rsi_all.loc[px.index]
fig.add_trace(go.Scatter(x=px.index, y=rsi_w, name="RSI2", line=dict(color=S.QQQ, width=1.4),
                         hovertemplate="RSI2 %{y:.1f}<extra></extra>"), row=2, col=1)
for lvl in (rsi2.RSI_BUY, rsi2.RSI_SELL):
    fig.add_hline(y=lvl, line=dict(color=S.INVESTED, width=1, dash="dot"), row=2, col=1)
hunts = rsi2.hunts(rsi_all, sf_off["signal"] == RISK_OFF)
h_in = hunts[hunts["entry"] >= px.index[0]]
if len(h_in):
    fig.add_trace(go.Scatter(x=h_in["entry"], y=rsi_all.loc[h_in["entry"]], mode="markers", name="🦇 사냥 진입",
                             marker=dict(symbol="triangle-up", size=11, color=S.SUN, line=dict(width=1, color="white")),
                             hovertemplate="🦇 사냥 진입 · RSI2 %{y:.1f}<extra></extra>"), row=2, col=1)
h_out = hunts[hunts["exit"].notna() & (hunts["exit"] >= px.index[0])]
if len(h_out):
    fig.add_trace(go.Scatter(x=h_out["exit"], y=rsi_all.loc[pd.DatetimeIndex(h_out["exit"])], mode="markers",
                             name="🔙 사냥 종료", customdata=h_out["reason"],
                             marker=dict(symbol="triangle-down", size=11, color=S.RAIN, line=dict(width=1, color="white")),
                             hovertemplate="🔙 사냥 종료 (%{customdata}) · RSI2 %{y:.1f}<extra></extra>"), row=2, col=1)
fig.add_trace(go.Scatter(x=px.index, y=sfw_off["vol"], name="20일 변동성", showlegend=False,
                         line=dict(color=S.QQQ, width=1.5), hovertemplate="20일 변동성 %{y:.1%}<extra></extra>"),
              row=3, col=1)
fig.add_hline(y=VOL_ALERT, line=dict(color=S.WARN, width=1.2, dash="dash"), row=3, col=1)
fig.update_xaxes(rangeslider_visible=False, rangebreaks=rangebreaks(px.index))
S.style(fig, height=620)
fig.update_yaxes(tickformat="$,.0f", row=1, col=1)
fig.update_yaxes(range=[0, 100], tickvals=[10, 50, 90], row=2, col=1)
fig.update_yaxes(tickformat=".0%", row=3, col=1)
ui.plot(fig)

# ── TQQQ ─────────────────────────────────────────
tq = window(ui.prices(RISK_ON))
if not tq.empty:
    ui.section("TQQQ", "남보라 배경 = ☂️ 피신 기간.")
    y = tq["close"] if raw_mode else tq["adj_close"]
    f = go.Figure()
    S.date_hover(f, tq.index, y)
    f.add_trace(go.Scatter(x=tq.index, y=y, name="TQQQ", line=dict(color=S.SUN, width=2),
                           hovertemplate="TQQQ %{y:$,.2f}<extra></extra>"))
    S.add_refuge(f, refuge_periods(sf_off.loc[sf_off.index.intersection(tq.index)].dropna(subset=["signal"])),
                 row=None, legend=False)
    S.style(f, height=S.H_SMALL, legend=False, y_fmt="$,.0f")
    ui.plot(f)

# ── 피신 기간별 손익 ─────────────────────────────
ui.section("☂️ 피신 기간별 손익",
           "피신 한 번마다, TQQQ에 그대로 있었을 때보다 계좌가 얼마나 더 많아졌나(이득) 또는 줄었나(손해). "
           "SGOV로 바꾼 날 종가 → TQQQ로 돌아온 날 종가, 배당조정 가격 기준.")
tbl = refuge_table(sf_off, qqq["adj_close"], ui.prices(RISK_ON)["adj_close"], ui.prices(RISK_OFF)["adj_close"])
if not tbl.empty and PERIODS[period] is not None:
    tbl = tbl[tbl["end"] >= px.index[0]]
tbl = tbl.reset_index(drop=True)

if tbl.empty:
    st.info(f"선택한 기간({period})에는 피신이 없었습니다.")
else:
    sm = refuge_summary(tbl)
    m1, m2, m3 = st.columns(3)
    ui.metric(m1, "피신 횟수 (끝난 것)", f"{sm['n']}번",
              note=f"이득 {sm['wins']} · 손해 {sm['losses']}" + (f" · 진행 중 {sm['ongoing']}" if sm["ongoing"] else ""))
    ui.metric(m2, "모든 피신을 합친 효과", S.pct(sm["total"]) if sm["n"] else "–",
              note=("이득" if sm["total"] > 0 else "손해") if sm["n"] else "끝난 피신 없음")
    if sm["n"]:
        b, w = sm["best"], sm["worst"]
        ui.metric(m3, "가장 컸던 이득 / 손해",
                  f"{S.pct(b['effect']) if b['effect'] > 0 else '없음'} / {S.pct(w['effect']) if w['effect'] <= 0 else '없음'}",
                  note=" / ".join([S.d(b["start"])[:7] if b["effect"] > 0 else "–",
                                   S.d(w["start"])[:7] if w["effect"] <= 0 else "–"]))

    def label(r):
        star = "*" if (r["tqqq_synthetic"] or r["sgov_cash"]) else ""
        return f"{S.d(r['start'])}{star}"

    hover = [
        f"<b>{S.dw(r['start'])} → {'진행 중' if r['ongoing'] else S.dw(r['end'])}</b> ({r['days']}거래일)<br>"
        f"TQQQ 그대로: {S.pct(r['tqqq'])}{' (QQQ×3 합성)' if r['tqqq_synthetic'] else ''}<br>"
        f"SGOV 피신: {S.pct(r['sgov'])}{' (상장 전, 현금 0%)' if r['sgov_cash'] else ''}<br>"
        f"QQQ: {S.pct(r['qqq'])}<br><b>피신 효과: {S.pct(r['effect'])}"
        f"{' (진행 중, 판정 안 함)' if r['ongoing'] else ''}</b>"
        for _, r in tbl.iterrows()
    ]
    colors = [S.NEUTRAL if o else (S.GAIN if e > 0 else S.LOSS) for e, o in zip(tbl["effect"], tbl["ongoing"])]
    ui.chart_title("피신 효과", "초록 = 이득, 빨강 = 손해, 회색 = 진행 중 (판정 안 함)")
    fb = go.Figure(go.Bar(
        x=[label(r) for _, r in tbl.iterrows()], y=tbl["effect"], marker_color=colors, marker_line_width=0,
        hovertext=hover, hoverinfo="text",
        text=[("진행 중" if o else S.pct(e)) for e, o in zip(tbl["effect"], tbl["ongoing"])] if len(tbl) <= 25 else None, textposition="outside", cliponaxis=False,
    ))
    fb.add_hline(y=0, line=dict(color="rgba(128,128,128,.6)", width=1))
    S.style(fb, height=360, legend=False, dates=False, unified=False, y_fmt=".0%")
    fb.update_layout(bargap=0.25)
    fb.update_xaxes(type="category")
    ui.plot(fb)

    show = pd.DataFrame({
        "피신 시작": tbl["start"].map(S.d),
        "복귀일": [("진행 중" if o else S.d(e)) for o, e in zip(tbl["ongoing"], tbl["end"])],
        "거래일": tbl["days"],
        "TQQQ 그대로": tbl["tqqq"],
        "SGOV 피신": tbl["sgov"],
        "QQQ": tbl["qqq"],
        "피신 효과": tbl["effect"],
        "판정": ["진행 중" if o else ("이득" if e > 0 else "손해") for e, o in zip(tbl["effect"], tbl["ongoing"])],
        "비고": [", ".join(x for x in [("TQQQ 합성" if t else ""), ("SGOV 상장 전" if c else "")] if x)
               for t, c in zip(tbl["tqqq_synthetic"], tbl["sgov_cash"])],
    }).iloc[::-1]
    fmt = {c: "{:+.1%}" for c in ["TQQQ 그대로", "SGOV 피신", "QQQ", "피신 효과"]}
    st.dataframe(show.style.format(fmt), hide_index=True, width="stretch")
    if (tbl["tqqq_synthetic"] | tbl["sgov_cash"]).any():
        st.caption("\\* 표시: TQQQ 상장(2010-02) 전은 QQQ 일간 수익률×3으로 합성(보수·비용 미반영), "
                   "SGOV 상장(2020-05) 전은 현금 0%로 계산한 참고값입니다.")

# ── 환율 ─────────────────────────────────────────
fx = window(ui.prices(FX_SYMBOL))
if not fx.empty:
    ui.section("USD/KRW 환율")
    f = go.Figure()
    S.date_hover(f, fx.index, fx["close"])
    f.add_trace(go.Scatter(x=fx.index, y=fx["close"], name="USD/KRW", line=dict(color=S.FX, width=2),
                           hovertemplate="USD/KRW %{y:,.2f}원<extra></extra>"))
    S.style(f, height=S.H_SMALL, legend=False, y_fmt=",.0f")
    ui.plot(f)

st.page_link("views/review.py", label="QQQ 1년 변동성 추이는 '연간 점검'에 있습니다", icon="📋")
st.caption(f"마지막 데이터: {mt.fmt_date(qqq.index[-1].date())} 미국 종가")
ui.footer()
