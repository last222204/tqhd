"""🎲 청산 시나리오: 시작일과 보유 기간을 무작위로 뽑아, 언제 파느냐에 따라 누가 이기나."""
import hashlib
import pickle
import random

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from t6 import store, ui
from t6 import style as ST
from t6.config import DATA_DIR
from t6.sim import data, exits, lab
from t6.sim.engine import STRATEGY_NAMES, UMBRELLA, Costs, Params, Taxes

S = [UMBRELLA, "QQQ", "QLD", "TQQQ"]
COLORS = ST.STRATEGY
CLS_COL = {exits.GREEN: ST.GAIN, exits.RED: ST.LOSS, exits.GRAY: ST.NEUTRAL}
CLS_NAME = {exits.GREEN: "상승장 청산", exits.RED: "하락장 청산", exits.GRAY: "보통 청산"}
CACHE_DIR = DATA_DIR / "cache"


@st.cache_resource(show_spinner="시세를 정리하는 중…")
def _market(version: int):
    return data.build()


@st.cache_resource
def _results() -> dict:
    """계산 결과 보관함 (같은 조건이면 다시 계산하지 않음). 파일에도 저장해서 서버를 다시 켜도 바로 나온다."""
    return {}


def _disk(key) -> "Path":
    return CACHE_DIR / f"lab_{hashlib.sha1(repr(key).encode()).hexdigest()[:16]}.pkl"


def name(s):
    return STRATEGY_NAMES[s]


def chart(fig, h, title, desc=None, legend=True):
    ui.chart_title(title, desc)
    ST.style(fig, height=h, legend=legend, dates=False, unified=False)


ui.page_title("🎲 청산 시나리오", "시작일과 보유 기간을 무작위로 뽑아서 네 전략을 같은 시작일·같은 청산일로 계산합니다. "
              "청산하는 날의 시장 상태(🟢 상승장 / 🔴 하락장 / ⚪ 보통)에 따라 누가 이기는지 봅니다.")
if store.last_price_date("QQQ") is None:
    st.info("시세가 아직 없습니다. 위의 '🔄 시세 새로고침'을 눌러 시세를 받은 뒤 다시 열어 주세요.")
    ui.footer()
    st.stop()
m = _market(store.data_version())

if "lab_seed" not in st.session_state:
    st.session_state["lab_seed"] = 0

with st.form("lab_form"):
    c1, c2, c3 = st.columns(3)
    inc_syn = c1.toggle("가상 데이터 구간도 포함 (2000년~)", key="lab_syn",
                        help="끄면 실제 상품 구간(2010-03~)에서만 시작일을 뽑습니다.")
    hold = c2.slider("보유 기간 범위 (년)", 1.0, 20.0, (3.0, 10.0), 0.5, key="lab_hold")
    n = c3.number_input("시뮬레이션 횟수", 100, 20_000, 2_000, 500, key="lab_n")
    c1, c2, c3, c4 = st.columns(4)
    initial = c1.number_input("처음 넣는 돈 (원)", 0, 10_000_000_000, 10_000_000, 1_000_000, key="lab_init")
    monthly = c2.number_input("매월 적립금 (원)", 0, 1_000_000_000, 1_000_000, 100_000, key="lab_month")
    pay_day = c3.number_input("적립일", 1, 28, 17, key="lab_payday")
    seed = c4.number_input("난수 시드", 0, 999_999, key="lab_seed", help="같은 시드면 같은 결과가 나옵니다.")
    with st.expander("고급 설정 (통화·검산 모드·분류 기준·시작일 범위)"):
        a1, a2 = st.columns(2)
        cur = a1.radio("통화 기준", ["원화 (환율 반영)", "달러 기준 (환율 고정)"], key="lab_cur")
        colab = a2.toggle("검산 모드 (코랩 가정)", key="lab_colab")
        b1, b2 = st.columns(2)
        g_dd = b1.number_input("🟢 상승장: 전고점 대비 몇 % 이내 (그리고 200일선 위)", -50.0, 0.0, -5.0, 1.0, key="lab_gdd")
        r_dd = b2.number_input("🔴 하락장: 전고점 대비 몇 % 이하", -90.0, 0.0, -20.0, 1.0, key="lab_rdd")
        lo_i = lab.first_start(m, True)
        rng_years = st.slider("시작일 범위 (연도)", int(m.idx[lo_i].year), int(m.idx[-1].year),
                              (int(m.idx[lo_i].year), int(m.idx[-1].year)), key="lab_years")
    f1, f2 = st.columns([3, 1])
    f1.form_submit_button("계산하기", type="primary", width="stretch")
    f2.form_submit_button("🎲 다시 굴리기 (새 시드)", width="stretch",
                          on_click=lambda: st.session_state.update(lab_seed=random.randint(1, 999_999)))

