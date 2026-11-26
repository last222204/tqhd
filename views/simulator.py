"""시뮬레이터: 아무 시작일·기간·금액으로 우산 전략을 했다면."""
import random
from datetime import date, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from t6 import store, ui
from t6 import style as S
from t6.sim import data, engine, exits, metrics, scan
from t6.sim.engine import STRATEGY_NAMES, UMBRELLA, Costs, Params, Taxes

COLORS = S.STRATEGY
GAIN, LOSS, GREY = S.GAIN, S.LOSS, S.INVESTED
PLOT_CFG = S.CONFIG
COMPARE = ["QQQ", "QLD", "TQQQ"]
RULES = {"고정 기간 (년 수)": "fixed", "종료일 직접": "date", "졸업 A: 전고점 졸업": "ath",
         "졸업 B: 목표 배수 졸업": "target", "하락장 강제 청산": "crash", "무작위 청산": "random"}
CLS_COLOR = {exits.GREEN: S.CLASS_FILL["green"], exits.RED: S.CLASS_FILL["red"]}


@st.cache_resource(show_spinner="시세를 정리하는 중…")
def _market(version: int):
    return data.build()


won = S.won
d = S.d


def pct(x, sign=False):
    return S.pct(x, sign)


def layout(fig, h, title, desc=None, legend=True):
    """차트 제목은 Plotly 밖(차트 바로 위)에, 모양은 공통 style 로."""
    ui.chart_title(title, desc)
    x0 = next((t.x for t in fig.data if getattr(t, "x", None) is not None and len(t.x)), [])
    dates = len(x0) > 0 and isinstance(x0[0], (pd.Timestamp, np.datetime64)) or (
        len(x0) > 0 and hasattr(x0[0], "year") and not isinstance(x0[0], (int, float)))
    S.style(fig, height=h, legend=legend, dates=bool(dates))


if store.last_price_date("QQQ") is None:
    ui.page_title("🧪 시뮬레이터")
    st.info("시세가 아직 없습니다. 위의 '🔄 시세 새로고침'을 눌러 시세를 받은 뒤 다시 열어 주세요.")
    ui.footer()
    st.stop()

m = _market(store.data_version())
first_day = m.idx[int(np.argmax(m.ready))].date()
last_day = m.idx[-1].date()

ui.page_title("🧪 시뮬레이터", "아무 시작일·기간·금액으로 그때 우산 전략을 했다면. "
              "매매는 신호 당일 종가, 세금·수수료·환율까지 반영합니다.")

# ── 빠른 선택 ────────────────────────────────────
five_ago = max(first_day, date(last_day.year - 5, last_day.month, min(last_day.day, 28)))
PRESETS = {
    "닷컴 꼭대기 (2000-03)": date(2000, 3, 1),
    "금융위기 직전 (2007-10)": date(2007, 10, 1),
    "금융위기 바닥 (2009-03)": date(2009, 3, 9),
    "코로나 직전 (2020-02)": date(2020, 2, 19),
    "2022 하락장 직전 (2021-11)": date(2021, 11, 19),
    "5년 전 오늘": five_ago,
    "🎲 무작위": None,
}
if "sim_start" not in st.session_state:
    st.session_state["sim_start"] = five_ago
if "sim_cmp" in st.session_state:   # 예전에 고른 비교 대상 중 없어진 것(SPY) 정리
    st.session_state["sim_cmp"] = [s for s in st.session_state["sim_cmp"] if s in COMPARE]
cols = st.columns(4)
for k, (label, dd) in enumerate(PRESETS.items()):
    if cols[k % 4].button(label, width="stretch", key=f"preset_{k}"):
        if dd is None:
            span = (last_day - timedelta(days=365) - first_day).days
            dd = first_day + timedelta(days=random.randint(0, max(span, 1)))
        st.session_state["sim_start"] = dd
        st.session_state["sim_avg"] = False
avg_mode = st.session_state.get("sim_avg", False)
if cols[3].button("📊 모든 시기 평균", width="stretch", key="preset_avg",
                  type="primary" if avg_mode else "secondary"):
    st.session_state["sim_avg"] = True
    avg_mode = True

