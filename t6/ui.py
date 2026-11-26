"""여러 화면이 같이 쓰는 Streamlit 부품: 페이지 제목·섹션·숫자 카드, 데이터 불러오기(캐시), 환율 막대, 데이터 상태 경고.

색·숫자 표기·차트 모양은 t6/style.py 에 있다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from . import market_time as mt
from . import refresh, store
from .config import FX_SYMBOL, SIGNAL_SYMBOL
from .strategy import signal_frame

CSS = """
<style>
/* 글꼴(Pretendard)은 .streamlit/config.toml 의 [theme.light]/[theme.dark] 에서 정한다 */
.block-container {padding-top: 2.2rem; padding-left: 1rem; padding-right: 1rem; max-width: 1100px;}
@media (max-width: 640px) {.block-container {padding-top: 3.4rem;}}   /* 휴대폰: 위쪽 메뉴 막대에 가리지 않게 */
/* 제목은 3단계: 페이지(h2) · 섹션(h3) · 본문 */
.block-container h2 {font-size: 1.65rem !important; font-weight: 700; padding: .2rem 0 .1rem 0 !important;}
.block-container h3 {font-size: 1.22rem !important; font-weight: 700; padding: 1.1rem 0 .2rem 0 !important;}
[data-testid="stMetricValue"] {font-size: 1.75rem !important;}
[data-testid="stMetricDelta"] svg {display: none;}
.t6-card {border-radius: 16px; padding: 18px 20px; margin: 4px 0 12px 0;
          border: 1px solid rgba(128,128,128,.25);}
