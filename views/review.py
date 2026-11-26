"""📋 연간 점검 (지금은 QQQ 1년 변동성 부분만. 교체 횟수·피신 비율·헛걸음·규칙 위반은 3단계에서)"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from t6 import longvol, ui
from t6 import style as S

ui.page_title("📋 연간 점검", "12월 말에 보는 화면. 지금은 'QQQ 1년 변동성'과 '판이 바뀌었나' 신호만 있고, "
              "교체 횟수·피신 비율·헛걸음·규칙 위반은 3단계에서 채웁니다.")

lv = ui.long_vol()
if lv is None:
    st.info("^SOX 시세가 없습니다. 위의 '🔄 시세 새로고침'을 눌러 주세요.")
    ui.footer()
    st.stop()

c1, c2, c3 = st.columns(3)
ui.metric(c1, "QQQ 1년 변동성 (지금)", f"{lv.current:.1%}", note=f"1999년 이후 {longvol.top_pct_text(lv.percentile)}")
ui.metric(c2, "과거 중간값 (QQQ)", f"{lv.qqq_median:.1%}")
ui.metric(c3, "경고 기준 (반도체 ^SOX 중간값)", f"{lv.sox_median:.1%}")

# ── 판이 바뀌었나 ────────────────────────────────
ui.section("판이 바뀌었나")
if lv.warning:
    st.markdown(
        f"<div class='t6-alert-red'>🔴 <b>{longvol.REGIME_MSG}</b><br>"
        f"연말 기준 2년 연속 ({lv.warning_years[-1] - 1}~{lv.warning_years[-1]}) QQQ 1년 변동성 ≥ "
        f"반도체 중간값 {lv.sox_median:.1%}<br>"
        "<span style='opacity:.75;font-size:.9rem'>경고는 정보일 뿐, 신호를 바꾸지 않습니다.</span></div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        f"<div class='t6-alert-none'>⚪ <b>나스닥 변동성 경고: 꺼짐</b><br>"
        f"기준: 연말 QQQ 1년 변동성이 반도체(^SOX) 1999년 이후 중간값 <b>{lv.sox_median:.1%}</b> 이상인 해가 2년 연속<br>"
        "<span style='opacity:.75;font-size:.9rem'>경고는 정보일 뿐, 신호를 바꾸지 않습니다.</span></div>",
        unsafe_allow_html=True,
    )
if lv.warning_years:
    st.caption("과거에 켜졌던 해: " + ", ".join(f"{y}년" for y in lv.warning_years))

# ── 추이 차트 (차트 페이지에서 옮겨 옴) ──────────
ui.section("QQQ 1년 변동성 추이",
           "최근 252거래일 일간 수익률 표준편차 × √252. 빨간 점선 = 경고 기준(반도체 중간값), 회색 점선 = QQQ 중간값.")
fv = go.Figure()
S.date_hover(fv, lv.qqq.index, lv.qqq)
fv.add_trace(go.Scatter(x=lv.qqq.index, y=lv.qqq, name="QQQ", line=dict(color=S.QQQ, width=2.2),
                        hovertemplate="QQQ %{y:.1%}<extra></extra>"))
fv.add_trace(go.Scatter(x=lv.sox.index, y=lv.sox, name="반도체 지수 ^SOX", line=dict(color=S.SOX, width=1.3, dash="dot"),
                        hovertemplate="^SOX %{y:.1%}<extra></extra>"))
fv.add_trace(go.Scatter(x=[lv.qqq.index[0], lv.qqq.index[-1]], y=[lv.sox_median] * 2, mode="lines",
                        name=f"경고 기준 {lv.sox_median:.1%}", line=dict(color=S.LOSS, width=1.5, dash="dash"),
                        hoverinfo="skip"))
fv.add_trace(go.Scatter(x=[lv.qqq.index[0], lv.qqq.index[-1]], y=[lv.qqq_median] * 2, mode="lines",
                        name=f"QQQ 중간값 {lv.qqq_median:.1%}", line=dict(color=S.QQQ, width=1, dash="dot"),
                        hoverinfo="skip"))
S.style(fv, height=S.H_BIG, y_fmt=".0%")
fv.update_yaxes(rangemode="tozero")
ui.plot(fv)

# ── 연도별 연말 1년 변동성 ──────────────────────
ui.section("연도별 연말 1년 변동성")
y = lv.years.iloc[::-1]
table = pd.DataFrame({
    "연도": [f"{i}{'' if c else ' (진행 중)'}" for i, c in zip(y.index, y["complete"])],
    "기준일": y["date"].map(S.d),
    "QQQ 1년 변동성": y["qqq"],
    "^SOX 1년 변동성": y["sox"],
    "기준 이상": ["🔴 이상" if o else "" for o in y["over"]],
})
st.dataframe(table.style.format({"QQQ 1년 변동성": "{:.1%}", "^SOX 1년 변동성": "{:.1%}"}),
             hide_index=True, width="stretch")
st.caption(f"QQQ 과거 중간값 {lv.qqq_median:.1%} · 반도체 중간값(경고 기준) {lv.sox_median:.1%} · "
           "모두 1999년 이후 데이터에서 계산합니다.")

ui.footer()