# ── 입력 ─────────────────────────────────────────
with st.form("sim_form"):
    c1, c2 = st.columns(2)
    start = c1.date_input("시작일", key="sim_start", min_value=first_day, max_value=last_day - timedelta(days=30))
    rule_name = c2.selectbox("청산 규칙", list(RULES), key="sim_rule",
                             help="언제 전부 팔고 세금을 정산하느냐. 졸업 규칙은 조건이 오는 첫날 청산합니다.")
    rk = RULES[rule_name]
    rule = None
    if rk == "fixed":
        years = c2.slider("몇 년", 1, 20, 5, key="sim_years")
        end_req = pd.Timestamp(start) + pd.DateOffset(years=years)
        length = pd.DateOffset(years=years)
        length_label = f"{years}년"
    elif rk == "date":
        if "sim_end" not in st.session_state:
            st.session_state["sim_end"] = min(last_day, start + timedelta(days=365 * 5))
        end_in = c2.date_input("종료일", min_value=first_day, max_value=last_day, key="sim_end")
        if end_in <= start:
            end_in = min(last_day, start + timedelta(days=365))
        end_req = pd.Timestamp(end_in)
        length = pd.DateOffset(days=(end_in - start).days)
        length_label = f"{(end_in - start).days}일"
    else:
        r1, r2, r3 = c2.columns(3)
        n_y = r1.number_input("최소 N년", 1, 20, 5, key="sim_n",
                              disabled=rk == "target", help="졸업 B는 시작 후 1년(252거래일)부터 판정합니다.")
        m_y = r2.number_input("최대 M년", 1, 30, 15, key="sim_m", help="이때까지 조건이 안 오면 강제 청산")
        x_t = r3.number_input("목표 X배", 1.1, 20.0, 2.0, 0.1, key="sim_x") if rk == "target" else 2.0
        seed = r3.number_input("시드", 0, 999_999, 0, key="sim_seed") if rk == "random" else 0
        if m_y < n_y and rk != "target":
            m_y = n_y
        rule = exits.Rule(rk, float(n_y if rk != "target" else 1), float(m_y), float(x_t), int(seed))
        end_req = pd.Timestamp(start) + pd.DateOffset(years=int(m_y))
        length = pd.DateOffset(years=int(rule.min_years))
        length_label = f"{int(rule.min_years)}~{int(m_y)}년"

    c1, c2, c3 = st.columns(3)
    initial = c1.number_input("처음 넣는 돈 (원)", 0, 10_000_000_000, 10_000_000, step=1_000_000, key="sim_init")
    monthly = c2.number_input("매월 적립금 (원, 0이면 거치식)", 0, 1_000_000_000, 1_000_000, step=100_000, key="sim_month")
    pay_day = c3.number_input("적립일 (매월, 휴장이면 다음 거래일)", 1, 28, 17, key="sim_payday")

    c1, c2 = st.columns(2)
    cur = c1.radio("통화 기준", ["원화 (그날 환율로 환전, 환율 효과 포함)", "달러 기준 (환율 고정)"], key="sim_cur")
    final_mode = c2.radio("마지막 날", ["전부 매도 후 세금 정산", "보유 유지 (세전 평가)"], key="sim_final")
    compare = st.multiselect("비교 대상 (그냥 적립)", COMPARE, default=COMPARE, key="sim_cmp",
                             format_func=lambda s: STRATEGY_NAMES[s])

    with st.expander("고급 설정 (세금·비용·검산 모드)"):
        a1, a2, a3, a4 = st.columns(4)
        sw = a1.number_input("교체 편도 %", 0.0, 5.0, 0.3, 0.05, key="sim_sw")
        buy = a2.number_input("적립 매수 %", 0.0, 5.0, 0.2, 0.05, key="sim_buy")
        taxs = a3.number_input("세금 납부용 매도 %", 0.0, 5.0, 0.3, 0.05, key="sim_taxsale")
        fin = a4.number_input("마지막 매도 %", 0.0, 5.0, 0.3, 0.05, key="sim_fin")
        b1, b2, b3 = st.columns(3)
        cap = b1.number_input("양도세율 %", 0.0, 50.0, 22.0, 0.5, key="sim_cap")
        ded = b2.number_input("연 기본공제 (원)", 0, 100_000_000, 2_500_000, 500_000, key="sim_ded")
        divt = b3.number_input("배당·이자세 %", 0.0, 50.0, 15.4, 0.1, key="sim_div")
        colab = st.toggle("검산 모드 (코랩 가정 그대로)", key="sim_colab",
                          help="환율 고정, 피난처 수익 전체에만 15.4%, 세금은 5월 첫 거래일에 평가액에서 차감, "
                               "피난처 매수 수수료 없음, 마지막 매도 0.2%. 위 비용·통화 설정은 무시됩니다.")
        d1, d2 = st.columns(2)
        g_dd = d1.number_input("🟢 상승장 청산: 전고점 대비 몇 % 이내 (그리고 200일선 위)", -50.0, 0.0, -5.0, 1.0,
                               key="sim_gdd")
        r_dd = d2.number_input("🔴 하락장 청산: 전고점 대비 몇 % 이하", -90.0, 0.0, -20.0, 1.0, key="sim_rdd")
    st.form_submit_button("계산하기", type="primary", width="stretch")

end_clamped = end_req.date() > last_day
p = Params(
    start=pd.Timestamp(start), end=min(end_req, pd.Timestamp(last_day)),
    initial_krw=float(initial), monthly_krw=float(monthly), pay_day=int(pay_day),
    fx_mode="real" if cur.startswith("원화") else "fixed",
    liquidate=final_mode.startswith("전부"), colab=colab,
    costs=Costs(sw / 100, buy / 100, taxs / 100, fin / 100),
    taxes=Taxes(cap / 100, float(ded), divt / 100),
)
strategies = [UMBRELLA] + compare
th = exits.Thresholds(g_dd / 100, r_dd / 100)
ms = exits.market_state(m)
cls_arr = exits.classify(ms["dd"].to_numpy(), ms["above200"].to_numpy(), th)


# ── 📊 모든 시기 평균 ─────────────────────────────
@st.cache_data(show_spinner="가능한 모든 시작 월을 계산하는 중… (처음 한 번만 몇 초)", max_entries=20)
def _scan_detail(version, key, strategies, length_key, inc_syn, _p, _length):
    return scan.scan_detail(_market(version), list(strategies), _p, _length, inc_syn)


def scan_key(p):
    return (p.initial_krw, p.monthly_krw, p.pay_day, p.fx_mode, p.liquidate, p.colab,
            tuple(p.costs.__dict__.values()), tuple(p.taxes.__dict__.values()))


@st.cache_data(show_spinner="청산 규칙을 모든 시작 월에 적용하는 중…", max_entries=30)
def _scan_rule(version, key, strategies, rule, th, inc_syn, _p):
    mk = _market(version)
    first = scan.REAL_FROM if not inc_syn else mk.idx[int(np.argmax(mk.ready))].strftime("%Y-%m-01")
    if inc_syn and pd.Timestamp(first) < mk.idx[int(np.argmax(mk.ready))]:
        first = (pd.Timestamp(first) + pd.DateOffset(months=1)).strftime("%Y-%m-%d")
    return exits.scan_rule(mk, list(strategies), _p, rule, th, first)