.t6-sun  {background: rgba(235,104,52,.13); border-color: rgba(235,104,52,.45);}   /* ☀️ TQQQ = style.SUN */
.t6-rain {background: rgba(111,134,201,.16); border-color: rgba(111,134,201,.55);} /* ☂️ 피신 = style.RAIN */
.t6-todo {border: 3px solid #d03b3b;}
.t6-quote {opacity: .62; font-size: .82rem; margin-top: 26px; text-align: center; font-style: italic;}
.t6-big  {font-size: clamp(2.2rem, 10vw, 4.2rem); font-weight: 800; line-height: 1.1; margin: 4px 0;}
.t6-sub  {opacity: .75; font-size: .95rem;}
.t6-steps ol {margin: 6px 0 0 1.1rem; padding: 0; font-size: 1.1rem;}
.t6-steps li {margin: 4px 0;}
.t6-border {border: 3px solid #fab219; background: rgba(250,178,25,.14); border-radius: 14px;
            padding: 14px 18px; font-size: 1.15rem; font-weight: 700; margin: 8px 0;}
.t6-alert-red {border-left: 8px solid #d03b3b; background: rgba(208,59,59,.12); border-radius: 10px; padding: 12px 16px;}
.t6-alert-yellow {border-left: 8px solid #fab219; background: rgba(250,178,25,.14); border-radius: 10px; padding: 12px 16px;}
.t6-alert-none {border-left: 8px solid rgba(128,128,128,.4); background: rgba(128,128,128,.07); border-radius: 10px; padding: 12px 16px;}
.t6-foot {opacity: .6; font-size: .8rem; margin-top: 10px; text-align: center;}
.t6-stale {border: 3px solid #d03b3b; background: rgba(208,59,59,.12); border-radius: 14px;
           padding: 14px 18px; font-size: 1.1rem; margin: 6px 0 12px 0;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


# ── 페이지 구성 공통 ─────────────────────────────
def page_title(title: str, desc: str | None = None) -> None:
    """페이지 맨 위: 제목 → 한 줄 설명."""
    st.markdown(f"## {title}")
    if desc:
        st.caption(desc)


def section(title: str, desc: str | None = None) -> None:
    """섹션 제목 (+ 한 줄 설명). 차트 제목도 이걸로 차트 바로 위에 쓴다."""
    st.markdown(f"### {title}")
    if desc:
        st.caption(desc)


def chart_title(title: str, desc: str | None = None) -> None:
    """차트 바로 위 소제목 (섹션보다 한 단계 작게, 본문 굵게)."""
    tail = f"<br><span style='opacity:.7;font-size:.88rem'>{desc}</span>" if desc else ""
    st.markdown(f"<b>{title}</b>{tail}", unsafe_allow_html=True)


def metric(col, label: str, value: str, note: str | None = None, change: str | None = None) -> None:
    """숫자 카드. note 는 설명(화살표 없음), change 는 진짜 증감(화살표·색 없이 부호로 표시)."""
    col.metric(label, value, note if note is not None else change, delta_color="off", delta_arrow="off")


def plot(fig) -> None:
    from .style import CONFIG

    st.plotly_chart(fig, width="stretch", config=CONFIG)


# ── 데이터 (캐시) ─────────────────────────────────
@st.cache_data(show_spinner=False)
def _load(symbol: str, version: int) -> pd.DataFrame:
    return store.load_prices(symbol)


def prices(symbol: str) -> pd.DataFrame:
    return _load(symbol, store.data_version())


@st.cache_data(show_spinner=False)
def _signals(version: int, col: str) -> pd.DataFrame:
    return signal_frame(store.load_prices(SIGNAL_SYMBOL), col)


@st.cache_data(show_spinner=False)
def _longvol(version: int):
    from . import longvol
    from .config import SOX_SYMBOL

    sox = store.load_prices(SOX_SYMBOL)
    if sox.empty:
        return None
    return longvol.compute(store.load_prices(SIGNAL_SYMBOL)["adj_close"], sox["close"])


def long_vol():
    """QQQ 1년 변동성 계산 결과 (^SOX 데이터가 없으면 None)."""
    return _longvol(store.data_version())


def signals(col: str = "adj_close") -> pd.DataFrame:
    """col='adj_close' 공식 신호, col='close' 배당 미조정 참고."""
    return _signals(store.data_version(), col)


# ── 받기 ─────────────────────────────────────────
def do_refresh() -> list | None:
    """받기. 다른 사람이 받는 중이거나 방금 받았으면 None (중복 요청 방지)."""
    with st.spinner("시세를 받는 중입니다… (처음엔 30초쯤 걸릴 수 있어요)"):
        res = refresh.try_refresh()
    st.cache_data.clear()
    return res


def auto_refresh() -> None:
    """앱이 열릴 때 하루 한 번 자동으로 받는다."""
    if "auto_checked" in st.session_state:
        return
    st.session_state["auto_checked"] = True
    try:
        if refresh.needs_refresh():
            do_refresh()
    except Exception as e:  # 받기 실패해도 저장된 값으로 계속
        st.session_state["auto_error"] = str(e)


# ── 상단 막대 ─────────────────────────────────────
def header() -> None:
    fx = prices(FX_SYMBOL)
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    with c1:
        if len(fx) >= 2:
            now_v, prev_v = fx["close"].iloc[-1], fx["close"].iloc[-2]
            d = fx.index[-1].date()
            metric(st, f"💱 USD/KRW · {d:%Y-%m-%d} 기준", f"{now_v:,.2f}원",
                   change=f"전일 대비 {now_v - prev_v:+,.2f}원 ({now_v / prev_v - 1:+.2%})")
        else:
            st.metric("💱 USD/KRW", "데이터 없음")
    with c2:
        wait = refresh.cooldown_left()
        if st.button("🔄 시세 새로고침", width="stretch", disabled=wait > 0,
                     help=f"방금 받았습니다. {wait}초 뒤에 다시 누를 수 있어요." if wait else None):
            res = do_refresh()
            if res is None:
                st.session_state["refresh_msg"] = ("ok", "방금 받은 시세를 보여드립니다.")
            elif bad := [r for r in res if not r.ok]:
                st.session_state["refresh_msg"] = ("error", "일부를 받지 못했습니다: " + ", ".join(r.symbol for r in bad))
            else:
                st.session_state["refresh_msg"] = ("ok", "새로 받았습니다.")
            st.rerun()
    msg = st.session_state.pop("refresh_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])
    stale_banner()


def stale_banner() -> None:
    f = refresh.freshness()
    if f["have"] is None:
        st.markdown(
            "<div class='t6-stale'>⚠️ <b>아직 받은 시세가 없습니다.</b> 인터넷 연결을 확인하고 "
            "'🔄 시세 새로고침'을 눌러 주세요.</div>",
            unsafe_allow_html=True,
        )
        return
    if f["stale"]:
        err = f["last_try"]["error"] if f["last_try"] and not f["last_try"]["ok"] else None
        st.markdown(
            f"<div class='t6-stale'>⚠️ <b>최신 시세를 받지 못했습니다.</b><br>"
            f"마지막으로 받은 날: <b style='font-size:1.4rem'>{mt.fmt_date(f['have'])} 종가</b><br>"
            f"아래 신호는 <b>이 날짜 기준</b>입니다. (받았어야 할 날: {mt.fmt_date(f['expected'])})</div>",
            unsafe_allow_html=True,
        )
        if err:
            with st.expander("오류 내용"):
                st.code(err)
    elif f["provisional"]:
        st.markdown(
            f"<div class='t6-border'>⏳ <b>잠정 종가</b>로 판정했습니다 ({mt.fmt_date(f['have'])}).<br>"
            "<span style='font-weight:400;font-size:1rem'>Yahoo 일봉에 공식 종가가 아직 없어서, "
            "정규장 마지막 1분봉 값을 종가로 썼습니다. 공식 종가와 보통 몇 센트 차이입니다. "
            "공식 종가가 올라오면 사이트를 열 때 자동으로 바뀝니다 (15분마다 다시 확인).</span></div>",
            unsafe_allow_html=True,
        )


def footer() -> None:
    st.markdown(
        "<div class='t6-foot'>이 사이트는 투자 조언 도구가 아니라, 내가 정한 규칙을 지키기 위한 기록 도구입니다.</div>",
        unsafe_allow_html=True,
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
