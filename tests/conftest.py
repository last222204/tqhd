"""테스트가 실제 FRED 서버에 접속하지 않게 막는다."""
import pytest


class _NoFred:
    name = "fred"

    def fetch_daily(self, series_id, start):
        raise ConnectionError("테스트에서는 FRED 에 접속하지 않음")


@pytest.fixture(autouse=True)
def _no_fred(monkeypatch):
    from t6 import refresh

    monkeypatch.setattr(refresh, "get_fred_source", lambda: _NoFred())