if avg_mode:
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    inc_syn_avg = c1.toggle("가상 데이터 구간도 포함 (2000년~)", value=False, key="sim_avg_syn",
                            help="끄면 실제 상품 구간(2010-03~)의 시작 월만 씁니다.")
    if c2.button("↩ 시작일 하나로 보기", width="stretch"):
        st.session_state["sim_avg"] = False
        st.rerun()
    if rule is not None:
        rdf = _scan_rule(store.data_version(), scan_key(p), tuple(strategies), rule, th, inc_syn_avg, p)
        if rdf.empty:
            st.info("계산할 수 있는 시작 월이 없습니다.")
            ui.footer()
            st.stop()
        starts = rdf["start"].drop_duplicates()
        st.markdown(f"### 📊 모든 시기 평균 — {exits.RULE_LABEL[rule.kind]} · 시작 월 {len(starts)}개 "
                    f"({starts.min():%Y-%m} ~ {starts.max():%Y-%m})")
        st.caption(f"각 달 첫 거래일에 시작, 청산 규칙 {length_label}"
                   f"{f', 목표 {rule.target:g}배' if rule.kind == 'target' else ''} · 처음 {won(p.initial_krw)} + "
                   f"매월 {won(p.monthly_krw)}{' · 검산 모드' if colab else ''}. 기간이 서로 달라서 연환산(IRR)이 주 지표입니다.")
        g = rdf.groupby("strategy")
        tab = pd.DataFrame({
            "연환산 중간값": g["irr"].median(), "연환산 평균": g["irr"].mean(),
            "연환산 운 나쁜 10%": g["irr"].quantile(0.10), "연환산 최악": g["irr"].min(),
            "배수 중간값": g["multiple"].median(), "배수 최악": g["multiple"].min(),
            "보유 중간값(년)": g["years"].median(), "원금손실": g["multiple"].apply(lambda x: float((x < 1).mean())),
            "최하방 최악": g["low"].min(),
            "졸업": g["status"].apply(lambda x: float((x == "grad").mean())),
            "최대 기간 강제": g["status"].apply(lambda x: float((x == "cap").mean())),
            "미졸업(데이터 끝)": g["status"].apply(lambda x: float((x == "data_end").mean())),
            "🟢 청산": g["cls"].apply(lambda x: float((x == exits.GREEN).mean())),
            "🔴 청산": g["cls"].apply(lambda x: float((x == exits.RED).mean())),
        }).loc[[s for s in strategies if s in set(rdf["strategy"])]]
        u = tab.loc[UMBRELLA]
        h1, h2, h3, h4 = st.columns(4)
        ui.metric(h1, "☂️ 연환산 중간값", pct(u["연환산 중간값"], True), f"최악 {pct(u['연환산 최악'], True)}")
        ui.metric(h2, "배수 중간값", f"{u['배수 중간값']:.2f}배", f"최악 {u['배수 최악']:.2f}배")
        ui.metric(h3, "보유 기간 중간값", f"{u['보유 중간값(년)']:.1f}년")
        ui.metric(h4, "🟢 / 🔴 청산 비율", f"{u['🟢 청산']:.0%} / {u['🔴 청산']:.0%}")
        show = tab.copy()
        show.index = [STRATEGY_NAMES[s] for s in show.index]
        fmt = {c: "{:+.1%}" for c in ["연환산 중간값", "연환산 평균", "연환산 운 나쁜 10%", "연환산 최악"]}
        fmt |= {"배수 중간값": "{:.2f}배", "배수 최악": "{:.2f}배", "보유 중간값(년)": "{:.1f}년"}
        fmt |= {c: "{:.0%}" for c in ["원금손실", "최하방 최악", "졸업", "최대 기간 강제", "미졸업(데이터 끝)",
                                       "🟢 청산", "🔴 청산"]}
        st.dataframe(show.style.format(fmt), width="stretch")
        fig = go.Figure()
        for s in strategies:
            gs = rdf[rdf["strategy"] == s]
            fig.add_trace(go.Scatter(x=gs["start"], y=gs["irr"], name=STRATEGY_NAMES[s], mode="lines",
                                     line=dict(color=COLORS[s], width=2.5 if s == UMBRELLA else 1.2), visible="legendonly" if s == "QLD" else True,
                                     hovertemplate=STRATEGY_NAMES[s] + " %{y:+.1%}<extra></extra>"))
        fig.add_hline(y=0, line=dict(color=GREY, width=1, dash="dot"))
        layout(fig, 380, "시작 월별 연환산 수익률 (IRR)")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
        out = rdf.assign(전략=rdf["strategy"].map(STRATEGY_NAMES), 분류=rdf["cls"].map(exits.CLASS_LABEL),
                         상태=rdf["status"].map(exits.STATUS_LABEL)).drop(columns=["strategy", "a", "e"])
        st.download_button("시작 월별 결과 CSV", out.to_csv(index=False).encode("utf-8-sig"),
                           f"청산규칙_{rule.kind}_{starts.min():%Y%m}_{starts.max():%Y%m}.csv", "text/csv")
        ui.footer()
        st.stop()
    df, paths = _scan_detail(store.data_version(), scan_key(p), tuple(strategies), str(length), inc_syn_avg, p, length)
    if df.empty:
        st.info("이 길이로 계산할 수 있는 시작 월이 없습니다. 기간을 줄여 보세요.")
        ui.footer()
        st.stop()
    starts = df["start"].drop_duplicates()
    st.markdown(f"### 📊 모든 시기 평균 — 시작 월 {len(starts)}개 ({starts.min():%Y-%m} ~ {starts.max():%Y-%m})")
    st.caption(f"각 달 첫 거래일에 시작해서 {length_label} 뒤까지, "
               f"처음 {won(p.initial_krw)} + 매월 {p.pay_day}일 {won(p.monthly_krw)} · "
               f"{'원화(환율 반영)' if p.fx_mode == 'real' else '달러 기준(환율 고정)'} · "
               f"{'마지막 날 전부 매도 세후' if p.liquidate else '보유 유지 세전'}"
               f"{' · 검산 모드' if colab else ''}. 위 입력의 시작일은 쓰지 않습니다.")
    if df["synthetic"].any():
        st.warning("⚠️ **가상 데이터 포함 구간이 섞여 있습니다. 실제보다 연 1~1.5%p 후할 수 있음.**")

    at = scan.average_table(df).loc[[s for s in strategies if s in set(df["strategy"])]]
    ua = at.loc[UMBRELLA]
    h1, h2, h3, h4 = st.columns(4)
    ui.metric(h1, "☂️ 평균 최종 배수", f"{ua['평균 배수']:.2f}배", f"중간값 {ua['중간값']:.2f}배")
    ui.metric(h2, "운 나쁜 10% / 최악", f"{ua['운 나쁜 10%']:.2f}배 / {ua['최악']:.2f}배")
    ui.metric(h3, "원금손실 확률", f"{ua['원금손실 확률']:.0%}")
    ui.metric(h4, "평균 연환산 (IRR)", pct(ua["평균 연환산"], True), f"평균 최대 낙폭 {ua['평균 최대 낙폭']:.0%}")

    show = at.copy()
    show.index = [STRATEGY_NAMES[s] for s in show.index]
    st.dataframe(show.style.format({
        "평균 배수": "{:.2f}배", "중간값": "{:.2f}배", "운 나쁜 10%": "{:.2f}배", "운 좋은 10%": "{:.2f}배",
        "최악": "{:.2f}배", "원금손실 확률": "{:.0%}", "평균 연환산": "{:+.1%}", "평균 최하방": "{:.0%}",
        "평균 최대 낙폭": "{:.1%}", "평균 원금 아래 기간": "{:.0%}", "평균 교체 횟수": "{:.1f}번",
        "평균 낸 세금": lambda v: won(v), "평균 수수료": lambda v: won(v)}), width="stretch")

    # 평균 경로
    fig = go.Figure()
    up = paths.get(UMBRELLA)
    if up is not None:
        fig.add_trace(go.Scatter(x=np.r_[up["years"], up["years"][::-1]], y=np.r_[up["p90"], up["p10"][::-1]],
                                 fill="toself", fillcolor="rgba(42,120,214,0.15)", line=dict(width=0),
                                 name="☂️ 운 나쁜 10% ~ 좋은 10%", hoverinfo="skip"))
    for s in strategies:
        if s in paths:
            pth = paths[s]
            fig.add_trace(go.Scatter(x=pth["years"], y=pth["mean"], name=STRATEGY_NAMES[s] + " 평균",
                                     line=dict(color=COLORS[s], width=3 if s == UMBRELLA else 1.5), visible="legendonly" if s == "QLD" else True,
                                     hovertemplate=STRATEGY_NAMES[s] + " %{y:.0%}<extra></extra>"))
    fig.add_hline(y=1, line=dict(color=S.LOSS, width=1, dash="dash"))
    layout(fig, 400, "평균 경로: 계좌 ÷ 넣은 돈 (시작 후 경과 기간)")
    fig.update_xaxes(title_text="시작 후 년")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

    # 시작 월별 최종 배수
    fig = go.Figure()
    for s in strategies:
        g = df[df["strategy"] == s]
        fig.add_trace(go.Scatter(x=g["start"], y=g["multiple"], name=STRATEGY_NAMES[s], mode="lines",
                                 line=dict(color=COLORS[s], width=2.5 if s == UMBRELLA else 1.2), visible="legendonly" if s == "QLD" else True,
                                 hovertemplate=STRATEGY_NAMES[s] + " %{y:.2f}배<extra></extra>"))
    fig.add_hline(y=1, line=dict(color=GREY, width=1, dash="dot"))
    layout(fig, 380, "시작 월별 최종 배수 (어느 달에 시작했느냐에 따라)")
    fig.update_xaxes(title_text="시작 월")
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

    # 분포
    du = df[df["strategy"] == UMBRELLA]["multiple"]
    fig = go.Figure(go.Histogram(x=du, nbinsx=30, marker_color=COLORS[UMBRELLA], marker_line_width=0,
                                 hovertemplate="%{x} : %{y}개<extra></extra>"))
    fig.add_vline(x=float(du.mean()), line=dict(color="#d03b3b", width=2), annotation_text=f"평균 {du.mean():.2f}배")
    fig.add_vline(x=1, line=dict(color=GREY, width=1, dash="dot"), annotation_text="원금",
                  annotation_position="bottom right")
    layout(fig, 300, "☂️ 최종 배수 분포")
    fig.update_layout(showlegend=False, hovermode="closest", bargap=0.05)
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

    best_s = df[df["strategy"] == UMBRELLA].nlargest(1, "multiple").iloc[0]
    worst_s = df[df["strategy"] == UMBRELLA].nsmallest(1, "multiple").iloc[0]
    st.caption(f"☂️ 가장 좋았던 시작: {best_s['start']:%Y-%m} ({best_s['multiple']:.2f}배) · "
               f"가장 나빴던 시작: {worst_s['start']:%Y-%m} ({worst_s['multiple']:.2f}배). "
               "프리셋 버튼을 누르면 그 시작일 하나를 자세히 볼 수 있습니다.")
    out = df.assign(전략=df["strategy"].map(STRATEGY_NAMES)).drop(columns=["strategy"])
    st.download_button("시작 월별 결과 CSV", out.to_csv(index=False).encode("utf-8-sig"),
                       f"모든시기평균_{starts.min():%Y%m}_{starts.max():%Y%m}.csv", "text/csv")
    ui.footer()
    st.stop()