p = Params(start=m.idx[0], end=m.idx[1], initial_krw=float(initial), monthly_krw=float(monthly),
           pay_day=int(pay_day), fx_mode="real" if cur.startswith("원화") else "fixed", colab=colab,
           costs=Costs(), taxes=Taxes())
th = exits.Thresholds(g_dd / 100, r_dd / 100)
key = (store.data_version(), int(n), int(seed), hold, inc_syn, rng_years, initial, monthly, pay_day, cur, colab,
       g_dd, r_dd)
box = _results()
if key not in box:
    f = _disk(key)
    try:
        box[key] = pickle.loads(f.read_bytes()) if f.exists() else None
    except Exception:  # 깨진 저장 파일은 무시하고 다시 계산
        box[key] = None
    if box[key] is None:
        try:
            d = lab.draw(m, int(n), int(seed), hold[0], hold[1], inc_syn,
                         f"{rng_years[0]}-01-01", f"{rng_years[1]}-12-31")
        except ValueError as e:
            del box[key]
            st.error(str(e))
            ui.footer()
            st.stop()
        bar = st.progress(0.0, text=f"{int(n):,}개 시나리오 계산 중…")
        df = lab.simulate(m, S, p, d, th,
                          progress=lambda fr: bar.progress(fr, text=f"{int(n):,}개 시나리오 계산 중… {fr:.0%}"))
        bar.empty()
        box[key] = (df, d.rejected)
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            for old in sorted(CACHE_DIR.glob("lab_*.pkl"), key=lambda x: x.stat().st_mtime)[:-30]:
                old.unlink()          # 저장 파일은 최근 30개만
            f.write_bytes(pickle.dumps(box[key]))
        except OSError:
            pass
    if len(box) > 20:             # 메모리에는 최근 것만
        keep = box[key]
        box.clear()
        box[key] = keep
df, rejected = box[key]
nd = df["draw"].nunique()
st.caption(f"시나리오 {nd:,}개 · 시드 {seed} · 보유 {hold[0]:g}~{hold[1]:g}년 · 시작 {df['start'].min():%Y-%m} ~ "
           f"{df['start'].max():%Y-%m} · 청산일이 데이터 끝을 넘어서 다시 뽑은 횟수 {rejected:,}번"
           f"{' · 검산 모드' if colab else ''}")
if df["synthetic"].any():
    st.warning("⚠️ 가상 데이터 구간이 섞여 있습니다. 실제보다 연 1~1.5%p 후할 수 있음.")

ct = lab.class_table(df, S)
CL = {**exits.CLASS_LABEL, "all": "전체"}

# ── 분류별 결과 ──────────────────────────────────
ui.section("청산 분류별 결과", "청산하는 날 QQQ가 어디 있었느냐로 나눈 결과. 순위 (평균) = 평균 배수가 높은 순, "
           "순위 (최악) = 가장 나빴던 경우가 덜 나쁜 순.")
mix = df.drop_duplicates("draw")["cls"].value_counts(normalize=True)
h1, h2, h3 = st.columns(3)
for col, c in zip((h1, h2, h3), (exits.GREEN, exits.RED, exits.GRAY)):
    ui.metric(col, exits.CLASS_LABEL[c], ST.ratio(mix.get(c, 0)), note=f"{int(round(mix.get(c, 0) * nd)):,}번")

tab = pd.DataFrame({
    "청산 분류": [CL[c] if i == 0 or ct["cls"].iloc[i - 1] != c else "" for i, c in enumerate(ct["cls"])],
    "횟수 (비율)": [f"{n_:,} ({sh:.0%})" if i == 0 or ct["cls"].iloc[i - 1] != c else ""
                 for i, (c, n_, sh) in enumerate(zip(ct["cls"], ct["n"], ct["share"]))],
    "전략": ct["strategy"].map(name),
    "평균 배수": ct["mean"], "중간값": ct["median"], "운 나쁜 10%": ct["p10"], "최악": ct["min"],
    "연환산 평균": ct["irr_mean"], "원금손실 확률": ct["loss"],
    "순위 (평균)": ct["rank_mean"], "순위 (최악)": ct["rank_min"],
})
st.dataframe(tab.style.format({"평균 배수": "{:.2f}배", "중간값": "{:.2f}배", "운 나쁜 10%": "{:.2f}배",
                               "최악": "{:.2f}배", "연환산 평균": "{:+.1%}", "원금손실 확률": "{:.1%}"}),
             hide_index=True, width="stretch", height=(len(tab) + 1) * 35 + 3,
             column_config={"청산 분류": st.column_config.TextColumn(width="medium"),
                            "횟수 (비율)": st.column_config.TextColumn(width="small")})

