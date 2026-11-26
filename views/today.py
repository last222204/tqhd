"""☀️ 오늘 (첫 화면) — 10초 안에 할 일을 알 수 있게: 신호·할 일 → 경계선·경고등 → 나머지는 접기."""
import streamlit as st

from t6 import live, longvol, rsi2, today, ui
from t6 import market_time as mt
from t6 import style as S
from t6.config import (BORDER_PCT, RISK_OFF, RISK_ON, SIGNAL_SYMBOL, SMA_FAST, SMA_SLOW, VOL_ALERT, VOL_WINDOW,
                       label)
from t6.style import pct, usd

ui.page_title("☀️ 오늘", "미국 장 마감 뒤 확정 종가로 판정한 오늘의 신호와 할 일.")

sf = ui.signals("adj_close")
if sf["signal"].dropna().empty:
    st.info("신호를 계산할 시세가 아직 없습니다. 위의 '🔄 시세 새로고침'을 눌러 주세요.")
    ui.footer()
    st.stop()

v = today.build(sf, ui.signals("close"), ui.now_utc())
rain = v.signal == RISK_OFF
icon = "☂️" if rain else "☀️"
_q = ui.prices(SIGNAL_SYMBOL)
prov = bool(_q["provisional"].iloc[-1]) if "provisional" in _q and len(_q) else False

# ── 신호 ─────────────────────────────────────────
st.markdown(
    f"""<div class='t6-card {"t6-rain" if rain else "t6-sun"}'>
    <div class='t6-sub'>오늘의 신호</div>
    <div class='t6-big'>{icon} {label(v.signal)}</div>
    <div class='t6-sub'>판정 기준: <b>{mt.fmt_date(v.as_of)} 미국 {"잠정 종가 ⏳" if prov else "종가"}</b> (QQQ 배당조정 종가)
    · 한국 시간 {mt.fmt_kst(v.session.close_kst)} 마감</div>
    </div>""",
    unsafe_allow_html=True,
)

# ── 사냥 칸 (조건이 맞을 때만) + 작은 RSI2 칸 ────
lv = rsi2.levels(_q["adj_close"], float(ui.prices(RISK_ON)["close"].iloc[-1]) if len(ui.prices(RISK_ON)) else None)
episodes = rsi2.hunts(rsi2.rsi_series(_q["adj_close"]), sf["signal"] == RISK_OFF)


@st.cache_data(ttl=60, show_spinner=False)
def _live(symbol: str, minute: int):
    return live.last_price(symbol)


_now = ui.now_utc()
_sess = rsi2.today_session(_now)