pay = data.pay_mask(m, p.pay_day)
exit_info = {}          # 전략 → (청산일 인덱스, 상태)
if rule is None:
    try:
        a, b = engine.window(m, p.start, p.end)
    except ValueError as e:
        st.error(str(e))
        st.stop()
    ab = {s: (a, b) for s in strategies}
else:
    p = Params(**{**p.__dict__, "liquidate": True})      # 청산 규칙은 항상 그날 전부 매도
    a = m.i_on_or_after(p.start)
    if a >= len(m.idx) - 1 or not m.ready[a]:
        st.error("시작일을 쓸 수 없습니다 (데이터 범위 밖)")
        st.stop()
    ab = {}
    for s in strategies:
        o, _ = exits.run_rule(m, s, p, a, rule, ms, th, pay, cls_arr)
        ab[s] = (a, o.e)
        exit_info[s] = (o.e, o.status)
    b = ab[UMBRELLA][1]
    end_clamped = False
res = {s: engine.run(m, s, p, pay, ab[s]) for s in strategies}
summ = {s: metrics.summary(r) for s, r in res.items()}
U, SU = res[UMBRELLA], summ[UMBRELLA]

# ── 경고 ─────────────────────────────────────────
if any(r.synthetic for r in res.values()):
    syn = [STRATEGY_NAMES[s] for s, r in res.items() if r.synthetic]
    st.warning("⚠️ **이 기간은 가상 데이터 포함, 실제보다 연 1~1.5%p 후할 수 있음.** "
               f"({', '.join(syn)}: 상장 전 구간을 QQQ×배수 − 단기금리 − 연 0.95%로 만듦)")
if end_clamped:
    st.info(f"종료일이 데이터보다 뒤라서 {d(m.idx[b])}(마지막 데이터)까지 계산했습니다.")
if colab:
    st.info("검산 모드: 코랩 백테스트 가정으로 계산 중입니다 (환율 고정 등).")
st.caption(f"계산 기간: {d(m.idx[a])} ~ {d(m.idx[b])} ({b - a}거래일) · "
           f"처음 {won(p.initial_krw)} + 매월 {p.pay_day}일 {won(p.monthly_krw)} · "
           f"{'원화(환율 반영)' if p.fx_mode == 'real' else '달러 기준(환율 고정)'} · "
           f"{'마지막 날 전부 매도 세후' if p.liquidate else '보유 유지 세전'}")


def exit_card(e: int, status: str, who: str = "") -> str:
    c = cls_arr[e]
    yrs = (m.idx[e] - m.idx[a]).days / 365.25
    bg = {"green": "rgba(12,163,12,.12)", "red": "rgba(208,59,59,.12)", "gray": "rgba(128,128,128,.10)"}[c]
    badge = "" if status == "grad" else f" · <b>{exits.STATUS_LABEL[status]}</b>"
    return (f"<div class='t6-card' style='background:{bg}'>"
            f"<div class='t6-sub'>{who}청산일 ({RULE_LABEL_SHORT})</div>"
            f"<div style='font-size:clamp(1.6rem,6vw,2.4rem);font-weight:800'>{d(m.idx[e])} · {exits.CLASS_LABEL[c]}</div>"
            f"<div class='t6-sub'>시작 후 <b>{yrs:.1f}년</b> ({e - a}거래일) · 그날 QQQ 전고점 대비 "
            f"<b>{ms['dd'].iloc[e]:+.1%}</b>, 200일선 {'위' if ms['above200'].iloc[e] else '아래'}{badge}</div></div>")


