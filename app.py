"""☂️ 우산 T6 — 시작 파일.  실행: 실행.bat  (또는  streamlit run app.py)"""
import streamlit as st

from t6 import store, ui

st.set_page_config(page_title="우산 T6", page_icon="☂️", layout="wide", initial_sidebar_state="auto")
store.init_db()
ui.inject_css()

# 메뉴: 매일 쓰는 것 / 연구 / 점검.  (기록: 매매 기록·내 계좌·세금은 2단계에서 이 자리에 들어간다)
pages = {
    "매일": [
        st.Page("views/today.py", title="오늘", icon="☀️", default=True),
        st.Page("views/charts.py", title="차트", icon="📈"),
    ],
    "연구": [
        st.Page("views/simulator.py", title="시뮬레이터", icon="🧪"),
        st.Page("views/exits_lab.py", title="청산 시나리오", icon="🎲"),
        st.Page("views/gap.py", title="주말 갭 점치기", icon="🎲"),
    ],
    "점검": [
        st.Page("views/review.py", title="연간 점검", icon="📋"),
    ],
}
nav = st.navigation(pages, position="sidebar", expanded=True)

ui.auto_refresh()
ui.header()
nav.run()
