"""🎲 월요일 아침 QQQ·TQQQ 출발 예상가 (재미용) — 어떤 숫자도 T6 신호를 바꾸지 않는다."""
from datetime import datetime, timezone

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from t6 import gap, gap_data, store, today, ui
from t6 import market_time as mt
from t6 import style as S
from t6.config import label

LCOL = {gap.UP: S.GAIN, gap.DOWN: S.LOSS, gap.FLAT_L: S.NEUTRAL}
LICON = {gap.UP: "▲", gap.DOWN: "▼", gap.FLAT_L: "■"}

ui.page_title("🎲 주말 갭 점치기", "금요일 정규장·애프터마켓 종가와 주말 나스닥 관련 시세로 월요일 아침 QQQ·TQQQ 출발가를 점칩니다.")
st.markdown("<div class='t6-border'>🎲 재미용입니다. T6 신호는 금요일 종가로 이미 정해졌고, "
            "이 페이지의 어떤 숫자도 신호를 바꾸지 않습니다.</div>", unsafe_allow_html=True)


@st.cache_data(ttl=300, show_spinner="나스닥 시세를 받는 중…")
def _snap(bucket: int):
    return gap_data.snapshot()


@st.cache_data(ttl=12 * 3600, show_spinner="과거 주말을 계산하는 중… (처음 한 번만)")
def _hist(version: int, day: str):
    return gap_data.history(store.load_prices("QQQ"))