if rule is not None:
    RULE_LABEL_SHORT = exits.RULE_LABEL[rule.kind]
    if rule.kind == "target":
        for s in strategies:
            st.markdown(exit_card(*exit_info[s], who=f"{STRATEGY_NAMES[s]} "), unsafe_allow_html=True)
        st.caption("졸업 B는 계좌마다 2배가 되는 날이 달라서 전략별 청산일이 다릅니다. "
                   "아래 피신 기록·QQQ 차트는 ☂️ 우산의 기간 기준입니다.")
    else:
        st.markdown(exit_card(*exit_info[UMBRELLA]), unsafe_allow_html=True)
        st.caption("모든 전략이 같은 날 청산합니다.")
else:
    RULE_LABEL_SHORT = "고정 기간" if rk == "fixed" else "종료일 직접"
    st.markdown(exit_card(b, "fixed" if rk == "fixed" else "date"), unsafe_allow_html=True)

# ── 출력 1: 요약 ─────────────────────────────────
ui.section("요약")
h1, h2, h3, h4 = st.columns(4)
ui.metric(h1, "☂️ 최종 금액", won(SU["final_krw"]), f"${SU['final_usd']:,.0f}")
ui.metric(h2, "최종 배수", f"{SU['multiple']:.2f}배", f"넣은 돈 {won(SU['invested'])}")
ui.metric(h3, "연환산 수익률 (IRR)", pct(SU["irr"], True))
ui.metric(h4, "최대 낙폭", pct(SU["mdd"]), f"최하방 {SU['low']:.0%} ({d(SU['low_date'])})")

rows = []
for s in strategies:
    x = summ[s]
    rec = d(x["mdd_recover"]) if x["mdd_recover"] is not None else "미회복"
    rows.append({
        "전략": STRATEGY_NAMES[s],
        "배수": x["multiple"],
        "최종 금액": x["final_krw"],
        "연환산": x["irr"],
        "최대 낙폭": x["mdd"],
        "최하방": x["low"],
        "원금 아래": x["under_share"],
        "최장 원금 아래": x["under_longest"],
        "넣은 돈": x["invested"],
        "최종($)": x["final_usd"],
        "낸 세금": x["cap_tax"] + x["div_tax"],
        "수수료": x["fees"],
        "최하방 날": d(x["low_date"]),
        "최대 낙폭 기간": f"{d(x['mdd_peak'])} → {d(x['mdd_trough'])} (회복 {rec})",
    })
summary_df = pd.DataFrame(rows)
st.dataframe(summary_df.style.format({
    "배수": "{:.2f}배", "최종 금액": S.won, "연환산": "{:+.1%}", "최대 낙폭": "{:.1%}", "최하방": "{:.0%}",
    "원금 아래": "{:.0%}", "최장 원금 아래": "{:,.0f}거래일", "넣은 돈": S.won, "최종($)": "${:,.0f}",
    "낸 세금": S.won, "수수료": S.won}), hide_index=True, width="stretch",
    column_config={"전략": st.column_config.TextColumn(pinned=True)})
with st.expander("용어 설명"):
    st.markdown(
        "- **최하방** = 기간 중 계좌 ÷ 넣은 돈이 가장 낮았던 값과 그날\n"
        "- **최대 낙폭** = 적립금 효과를 뺀 시간가중 기준, 고점 대비 가장 크게 빠진 비율과 그 기간\n"
        "- **원금 아래** = 계좌가 넣은 돈보다 적었던 날의 비율, 가장 길게 이어진 기간\n"
        "- **낸 세금** = 양도세 + 배당·이자세 · **연환산** = 적립 날짜를 반영한 IRR"
    )

# 계좌 차트
fig = go.Figure()
fig.add_trace(go.Scatter(x=U.dates, y=U.invested, name="넣은 돈", line=dict(color=GREY, width=2, dash="dot", shape="hv"),
                         hovertemplate="넣은 돈 %{y:,.0f}원<extra></extra>"))
for s in strategies:
    v = metrics.net_values(res[s])
    fig.add_trace(go.Scatter(x=res[s].dates, y=v, name=STRATEGY_NAMES[s],
                             line=dict(color=COLORS[s], width=3 if s == UMBRELLA else 1.5), visible="legendonly" if s == "QLD" else True,
                             hovertemplate=STRATEGY_NAMES[s] + " %{y:,.0f}원<extra></extra>"))
S.date_hover(fig, U.dates, U.invested)
layout(fig, 420, "계좌 가치 vs 넣은 돈", "원화, 마지막 날은 세후. 범례를 누르면 선을 켜고 끕니다 (QLD는 기본으로 꺼 둠).")
S.won_axis(fig, [metrics.net_values(r) for r in res.values()] + [U.invested])
st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

fig = go.Figure()
for s in strategies:
    r = res[s]
    ratio = metrics.net_values(r) / np.where(r.invested > 0, r.invested, np.nan)
    fig.add_trace(go.Scatter(x=r.dates, y=ratio, name=STRATEGY_NAMES[s],
                             line=dict(color=COLORS[s], width=3 if s == UMBRELLA else 1.5), visible="legendonly" if s == "QLD" else True,
                             hovertemplate=STRATEGY_NAMES[s] + " %{y:.0%}<extra></extra>"))
fig.add_hline(y=1, line=dict(color=S.LOSS, width=1, dash="dash"))
fig.add_trace(go.Scatter(x=[SU["low_date"]], y=[SU["low"]], mode="markers+text", name="☂️ 최하방",
                         marker=dict(size=11, color=COLORS[UMBRELLA], symbol="diamond", line=dict(width=1.5, color="white")),
                         text=[f"최하방 {SU['low']:.0%}"], textposition="bottom center", showlegend=False))
S.date_hover(fig, U.dates, metrics.net_values(U) / np.where(U.invested > 0, U.invested, np.nan))
layout(fig, 360, "계좌 ÷ 넣은 돈", "빨간 점선 = 넣은 돈 100%, ◆ = 우산의 최하방")
fig.update_yaxes(tickformat=".0%")
st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

T = st.tabs(["📅 연도별", "☂️ 피신 기록", "☀️ 보유 구간", "📈 QQQ와 신호", "💱 환율 효과", "🍀 운이 좋았나", "🔀 청산일 바꿔 보기", "💾 내보내기"])

