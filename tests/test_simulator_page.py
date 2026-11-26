"""시뮬레이터 화면을 실제로 돌려 본다 (Streamlit AppTest). 청산 규칙마다 오류 없이 그려지는지."""
import pytest
from streamlit.testing.v1 import AppTest

from t6 import store
from t6.config import ROOT

PAGE = ROOT / "views" / "simulator.py"

RULES = ["고정 기간 (년 수)", "졸업 A: 전고점 졸업", "졸업 B: 목표 배수 졸업", "하락장 강제 청산", "무작위 청산"]


@pytest.fixture(scope="module", autouse=True)
def _need_data():
    store.init_db()
    if (store.last_price_date("TQQQ") or "") < "2026-11-01":
        pytest.skip("저장된 시세가 부족합니다")


def _run(rule, avg=False, start="2012-03-01"):
    import datetime as dt

    at = AppTest.from_file(str(PAGE), default_timeout=120)
    at.session_state["sim_rule"] = rule
    at.session_state["sim_start"] = dt.date.fromisoformat(start)
    at.session_state["sim_avg"] = avg
    at.run()
    return at


@pytest.mark.parametrize("rule", RULES)
def test_rule_renders(rule):
    at = _run(rule)
    assert not at.exception, at.exception
    texts = " ".join(m.value for m in at.markdown)
    assert "청산일" in texts and "### 요약" in texts
    labels = [t.label for t in at.tabs]
    assert len(labels) == 8 and "🔀 청산일 바꿔 보기" in labels and "☂️ 피신 기록" in labels


@pytest.mark.parametrize("rule", ["고정 기간 (년 수)", "졸업 A: 전고점 졸업", "졸업 B: 목표 배수 졸업"])
def test_average_view_renders(rule):
    at = _run(rule, avg=True)
    assert not at.exception, at.exception
    assert any("모든 시기 평균" in m.value for m in at.markdown)