# ── 한눈에 보는 비교 ─────────────────────────────
ui.section("한눈에 보는 비교")
g = ct.set_index(["cls", "strategy"])
lines = []
for c in (exits.GREEN, exits.RED):
    if (c, UMBRELLA) not in g.index:
        continue
    sub = ct[ct["cls"] == c]
    best = sub.loc[sub["mean"].idxmax()]
    safe = sub.loc[sub["min"].idxmax()]
    head = {exits.GREEN: "🟢 상승장에서 청산하면", exits.RED: "🔴 하락장에서 청산하면"}[c]
    lines.append(f"**{head}** — 평균 1위: **{name(best['strategy'])}** {best['mean']:.2f}배 · "
                 f"최악이 가장 덜 나쁜 전략: **{name(safe['strategy'])}** {safe['min']:.2f}배 "
                 f"(☂️ 우산은 평균 {g.loc[(c, UMBRELLA), 'mean']:.2f}배, 최악 {g.loc[(c, UMBRELLA), 'min']:.2f}배)")
st.markdown("  \n".join(lines) if lines else "분류별 표본이 부족합니다.")

if all((c, s) in g.index for c in (exits.GREEN, exits.RED) for s in S):
    ratio = pd.Series({s: g.loc[(exits.GREEN, s), "mean"] / g.loc[(exits.RED, s), "mean"] for s in S})
    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**🟢 상승장 평균 ÷ 🔴 하락장 평균** (클수록 '언제 파느냐'에 운명이 걸린 전략)")
        rt = pd.DataFrame({"전략": [name(s) for s in ratio.index], "비율": ratio.values}).sort_values("비율", ascending=False)
        st.dataframe(rt.style.format({"비율": "{:.2f}"}), hide_index=True, width="stretch")
        top = ratio.idxmax()
        expected = top == "TQQQ" and ratio[UMBRELLA] < ratio["TQQQ"]
        st.markdown(("✅ 예상대로 **TQQQ 그냥 적립이 가장 크고, 우산은 그보다 작습니다** "
                     f"({ratio['TQQQ']:.2f} vs {ratio[UMBRELLA]:.2f}).") if expected else
                    (f"⚠️ 예상과 다릅니다: 가장 큰 건 **{name(top)}** ({ratio[top]:.2f}), "
                     f"우산 {ratio[UMBRELLA]:.2f}, TQQQ {ratio['TQQQ']:.2f}."))
    with c2:
        red_win = lab.head_to_head(df, UMBRELLA, "TQQQ", exits.RED)
        green_win = lab.head_to_head(df, "TQQQ", UMBRELLA, exits.GREEN)
        ui.metric(st, "🔴 하락장 청산에서 우산이 TQQQ보다 나았던 비율", ST.ratio(red_win))
        ui.metric(st, "🟢 상승장 청산에서 TQQQ가 우산보다 나았던 비율", ST.ratio(green_win))
        st.caption(f"전체로는 우산이 TQQQ보다 나았던 비율 {lab.head_to_head(df, UMBRELLA, 'TQQQ', None):.0%}")

# ── 차트 ─────────────────────────────────────────
ui.section("차트")
lo, hi = float(df["multiple"].min()), float(df["multiple"].max())
fig = go.Figure()
for c in (exits.GREEN, exits.GRAY, exits.RED):
    sub = df[df["cls"] == c]
    if sub.empty:
        continue
    fig.add_trace(go.Box(x=sub["strategy"].map(name), y=sub["multiple"], name=CLS_NAME[c],
                         marker_color=CLS_COL[c], boxpoints=False, offsetgroup=c,
                         hovertemplate=CLS_NAME[c] + " %{y:.2f}배<extra></extra>"))
fig.add_hline(y=1, line=dict(color=ST.INVESTED, width=1, dash="dot"))
chart(fig, ST.H_BIG, "전략별 최종 배수 분포", "상자 = 가운데 50%, 선 = 가장 낮고 높은 값. 초록 = 상승장 청산, 회색 = 보통, 빨강 = 하락장. 점선 = 원금.")
fig.update_layout(boxmode="group")
ST.log_mult_axis(fig, lo, hi)
ui.plot(fig)