with T[0]:
    # ── 출력 2: 연도별 ───────────────────────────────
    yu = metrics.yearly(U)
    show = yu.copy()
    for c in ["연초 평가액", "넣은 돈", "연말 평가액", "낸 세금"]:
        show[c] = show[c].map(won)
    show["수익률"] = yu["수익률"].map(lambda x: pct(x, True))
    show["피신한 날"] = yu["피신한 날"].map(lambda x: f"{x:.0%}")
    st.markdown("**☂️ 우산**")
    st.dataframe(show, hide_index=True, width="stretch")

    ytab = pd.DataFrame({"연도": sorted({y for s in strategies for y in res[s].dates.year})})
    for s in strategies:        # 졸업 B는 전략마다 끝나는 해가 달라서 연도로 맞춘다
        ys = metrics.yearly(res[s]).set_index("연도")["수익률"]
        ytab[STRATEGY_NAMES[s]] = ytab["연도"].map(ys)
    st.markdown("**그해 수익률 비교** (적립금 효과를 뺀 시간가중)")
    st.dataframe(ytab.style.format({c: "{:+.1%}" for c in ytab.columns if c != "연도"}), hide_index=True, width="stretch")
    fig = go.Figure()
    for s in strategies:
        fig.add_trace(go.Bar(x=ytab["연도"].astype(str), y=ytab[STRATEGY_NAMES[s]], name=STRATEGY_NAMES[s],
                             marker_color=COLORS[s], hovertemplate=STRATEGY_NAMES[s] + " %{y:+.1%}<extra></extra>"))
    layout(fig, 360, "연도별 수익률")
    fig.update_layout(barmode="group", hovermode="x unified")
    fig.update_yaxes(tickformat=".0%")
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG)


with T[1]:
    # ── 출력 3: 피신 기록 ────────────────────────────
    rt = metrics.refuge_records(m, a, b)
    if rt.empty:
        st.info("이 기간에는 피신이 없었습니다.")
    else:
        rs = metrics.refuge_summary(rt)
        c1, c2, c3 = st.columns(3)
        ui.metric(c1, "💚 보험금 (피신이 이득)", f"{rs['gain_n']}번 · {pct(rs['gain_total'], True)}",
                  f"기간 중간값 {rs['gain_median_days'] or 0:.0f}거래일")
        ui.metric(c2, "❤️ 보험료 (피신이 손해)", f"{rs['pay_n']}번 · {pct(rs['pay_total'], True)}",
                  f"기간 중간값 {rs['pay_median_days'] or 0:.0f}거래일")
        ui.metric(c3, "모든 피신 합친 효과", pct(rs["total"], True),
                  f"가장 큰 보험금 빼면 {pct(rs['total_without_best'], True)}")
        if rs.get("ongoing_n"):
            st.caption("기간 끝에 피신 중인 구간은 '진행 중'으로 표시하고 보험금·보험료 합계에서 뺍니다 (회색 막대).")
        if rs["best"] is not None:
            st.caption(f"가장 큰 보험금: {d(rs['best']['start'])} 피신 ({rs['best']['days']}거래일) {pct(rs['best']['effect'], True)}. "
                       "이 한 번이 없었다면 합친 효과는 위 값처럼 바뀝니다.")
        refuge_df = pd.DataFrame({
            "피신 시작": rt["start"].map(d) + rt["from_start"].map(lambda x: " (시작 시 피신 중)" if x else ""),
            "복귀일": [("진행 중" if o else d(e)) for o, e in zip(rt["ongoing"], rt["end"])],
            "거래일 수": rt["days"],
            "TQQQ 그대로였다면": rt["tqqq"].map(lambda x: pct(x, True)),
            "피난처 실제": rt["refuge"].map(lambda x: pct(x, True)),
            "QQQ": rt["qqq"].map(lambda x: pct(x, True)),
            "피신 효과": rt["effect"].map(lambda x: pct(x, True)),
            "판정": rt["verdict"] + rt["synthetic"].map(lambda x: " *가상" if x else ""),
        })
        st.dataframe(refuge_df, hide_index=True, width="stretch")
        fig = go.Figure(go.Bar(
            x=[f"{d(s)}" for s in rt["start"]], y=rt["effect"],
            marker_color=[GREY if o else (GAIN if e > 0 else LOSS) for e, o in zip(rt["effect"], rt["ongoing"])],
            marker_line_width=0,
            hovertext=[f"{d(r.start)} → {'진행 중' if r.ongoing else d(r.end)} ({r.days}거래일)<br>"
                       f"TQQQ {r.tqqq:+.1%} · 피난처 {r.refuge:+.1%}<br><b>{r.verdict} {r.effect:+.1%}</b>"
                       for r in rt.itertuples()], hoverinfo="text"))
        fig.add_hline(y=0, line=dict(color=GREY, width=1))
        layout(fig, 340, "피신 효과 (초록 = 보험금, 빨강 = 보험료)")
        fig.update_layout(hovermode="closest", showlegend=False)
        fig.update_xaxes(type="category")
        fig.update_yaxes(tickformat=".0%")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
        st.caption("피신 효과 = (1 + 피난처 수익률) ÷ (1 + TQQQ 수익률) − 1. 피신한 날 종가 → 복귀한 날 종가, 세전.")


with T[2]:
    # ── 출력 4: 수익 구간 ────────────────────────────
    seg = metrics.holding_segments(m, a, b)
    ws = metrics.whipsaws(m, a, b)
    if not seg.empty:
        best, worst = seg.loc[seg["ret"].idxmax()], seg.loc[seg["ret"].idxmin()]
        c1, c2, c3 = st.columns(3)
        ui.metric(c1, "가장 크게 번 구간", pct(best["ret"], True), f"{d(best['start'])}~{d(best['end'])}")
        ui.metric(c2, "가장 크게 잃은 구간", pct(worst["ret"], True), f"{d(worst['start'])}~{d(worst['end'])}")
        ui.metric(c3, "헛걸음", f"{ws}번", "교체 후 10거래일 안에 되돌아감")
        seg_df = pd.DataFrame({
            "시작": seg["start"].map(d), "종료": [("진행 중" if o else d(e)) for o, e in zip(seg["ongoing"], seg["end"])],
            "거래일": seg["days"], "구간 수익률": seg["ret"].map(lambda x: pct(x, True)),
        })
        st.dataframe(seg_df, hide_index=True, width="stretch")


