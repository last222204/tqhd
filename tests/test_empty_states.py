"""빈 상태: 시세가 하나도 없고 받기도 실패할 때 모든 페이지가 멈추지 않고 안내 문구를 보여주는지."""
import pytest
from streamlit.testing.v1 import AppTest

from t6 import refresh, store
from t6.config import ROOT

PAGES = ["today", "charts", "simulator", "exits_lab", "review"]


class _Down:
    name = "fake"

    def fetch_daily(self, *a, **k):
        raise ConnectionError("인터넷 끊김 (테스트)")


@pytest.mark.parametrize("page", PAGES)
def test_page_with_empty_db(page, tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "empty.db")
    monkeypatch.setattr(refresh, "get_source", lambda: _Down())
    store.init_db()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    at.switch_page(f"views/{page}.py")
    at.run()
    assert not at.exception, at.exception
    notes = " ".join(x.value for x in list(at.info) + list(at.error))
    assert "시세" in notes          # '시세가 없습니다 … 새로고침' 안내