samp = df[df["draw"].isin(df["draw"].drop_duplicates().sample(min(nd, 1500), random_state=0))]
fig = go.Figure()
for s in S:
    sub = samp[samp["strategy"] == s]
    fig.add_trace(go.Scattergl(
        x=sub["dd"], y=sub["multiple"], mode="markers", name=name(s),
        visible="legendonly" if s == "QLD" else True,
        marker=dict(color=COLORS[s], size=5, opacity=0.45),
        hovertemplate=name(s) + " %{y:.2f}배 · 전고점 대비 %{x:.1%}<extra></extra>"))
fig.add_vline(x=th.green_dd, line=dict(color=ST.GAIN, width=1, dash="dash"))
fig.add_vline(x=th.red_dd, line=dict(color=ST.LOSS, width=1, dash="dash"))
fig.add_hline(y=1, line=dict(color=ST.INVESTED, width=1, dash="dot"))
chart(fig, ST.H_BIG, "청산일 QQQ 위치 vs 최종 배수",
      "가로 = 청산하는 날 QQQ가 전고점에서 얼마나 내려와 있었나 (오른쪽 = 전고점 근처). 초록·빨강 점선 = 분류 기준."
      + (" 점이 많아서 1,500개 시나리오만 그렸습니다 (표·통계는 전체 사용)." if nd > 1500 else ""))
fig.update_xaxes(tickformat=".0%")
ST.log_mult_axis(fig, lo, hi)
ui.plot(fig)

red = df[df["cls"] == exits.RED].copy()
if not red.empty:
    red["보유"] = np.floor(red["years"]).astype(int)
    pv = red.groupby(["보유", "strategy"])["multiple"].mean().unstack()
    cnt = red.drop_duplicates("draw").groupby("보유").size()
    fig = go.Figure()
    for s in S:
        if s in pv:
            fig.add_trace(go.Bar(x=[f"{y}년대" for y in pv.index], y=pv[s], name=name(s), marker_color=COLORS[s],
                                 hovertemplate=name(s) + " %{y:.2f}배<extra></extra>"))
    chart(fig, 360, "보유 기간별 🔴 하락장 청산 평균 배수",
          "표본 수: " + ", ".join(f"{y}년대 {c}번" for y, c in cnt.items()))
    fig.update_layout(barmode="group", hovermode="x unified")
    fig.update_yaxes(ticksuffix="배")
    ui.plot(fig)

# ── 주사위 한 번 굴리기 ──────────────────────────
ui.section("주사위 한 번 굴리기", "뽑힌 시나리오 하나를 시뮬레이터 상세 화면(요약, 피신 기록, 차트)으로 엽니다.")


def open_one(cls_filter):
    pool = df.drop_duplicates("draw")
    if cls_filter:
        pool = pool[pool["cls"] == cls_filter]
    if pool.empty:
        st.warning("그런 시나리오가 없습니다.")
        return
    row = pool.sample(1, random_state=random.randint(0, 10**9)).iloc[0]
    ss = st.session_state
    ss["sim_start"] = row["start"].date()
    ss["sim_rule"] = "종료일 직접"
    ss["sim_end"] = row["exit"].date()
    ss["sim_init"], ss["sim_month"], ss["sim_payday"] = int(initial), int(monthly), int(pay_day)
    ss["sim_cur"] = ("원화 (그날 환율로 환전, 환율 효과 포함)" if cur.startswith("원화") else "달러 기준 (환율 고정)")
    ss["sim_colab"] = bool(colab)
    ss["sim_gdd"], ss["sim_rdd"] = float(g_dd), float(r_dd)
    ss["sim_avg"] = False
    st.switch_page("views/simulator.py")


b1, b2, b3 = st.columns(3)
if b1.button("🎲 아무거나 한 번", width="stretch"):
    open_one(None)
if b2.button("🔴 하락장 청산만 뽑기", width="stretch"):
    open_one(exits.RED)
if b3.button("🟢 상승장 청산만 뽑기", width="stretch"):
    open_one(exits.GREEN)

st.download_button("시나리오 전체 CSV", df.assign(전략=df["strategy"].map(name), 분류=df["cls"].map(exits.CLASS_LABEL))
                   .to_csv(index=False).encode("utf-8-sig"), f"청산시나리오_시드{seed}.csv", "text/csv")
ui.footer()