with T[3]:
    # ── 출력 5: QQQ 차트 ─────────────────────────────
    sl = slice(a, b + 1)
    x = m.idx[sl]
    fig = go.Figure()
    S.date_hover(fig, x, m.qqq_adj.iloc[sl])
    fig.add_trace(go.Scatter(x=x, y=m.qqq_adj.iloc[sl], name="QQQ (배당조정)", line=dict(color=S.QQQ, width=1.6),
                             hovertemplate="QQQ %{y:$,.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=m.sma_fast.iloc[sl], name="50일선", line=dict(color=S.SMA50, width=2),
                             hovertemplate="50일선 %{y:$,.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=x, y=m.sma_slow.iloc[sl], name="200일선", line=dict(color=S.SMA200, width=2),
                             hovertemplate="200일선 %{y:$,.2f}<extra></extra>"))
    S.add_refuge(fig, [(r.start, r.end) for r in rt.itertuples()] if not rt.empty else [], row=None)
    on = m.sig_on[sl]
    swi = np.where(on[1:] != on[:-1])[0] + 1
    if len(swi):
        xs = x[swi]
        ys = m.qqq_adj.iloc[sl].iloc[swi]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="markers", name="교체일 (위 = ☀️ TQQQ로, 아래 = ☂️ 피신)",
                                 marker=dict(symbol=["triangle-up" if on[i] else "triangle-down" for i in swi], size=11,
                                             color=[S.SUN if on[i] else S.RAIN for i in swi],
                                             line=dict(width=1, color="white")),
                                 hovertemplate=["▲ ☀️ TQQQ로 교체<extra></extra>" if on[i] else "▼ ☂️ 피신으로 교체<extra></extra>"
                                                for i in swi]))
    layout(fig, 420, "QQQ와 이동평균", "배당조정 종가 기준. 남보라 배경 = ☂️ 피신 기간.")
    fig.update_yaxes(tickformat="$,.0f")
    st.plotly_chart(fig, width="stretch", config=PLOT_CFG)


with T[4]:
    # ── 출력 6: 환율 ─────────────────────────────────
    if p.fx_mode == "real" and not colab:
        pf = Params(**{**p.__dict__, "fx_mode": "fixed"})
        uf = engine.run(m, UMBRELLA, pf, pay, (a, b))
        eff = U.final_krw - uf.final_krw
        c1, c2, c3 = st.columns(3)
        ui.metric(c1, "환율이 최종 결과에 보탠 금액", won(eff), f"환율 고정이었다면 {won(uf.final_krw)}")
        ui.metric(c2, "시작 환율", f"{m.fx[a]:,.2f}원", d(m.idx[a]))
        ui.metric(c3, "끝 환율", f"{m.fx[b]:,.2f}원", f"{d(m.idx[b])} ({m.fx[b] / m.fx[a] - 1:+.1%})")
        fig = go.Figure()
        S.date_hover(fig, x, m.fx[sl])
        fig.add_trace(go.Scatter(x=x, y=m.fx[sl], name="USD/KRW", line=dict(color=S.FX, width=2),
                                 hovertemplate="USD/KRW %{y:,.2f}원<extra></extra>"))
        layout(fig, S.H_SMALL, "USD/KRW 환율", legend=False)
        fig.update_yaxes(tickformat=",.0f")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
    else:
        st.info("환율 효과는 '원화 (그날 환율로 환전)' 기준이고 검산 모드가 아닐 때만 계산합니다.")


with T[5]:
    # ── 출력 7: 이 시작일은 운이 좋았나 ───────────────
    inc_syn = st.toggle("가상 데이터 구간도 포함 (2000년~)", value=False, key="sim_scan_syn",
                        help="끄면 실제 상품 구간(2010-03~)의 시작 월만 씁니다.")


    @st.cache_data(show_spinner="가능한 모든 시작 월을 계산하는 중…", max_entries=30)
    def _scan(version, key, strategies, length_key, inc_syn, _p, _length):
        return scan.scan(_market(version), list(strategies), _p, _length, inc_syn)


    key = scan_key(p)
    if rule is None:
        sc = _scan(store.data_version(), key, tuple(strategies), str(length), inc_syn, p, length)
    else:
        sc = _scan_rule(store.data_version(), key, tuple(strategies), rule, th, inc_syn, p)
        st.caption(f"청산 규칙 '{exits.RULE_LABEL[rule.kind]}'을 모든 시작 월에 똑같이 적용했습니다.")
    if sc.empty:
        st.info("이 길이로 계산할 수 있는 시작 월이 없습니다.")
    else:
        du = sc[sc["strategy"] == UMBRELLA]["multiple"].to_numpy()
        pc, txt = scan.luck_text(du, U.multiple)
        if not inc_syn and m.idx[a] < pd.Timestamp(scan.REAL_FROM):
            st.warning("내 시작일은 실제 상품 구간(2010-03~)보다 앞이라 이 분포와 조건이 다릅니다. "
                       "위의 '가상 데이터 구간도 포함'을 켜고 비교하세요.")
        ui.metric(st, "내 시작일의 ☂️ 최종 배수", f"{U.multiple:.2f}배", f"{len(du)}개 시작 월 중 {txt}")
        fig = go.Figure(go.Histogram(x=du, nbinsx=30, marker_color=COLORS[UMBRELLA], marker_line_width=0,
                                     hovertemplate="%{x} : %{y}개<extra></extra>"))
        fig.add_vline(x=U.multiple, line=dict(color="#d03b3b", width=2), annotation_text=f"내 시작일 {U.multiple:.2f}배")
        fig.add_vline(x=1, line=dict(color=GREY, width=1, dash="dot"), annotation_text="원금", annotation_position="bottom right")
        layout(fig, 320, f"☂️ 최종 배수 분포 ({len(du)}개 시작 월, {sc['start'].min():%Y-%m} ~ {sc['start'].max():%Y-%m})")
        fig.update_layout(showlegend=False, hovermode="closest", bargap=0.05)
        fig.update_xaxes(title_text="최종 배수")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)
        stt = scan.stats(sc).loc[[s for s in strategies if s in set(sc["strategy"])]]
        stt.index = [STRATEGY_NAMES[s] for s in stt.index]
        st.dataframe(stt.style.format({"평균": "{:.2f}배", "중간값": "{:.2f}배", "운 나쁜 10%": "{:.2f}배",
                                       "최악": "{:.2f}배", "원금손실 확률": "{:.0%}"}), width="stretch")
        st.caption("같은 기간 길이·같은 금액·같은 설정으로 각 달 첫 거래일에 시작했다면. 결과는 저장해 두고 다시 쓰입니다.")