@st.fragment(run_every=60 if rsi2.market_open(_now, _sess) else None)
def hunt_panel():
    now = ui.now_utc()
    session = rsi2.today_session(now)
    is_open = rsi2.market_open(now, session)
    p = _live(SIGNAL_SYMBOL, int(now.timestamp() // 60)) if is_open else None
    hv = rsi2.hunt_view(lv, rain, episodes, session, p, rsi2.skipped())
    box = "<div class='t6-card' style='padding:10px 16px;border:2px solid {c}'>{t}</div>"
    if hv.kind == "wait":
        st.markdown(box.format(c=S.WARN, t=(
            f"🦇 <b>사냥 대기</b> · 기준 {lv.buy:.2f} (TQQQ 대략 {lv.tqqq_at(lv.buy) or 0:.2f}) · 현재 {p:.2f} "
            f"(기준까지 {lv.buy / p - 1:+.1%})")), unsafe_allow_html=True)
    elif hv.kind == "enter":
        tight = " <span class='t6-sub'>· 애매: 들어가지 않음</span>" if hv.tight else ""
        st.markdown(box.format(c=S.SUN, t=f"🦇 <b>사냥 진입</b> · 마감 전 TQQQ 매수 · RSI2 {hv.live_rsi:.1f}{tight}"),
                    unsafe_allow_html=True)
    elif hv.kind in ("hunting", "exit"):
        if hv.kind == "hunting":
            note = f"<br><span class='t6-sub'>{hv.note}</span>" if hv.note else ""
            txt = (f"🦇 <b>사냥 중 {hv.day}일째</b> · 매도 기준 {lv.sell:.2f} (RSI2>50) · "
                   f"5일째: {hv.day5.month}월 {hv.day5.day}일{note}")
            st.markdown(box.format(c=S.SUN, t=txt), unsafe_allow_html=True)
        else:
            st.markdown(box.format(c=S.RAIN, t=f"🔙 <b>복귀</b> · 마감 전 TQQQ 매도 → 현금 "
                                               f"<span class='t6-sub'>({hv.note})</span>"), unsafe_allow_html=True)
        if st.checkbox("이번 사냥 건너뜀", key=f"hunt_skip_{hv.entry.date()}"):
            rsi2.set_skip(hv.entry.date(), True)
            st.rerun()
    elif hv.entry is not None and session is not None:      # 건너뛴 회차: 되돌리기만 작게
        if st.button(f"↩ {hv.entry.date()} 사냥 건너뜀 취소", key="hunt_unskip"):
            rsi2.set_skip(hv.entry.date(), False)
            st.rerun()

    # 작은 RSI2 칸: 확정 · 실시간(장중 추정) · 사냥 확인 시각까지
    parts = [f"RSI2 확정 <b>{lv.rsi:.1f}</b> <span class='t6-sub'>({lv.as_of:%m-%d} 종가)</span>"]
    if is_open:
        parts.append(f"실시간 <b>{hv.live_rsi:.1f}</b> <span class='t6-sub'>(장중 추정, QQQ {p:.2f})</span>"
                     if p is not None else "<span class='t6-sub'>실시간 없음</span>")
    if session is not None:
        chk = rsi2.check_time(session)
        if now < chk:
            h, m_ = divmod(int((chk - now).total_seconds() // 60), 60)
            parts.append(f"사냥 확인 {mt.fmt_kst(chk, False)}까지 <b>{h}시간 {m_}분</b>")
    st.markdown("<div class='t6-card' style='padding:8px 16px;font-size:.95rem'>" + " · ".join(parts) + "</div>",
                unsafe_allow_html=True)


hunt_panel()

# ── 할 일 ────────────────────────────────────────
if v.switched:
    steps = "".join(f"<li>{s}</li>" for s in v.steps)
    when = "<br>".join(v.when).replace("~", "&#126;")
    st.markdown(
        f"""<div class='t6-card t6-steps t6-todo'>
        <div style='font-size:1.35rem;font-weight:700'>🔁 교체일입니다: {label(v.prev_signal)} → {label(v.signal)}</div>
        <ol>{steps}</ol>
        <div style='margin-top:8px'>🕒 {when}</div>
        </div>""",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"<div class='t6-card'><b>교체 없음.</b> 어제와 같은 신호입니다. {label(v.signal)} 그대로 보유. 할 일 없음.</div>",
        unsafe_allow_html=True,
    )

# ── 경계선 · 경고등 ──────────────────────────────
if v.border:
    lines = []
    if abs(v.dist_fast) <= BORDER_PCT + 1e-12:
        lines.append(f"{SMA_FAST}일선과 {v.dist_fast:+.2%}")
    if abs(v.dist_slow) <= BORDER_PCT + 1e-12:
        lines.append(f"{SMA_SLOW}일선과 {v.dist_slow:+.2%}")
    st.markdown(
        f"<div class='t6-border'>⚠️ 경계선: 종가가 {' / '.join(lines)} 거리입니다 (±{BORDER_PCT:.1%} 이내).<br>"
        "<span style='font-weight:400;font-size:1rem'>데이터 출처나 조정 방식에 따라 신호가 갈릴 수 있는 구간입니다. "
        "판정은 이 사이트의 배당조정 종가 기준을 따릅니다.</span></div>",
        unsafe_allow_html=True,
    )

vol_txt = f"QQQ {VOL_WINDOW}거래일 변동성 <b>{v.vol:.1%}</b> (기준 {VOL_ALERT:.0%})"
if v.alert == "red":
    body = f"🔴 <b>경고등: 꼭대기 첫 폭풍 가능성. 규칙은 그대로.</b><br>{vol_txt} · 200일선 위"
elif v.alert == "yellow":
    body = f"🟡 <b>경고등: 바닥 근처 소란 가능성. 규칙은 그대로.</b><br>{vol_txt} · 200일선 아래"
else:
    body = f"⚪ 경고등 꺼짐 · {vol_txt}"
st.markdown(
    f"<div class='t6-alert-{v.alert or 'none'}'>{body}<br>"
    "<span style='opacity:.75;font-size:.9rem'>경고등은 정보일 뿐, 신호를 바꾸지 않습니다.</span></div>",
    unsafe_allow_html=True,
)

lv = ui.long_vol()
if lv is not None and lv.warning:          # 판이 바뀌었나 경고는 켜졌을 때만 여기에도 크게
    st.markdown(
        f"<div class='t6-alert-red' style='margin-top:10px'>🔴 <b>{longvol.REGIME_MSG}</b><br>"
        f"연말 기준 QQQ 1년 변동성이 반도체 중간값 이상인 해가 2년 연속 ({lv.warning_years[-1] - 1}~{lv.warning_years[-1]})<br>"
        "<span style='opacity:.75;font-size:.9rem'>경고는 정보일 뿐, 신호를 바꾸지 않습니다.</span></div>",
        unsafe_allow_html=True,
    )

# ── 다음 일정 (짧게) ─────────────────────────────
nc = v.next_contribution_kst
s = v.next_session
judge = (f"🕒 다음 신호 판정 **{mt.fmt_kst(v.next_judgement_kst)} 이후**" if v.next_judgement_kst > ui.now_utc()
         else f"🕒 {mt.fmt_kst(v.next_judgement_kst)}에 마감한 장의 시세를 기다리는 중")
st.markdown(
    f"<div style='margin-top:14px'></div>\n\n"
    f"💰 다음 적립일 **{mt.fmt_date(v.next_contribution)}** · 넣을 곳: 그날 보유 중인 쪽 (지금 신호대로라면 **{label(v.signal)}**)  \n"
    f"{judge}",
    unsafe_allow_html=True,
)

# ── 접어 둔 상세 ─────────────────────────────────
with st.expander(f"QQQ 종가와 이동평균 — 종가 {usd(v.close)}, 50일선 {pct(v.dist_fast)}, 200일선 {pct(v.dist_slow)}"):
    c1, c2, c3 = st.columns(3)
    ui.metric(c1, "QQQ 종가 (배당조정)", usd(v.close))
    ui.metric(c2, f"{SMA_FAST}일선", usd(v.sma_fast), note=f"종가가 {pct(v.dist_fast)}")
    ui.metric(c3, f"{SMA_SLOW}일선", usd(v.sma_slow), note=f"종가가 {pct(v.dist_slow)}")
    pos = (lambda x: "위" if x >= 0 else "아래")
    st.caption(f"종가는 {SMA_FAST}일선 {pos(v.dist_fast)}, {SMA_SLOW}일선 {pos(v.dist_slow)}. "
               "규칙: 둘 다 아래면 ☂️ 현금(달러), 하나라도 위면 ☀️ TQQQ.")
    r = v.raw
    st.markdown(f"**참고: 배당 미조정 종가 기준** (신호 판정에는 쓰지 않음) — 종가 {usd(r['close'])}, "
                f"{SMA_FAST}일선 {usd(r['sma_fast'])} ({pct(r['dist_fast'])}), "
                f"{SMA_SLOW}일선 {usd(r['sma_slow'])} ({pct(r['dist_slow'])}) → 신호 **{label(r['signal'])}**")
    if r["signal"] != v.signal:
        st.warning("미조정 기준과 공식 기준의 신호가 다릅니다. 공식 신호는 배당조정 기준입니다.")

if lv is not None:
    with st.expander(f"QQQ 1년 변동성 — {lv.current:.1%} (1999년 이후 {longvol.top_pct_text(lv.percentile)})"):
        c1, c2, c3 = st.columns(3)
        ui.metric(c1, "지금 (최근 252거래일)", f"{lv.current:.1%}",
                  note=f"1999년 이후 {longvol.top_pct_text(lv.percentile)}")
        ui.metric(c2, "과거 중간값 (QQQ)", f"{lv.qqq_median:.1%}")
        ui.metric(c3, "경고 기준 (반도체 ^SOX 중간값)", f"{lv.sox_median:.1%}")
        st.caption("판이 바뀌었나 신호: " + ("켜짐" if lv.warning else "꺼짐") +
                   ". 연말 기준 2년 연속 반도체 중간값 이상이면 켜집니다. 경고는 정보일 뿐, 신호를 바꾸지 않습니다.")
        st.page_link("views/review.py", label="연간 점검에서 추이 차트와 연도별 표 보기", icon="📋")

with st.expander("다음 일정 자세히 (한국 시간표)"):
    season = "여름 (서머타임)" if s.summer else "겨울"
    st.markdown(
        f"**💰 다음 적립일 {mt.fmt_date(v.next_contribution)}** — 정규장 {mt.fmt_kst(nc.open_kst)} \\~ "
        f"{mt.fmt_kst(nc.close_kst)}  \n"
        f"**🕒 다음 판정 거래일 {mt.fmt_date(s.session)}** ({season} 시간표) — 정규장 "
        f"{mt.fmt_kst(s.open_kst, False)}\\~{mt.fmt_kst(s.close_kst, False)}, 애프터마켓 "
        f"{mt.fmt_kst(s.after_start_kst, False)}\\~{mt.fmt_kst(s.after_end_kst, False)}"
    )

f = ui.store.last_fetch(ok=True)
if f:
    st.caption(f"데이터: {f['source']} · 받은 시각 {mt.fmt_kst(f['fetched_at'])} (한국 시간)")

st.markdown("<div class='t6-quote'>2022-04-08 ~ 07-19 피신 68일, TQQQ 그대로였다면 -45%. 보험료는 이날을 위해 낸다.</div>",
            unsafe_allow_html=True)
ui.footer()