now = datetime.now(timezone.utc)
sn = _snap(int(now.timestamp() // 300))
t, est = sn.t, sn.est
f = mt.fmt_kst
q_open, t_open = gap.open_prices(est, sn.qqq.get("close"), sn.tqqq.get("close"))
bt = _hist(store.data_version(), now.strftime("%Y-%m-%d"))
acc = gap.accuracy(bt, est.method) if est.method in ("ah", "perp", "ah_perp") else {"mae": None, "n": 0}

if t.us_monday_holiday:
    st.info(f"이번 주 월요일은 **미국 휴장**입니다. {mt.fmt_date(t.us_next)} 출발가를 점칩니다.")
day_name = "월요일" if t.us_next.weekday() == 0 else mt.fmt_date(t.us_next)

# ── 메인: 출발 예상가 ────────────────────────────
ui.section(f"🔮 {day_name} 아침 출발 예상가",
           f"{mt.fmt_date(t.us_next)} 미국 정규장 시작 {f(t.us_open)} (한국 시간) 첫 가격 예상. "
           f"쓴 방법: {gap.METHODS[est.method]}")


def card(col, name, close, open_est, gap_pct, ah, mae, lev=1):
    lab = gap.label_of(gap_pct * lev) if gap_pct is not None else None
    colr = LCOL.get(lab, S.NEUTRAL)
    rng = ""
    if mae is not None and open_est is not None and close is not None:
        lo, hi = close * (1 + lev * (gap_pct - mae)), close * (1 + lev * (gap_pct + mae))
        rng = f"<br><span class='t6-sub'>과거 같은 방법 평균 오차 ±{lev * mae:.1%} → {S.usd(lo)} ~ {S.usd(hi)}</span>"
    col.markdown(
        f"<div class='t6-card' style='border:2px solid {colr};background:{colr}1f'>"
        f"<div class='t6-sub'>{name} 출발 예상</div>"
        f"<div style='font-size:clamp(2rem,9vw,3rem);font-weight:800;line-height:1.15'>{S.usd(open_est)}</div>"
        f"<div style='font-size:1.15rem;font-weight:700;color:{colr}'>{LICON.get(lab, '')} "
        f"{S.pct(lev * gap_pct) if gap_pct is not None else '–'} · {lab or '–'}</div>"
        f"<div class='t6-sub' style='margin-top:6px'>금요일 종가 {S.usd(close)} · 애프터마켓 마지막 {S.usd(ah)}</div>{rng}</div>",
        unsafe_allow_html=True)


c1, c2 = st.columns(2)
card(c1, "QQQ", sn.qqq.get("close"), q_open, est.gap, sn.qqq.get("ah"), acc.get("mae"))
card(c2, "TQQQ", sn.tqqq.get("close"), t_open, est.gap, sn.tqqq.get("ah"), acc.get("mae"), lev=gap.LEVERAGE)

sg = "+" if est.gap >= 0 else "−"
steps = "".join(f"<li>{name}: <b>{v:+.2%}</b></li>" for name, v in est.steps) or "<li>재료가 없어 금요일 종가 그대로</li>"
st.markdown(
    f"<div class='t6-card' style='padding:12px 18px'><b>어떻게 계산했나</b>"
    f"<ol style='margin:6px 0 4px 1.1rem;padding:0'>{steps}</ol>"
    f"<span class='t6-sub'>→ 예상 갭 <b>{est.gap:+.2%}</b> · QQQ = 금요일 종가 × (1 {sg} {abs(est.gap):.4f}) · "
    f"TQQQ = 금요일 종가 × (1 {sg} 3 × {abs(est.gap):.4f}). "
    f"우선순위: 나스닥 선물(열리면) → 애프터마켓 + 주말 무기한 선물 → 무기한 선물만 → 애프터마켓만.</span></div>",
    unsafe_allow_html=True)

# T6 신호와 할 일 (점치기와 헷갈리지 않게)
sf = ui.signals("adj_close")
if not sf["signal"].dropna().empty:
    v = today.build(sf, ui.signals("close"), ui.now_utc())
    rain = v.signal == "SGOV"
    todo = (f"🔁 <b>{label(v.prev_signal)} → {label(v.signal)} 교체</b> · " + v.when[-1].replace("~", "&#126;")) if v.switched else \
        f"교체 없음 · <b>{label(v.signal)}</b> 그대로 보유"
    st.markdown(
        f"<div class='t6-card {'t6-rain' if rain else 't6-sun'}' style='padding:10px 16px'>"
        f"<b>{'☂️' if rain else '☀️'} T6 신호: {label(v.signal)}</b> <span class='t6-sub'>({mt.fmt_date(v.as_of)} 종가 판정, "
        f"위 예상가와 무관)</span><br>이번 주 할 일: {todo}</div>", unsafe_allow_html=True)


def p(x):
    return S.pct(x) if x is not None else "데이터 없음"


def usd(x):
    return S.usd(x) if x is not None else "데이터 없음"


# ── 재료 ─────────────────────────────────────────
ui.section("재료", f"금요일 미국 정규장 마감 {f(t.us_close)} · 애프터마켓 끝 {f(t.ah_end)} · "
           f"나스닥 선물 개장 {f(t.fut_open)} (모두 한국 시간)")
rows = [
    ("QQQ 정규장 종가", usd(sn.qqq.get("close")), "", ""),
    ("QQQ 애프터마켓 마지막", usd(sn.qqq.get("ah")), p(sn.qqq.get("ah_chg")), "종가 대비"),
    ("TQQQ 정규장 종가", usd(sn.tqqq.get("close")), "", ""),
    ("TQQQ 애프터마켓 마지막", usd(sn.tqqq.get("ah")), p(sn.tqqq.get("ah_chg")), "종가 대비"),
]
for name, d_ in sn.perps.items():
    mark = " ← 예상에 씀" if name == sn.perp_used else ""
    rows.append((f"나스닥100 무기한 선물 ({name})", f"{d_['now']:,.0f}" if d_["now"] else "데이터 없음",
                 f"{p(d_['chg_close'])} / 애프터마켓 뒤 {p(d_['chg_ah'])}", f"⚠️ {d_['note']}{mark}"))
if sn.nq["opened"]:
    rows.append(("나스닥 선물 (NQ=F)", f"{sn.nq['now']:,.2f}" if sn.nq["now"] else "데이터 없음", p(sn.nq["chg"]),
                 "금요일 미국 마감 시각 대비 ← 열렸으면 최우선"))
else:
    left = t.fut_open - now
    h, m_ = divmod(int(left.total_seconds() // 60), 60)
    rows.append(("나스닥 선물 (NQ=F)", f"아직 안 열림 · {f(t.fut_open)} 개장", f"남은 {h // 24}일 {h % 24}시간 {m_}분",
                 "열리면 이것만으로 예상"))
st.dataframe(pd.DataFrame(rows, columns=["재료", "가격", "변화", "메모"]), hide_index=True, width="stretch")
st.caption("무기한 선물 변화 = 금요일 미국 마감 대비 / 애프터마켓 끝(20:00 ET) 대비. 코인 거래소의 주말 거래는 얇아서 크게 튀기도 합니다.")

# ── 과거엔 얼마나 맞았나 ─────────────────────────
ui.section("과거엔 얼마나 맞았나",
           "세 가지 예측을 같은 주말들로 나란히 비교. 무기한 선물은 월요일 08:00 KST(여름 07:00, 나스닥 선물 개장) "
           "직전 값으로 고정하고 그 이후 가격은 쓰지 않았습니다.")
res, common = gap.compare(bt)


def ci_txt(ci):
    return f"{ci[0]:.0%} ~ {ci[1]:.0%}" if ci else "–"


if not res or len(common) < 3:
    st.info("무기한 선물 과거 자료가 부족해서 아직 비교할 수 없습니다.")
else:
    span = f"{S.d(bt.loc[common, 'anchor'].min())} ~ {S.d(bt.loc[common, 'anchor'].max())}"
    rows_a = []
    for m_key, nm in (("ah", "(가) 애프터마켓만"), ("ah_perp", "(나) 애프터마켓 + 무기한 선물"), ("flat", "(다) 보합 0%")):
        r = res[m_key]
        b = r["big"]
        rows_a.append({
            "예측": nm + (" ← 지금 쓴 방법" if m_key == est.method else ""),
            "N": r["n"],
            "방향 적중률": f"{r['hit']:.0%}" if r["hit"] is not None else "– (방향 없음)",
            "95% 범위": ci_txt(r["ci"]),
            "3단계 적중률": f"{r['hit3']:.0%}" if r["hit3"] is not None else "–",
            "상관계수": f"{r['corr']:+.2f}" if r["corr"] is not None else "–",
            "평균 오차": f"{r['mae'] * 100:.2f}%p" if r["mae"] is not None else "–",
            "갭 1%↑ 방향 적중": (f"{b['hit']:.0%} ({ci_txt(b['ci'])})" if b["hit"] is not None else "–"),
            "갭 1%↑ N": b["n"],
        })
    st.dataframe(pd.DataFrame(rows_a), hide_index=True, width="stretch",
                 column_config={"예측": st.column_config.TextColumn(pinned=True, width="medium")})
    st.caption(
        f"같은 주말 {len(common)}번 ({span}) 기준. 방향 적중률 = 갭의 위·아래를 맞힌 비율 (동전 던지기 50%와 비교), "
        "95% 범위 = 표본이 적을 때 적중률이 이 정도까지 흔들릴 수 있다는 뜻(윌슨 구간). "
        "3단계 적중률 = 갭상승·보합·갭하락(±0.3%) 구간을 맞힌 비율 — 보합 예측도 이걸로 비교. "
        "평균 오차 = |예상 갭 − 실제 갭| 의 평균(%p). 보합 0%의 평균 오차보다 작아야 예측이 쓸모 있다는 뜻입니다.")
    full = gap.accuracy(bt, "ah")
    if full["hit"] is not None:
        st.caption(f"참고: (가) 애프터마켓만은 더 긴 기간({full['n']}주, 2023-12~)으로 보면 방향 적중률 {full['hit']:.0%} "
                   f"({ci_txt(full['ci'])}), 평균 오차 {full['mae'] * 100:.2f}%p. 무기한 선물 자료는 거래소가 최근 약 7개월치만 줍니다.")
show_m = "ah_perp" if res and len(common) >= 3 else "ah"
d = bt[["anchor", "actual", show_m]].dropna() if bt is not None and not bt.empty else pd.DataFrame()
if len(d) >= 3:
    same = (d[show_m] * d["actual"]) > 0
    fs = go.Figure()
    for flag, nm, colr in ((True, "방향 맞음", S.GAIN), (False, "방향 틀림", S.LOSS)):
        dd = d[same == flag]
        fs.add_trace(go.Scatter(x=dd[show_m], y=dd["actual"], mode="markers", name=nm,
                                marker=dict(color=colr, size=7, opacity=0.6),
                                customdata=[S.d(a) for a in dd["anchor"]],
                                hovertemplate="%{customdata}<br>예상 갭 %{x:.2%}<br>실제 갭 %{y:.2%}<extra></extra>"))
    lim = float(max(d[show_m].abs().max(), d["actual"].abs().max())) * 1.1
    fs.add_trace(go.Scatter(x=[-lim, lim], y=[-lim, lim], mode="lines", name="예상 = 실제",
                            line=dict(color=S.INVESTED, width=1, dash="dot"), hoverinfo="skip"))
    ui.chart_title(f"예상 갭 vs 실제 갭 ({gap.METHODS[show_m]})", "점선에 가까울수록 잘 맞힌 주.")
    S.style(fs, height=S.H_BIG, dates=False, unified=False)
    fs.update_xaxes(tickformat=".1%", zeroline=True)
    fs.update_yaxes(tickformat=".1%", zeroline=True)
    ui.plot(fs)

# ── 예상가 장부 ──────────────────────────────────
ui.section("예상가 장부", "주말마다 한 줄씩 자동 저장하고, 미국 정규장이 열리기 전까지 최신 예상으로 덮어씁니다. "
           "장이 열린 뒤 이 페이지를 열면 실제 시가로 채점합니다.")
try:
    if t.weekend:
        pu = sn.perps.get(sn.perp_used) or {}
        gap.save_estimate(t, est, sn.qqq.get("close"), sn.tqqq.get("close"),
                          {"ah": sn.qqq.get("ah_chg"), "perp": sn.perp_used, "perp_close": pu.get("chg_close"),
                           "perp_after_ah": pu.get("chg_ah"), "nq": sn.nq["chg"]}, now)
    gap.settle(store.load_prices("QQQ"), store.load_prices("TQQQ"))
except Exception as e:  # 장부는 재미 기능이라 실패해도 페이지는 계속
    st.caption(f"장부 저장 실패: {e}")
L = gap.ledger()
if L.empty:
    st.info("아직 저장된 예상이 없습니다. 주말(금요일 미국 마감 뒤 ~ 월요일 장 시작 전)에 이 페이지를 열면 저장됩니다.")
else:
    s_ = gap.ledger_stats(L)
    c1, c2, c3 = st.columns(3)
    ui.metric(c1, "채점한 주", f"{s_['n']}주")
    ui.metric(c2, "QQQ 평균 오차", f"±{s_['qqq_mae']:.2%}" if s_["qqq_mae"] is not None else "–",
              note=f"TQQQ ±{s_['tqqq_mae']:.2%}" if s_["tqqq_mae"] is not None else None)
    ui.metric(c3, "방향 맞힌 비율", S.ratio(s_["hit"]) if s_["hit"] is not None else "–")
    show = pd.DataFrame({
        "주말 (미국 금요일)": L["week"], "방법": L["method"].map(gap.METHODS),
        "QQQ 종가": L["qqq_close"], "QQQ 예상": L["qqq_est"], "QQQ 실제 시가": L["qqq_open"], "QQQ 오차": L["qqq_err"],
        "TQQQ 예상": L["tqqq_est"], "TQQQ 실제 시가": L["tqqq_open"], "TQQQ 오차": L["tqqq_err"],
        "방향": L["dir_hit"].map({True: "✅ 맞음", False: "❌ 틀림"}).fillna("채점 전"),
    })
    money = (lambda x: S.usd(x) if pd.notna(x) else "–")
    pctf = (lambda x: S.pct(x) if pd.notna(x) else "–")
    st.dataframe(show.style.format({"QQQ 종가": money, "QQQ 예상": money, "QQQ 실제 시가": money, "QQQ 오차": pctf,
                                    "TQQQ 예상": money, "TQQQ 실제 시가": money, "TQQQ 오차": pctf}),
                 hide_index=True, width="stretch")

ui.footer()