with T[6]:
    # ── 출력 8: 시작일 고정 + 청산일만 바꿔 보기 ─────────
    c1, c2 = st.columns(2)
    vn = c1.number_input("최소 N년", 1, 20, int(rule.min_years) if rule is not None and rule.kind != "target" else 5,
                         key="sim_vn")
    vm = c2.number_input("최대 M년", 1, 30, int(rule.max_years) if rule is not None else 15, key="sim_vm")
    vt, _ = exits._offset(m, a, vn)
    vc, v_over = exits._offset(m, a, max(vm, vn))
    if vt >= vc:
        st.info(f"시작 후 {vn}년이 데이터보다 뒤라서 계산할 청산일이 없습니다. 시작일을 앞당기거나 N을 줄이세요.")
    else:
        pl = Params(**{**p.__dict__, "liquidate": True})
        curves = {}
        for s in strategies:
            rr = engine.run(m, s, pl, pay, (a, vc))
            k = np.arange(vt - a, vc - a + 1)
            curves[s] = rr.exit_krw[k] / rr.invested[k]
        xd = m.idx[vt:vc + 1]
        cl = cls_arr[vt:vc + 1]
        fig = go.Figure()
        # 🟢/🔴 구간 배경
        run_start = 0
        for i in range(1, len(cl) + 1):
            if i == len(cl) or cl[i] != cl[run_start]:
                if cl[run_start] in CLS_COLOR:
                    fig.add_vrect(x0=xd[run_start], x1=xd[i - 1] + pd.Timedelta(days=1),
                                  fillcolor=CLS_COLOR[cl[run_start]], line_width=0, layer="below")
                run_start = i
        for s in strategies:
            fig.add_trace(go.Scatter(x=xd, y=curves[s], name=STRATEGY_NAMES[s],
                                     line=dict(color=COLORS[s], width=2.5 if s == UMBRELLA else 1.3), visible="legendonly" if s == "QLD" else True,
                                     hovertemplate=STRATEGY_NAMES[s] + " %{y:.2f}배<extra></extra>"))
        fig.add_hline(y=1, line=dict(color=GREY, width=1, dash="dot"))
        layout(fig, 420, f"{d(m.idx[a])} 시작 · 그날 팔았다면 세후 배수 (초록 배경 = 🟢 상승장, 빨강 = 🔴 하락장)")
        st.plotly_chart(fig, width="stretch", config=PLOT_CFG)

        rows = []
        for s in strategies:
            y = curves[s]
            row = {"전략": STRATEGY_NAMES[s]}
            for c in (exits.GREEN, exits.RED, exits.GRAY):
                mask = cl == c
                row[exits.CLASS_LABEL[c] + " 평균"] = f"{y[mask].mean():.2f}배" if mask.any() else "–"
            row["전체 평균"] = f"{y.mean():.2f}배"
            row["최악"] = f"{y.min():.2f}배 ({d(xd[int(y.argmin())])})"
            row["최고"] = f"{y.max():.2f}배 ({d(xd[int(y.argmax())])})"
            rows.append(row)
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        mat = np.vstack([curves[s] for s in strategies])
        u = curves[UMBRELLA]
        not_worst = float(np.mean(u > mat.min(axis=0) - 1e-12)) if len(strategies) > 1 else 1.0
        worst_share = float(np.mean(np.isclose(u, mat.min(axis=0))))
        lines = []
        if len(strategies) > 1:
            if worst_share == 0:
                lines.append(f"✅ 이 시작일이면 {vn}~{vm}년 사이 **언제 팔아도 우산이 최악을 면했습니다** ({len(u)}거래일 모두).")
            else:
                lines.append(f"이 시작일이면 {len(u)}거래일 중 **{1 - worst_share:.0%}**에서 우산이 최악을 면했고, "
                             f"{worst_share:.0%}에서는 네 전략 중 가장 나빴습니다.")
        if "TQQQ" in curves:
            t = curves["TQQQ"]
            lines.append(f"우산이 TQQQ 그냥 적립보다 나았던 날: 전체 {np.mean(u > t):.0%}")
            for c in (exits.RED, exits.GREEN):
                mask = cl == c
                if mask.any():
                    lines.append(f"· {exits.CLASS_LABEL[c]}에 팔았다면: 우산이 TQQQ보다 나았던 날 {np.mean(u[mask] > t[mask]):.0%} "
                                 f"({mask.sum()}거래일)")
        if v_over:
            lines.append(f"(최대 {vm}년이 데이터보다 뒤라서 {d(m.idx[vc])}까지만 계산)")
        st.markdown("  \n".join(lines))


with T[7]:
    # ── 출력 9: 내보내기 ─────────────────────────────
    tag = f"{d(m.idx[a])}_{d(m.idx[b])}"
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button("요약 CSV", summary_df.to_csv(index=False).encode("utf-8-sig"), f"요약_{tag}.csv", "text/csv",
                       width="stretch")
    yall = pd.concat([metrics.yearly(res[s]).assign(전략=STRATEGY_NAMES[s]) for s in strategies])
    c2.download_button("연도별 CSV", yall.to_csv(index=False).encode("utf-8-sig"), f"연도별_{tag}.csv", "text/csv",
                       width="stretch")
    c3.download_button("피신 기록 CSV", (rt.to_csv(index=False) if not rt.empty else "").encode("utf-8-sig"),
                       f"피신기록_{tag}.csv", "text/csv", width="stretch")
    c4.download_button("매매 내역 CSV", pd.DataFrame(U.trades).to_csv(index=False).encode("utf-8-sig"),
                       f"매매내역_{tag}.csv", "text/csv", width="stretch")

    lines = [
        f"[우산 T6 시뮬레이션] {d(m.idx[a])} ~ {d(m.idx[b])} ({b - a}거래일)",
        f"조건: 처음 {won(p.initial_krw)} + 매월 {p.pay_day}일 {won(p.monthly_krw)}, "
        f"{'원화(환율 반영)' if p.fx_mode == 'real' else '달러 기준'}, "
        f"{'마지막 날 전부 매도 세후' if p.liquidate else '보유 유지 세전'}"
        f"{', 검산 모드(코랩 가정)' if colab else ''}",
        f"비용: 교체 편도 {sw}% · 적립 매수 {buy}% · 양도세 {cap}% (공제 {won(ded)}) · 배당·이자세 {divt}%",
    ]
    if any(r.synthetic for r in res.values()):
        lines.append("※ 가상 데이터 포함 (실제보다 연 1~1.5%p 후할 수 있음)")
    for s in strategies:
        x = summ[s]
        lines.append(f"- {STRATEGY_NAMES[s]}: {won(x['final_krw'])} ({x['multiple']:.2f}배, 연 {pct(x['irr'], True)}), "
                     f"최하방 {x['low']:.0%}, 최대 낙폭 {x['mdd']:.1%}, 세금 {won(x['cap_tax'] + x['div_tax'])}")
    if not rt.empty:
        lines.append(f"피신 {rs['n']}번: 보험금 {rs['gain_n']}번 {pct(rs['gain_total'], True)}, "
                     f"보험료 {rs['pay_n']}번 {pct(rs['pay_total'], True)}, 헛걸음 {ws}번")
    if not sc.empty:
        lines.append(f"이 시작일: {len(du)}개 시작 월 중 {txt}")
    st.code("\n".join(lines), language=None, wrap_lines=True)
    st.caption("오른쪽 위 복사 버튼으로 한 번에 복사할 수 있습니다.")


ui.footer()
