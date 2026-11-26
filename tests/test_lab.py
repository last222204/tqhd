"""무작위 청산 시뮬레이션: 시드 재현, 같은 청산일, 데이터 끝 제외, 화면."""
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from t6 import store
from t6.config import ROOT
from t6.sim import data, engine, exits, lab

S = [engine.UMBRELLA, "QQQ", "QLD", "TQQQ"]


@pytest.fixture(scope="module")
def m():
    store.init_db()
    if (store.last_price_date("TQQQ") or "") < "2026-11-01":
        pytest.skip("저장된 시세가 부족합니다")
    return data.build()


def _p(m):
    return engine.Params(start=m.idx[0], end=m.idx[1])


def test_same_seed_same_result(m):
    d1 = lab.draw(m, 150, 42, 3, 10, False)
    d2 = lab.draw(m, 150, 42, 3, 10, False)
    d3 = lab.draw(m, 150, 43, 3, 10, False)
    assert (d1.a == d2.a).all() and (d1.e == d2.e).all() and d1.rejected == d2.rejected
    assert not (d1.a == d3.a).all()
    r1 = lab.simulate(m, S, _p(m), d1, exits.Thresholds())
    r2 = lab.simulate(m, S, _p(m), d2, exits.Thresholds())
    assert np.allclose(r1.sort_values(["draw", "strategy"])["multiple"].to_numpy(),
                       r2.sort_values(["draw", "strategy"])["multiple"].to_numpy())


def test_exit_never_past_data_end_and_in_range(m):
    d = lab.draw(m, 400, 1, 8, 12, False)          # 긴 보유 → 많이 버려진다
    assert d.rejected > 0
    assert (d.e <= len(m.idx) - 1).all()
    assert (d.a >= m.i_on_or_after("2010-03-01")).all()
    yrs = (m.idx[d.e] - m.idx[d.a]).days / 365.25
    assert (yrs >= 8 - 0.02).all() and (yrs <= 12 + 0.02).all()


def test_all_strategies_share_start_and_exit(m):
    d = lab.draw(m, 60, 3, 3, 10, False)
    df = lab.simulate(m, S, _p(m), d, exits.Thresholds())
    per = df.groupby("draw").agg(n=("strategy", "nunique"), starts=("start", "nunique"), exits_=("exit", "nunique"))
    assert (per["n"] == 4).all() and (per["starts"] == 1).all() and (per["exits_"] == 1).all()
    # 한 시나리오를 엔진으로 따로 돌려도 같은 값 (청산일 칸 = 실제 청산)
    row = df[(df["draw"] == 0) & (df["strategy"] == engine.UMBRELLA)].iloc[0]
    r = engine.run(m, engine.UMBRELLA, engine.Params(start=row["start"], end=row["exit"]))
    assert abs(r.multiple - row["multiple"]) < 1e-9


def test_class_mix_changes_with_thresholds(m):
    d = lab.draw(m, 300, 5, 3, 10, False)
    a = lab.simulate(m, ["QQQ"], _p(m), d, exits.Thresholds())
    b = lab.simulate(m, ["QQQ"], _p(m), d, exits.Thresholds(-0.15, -0.10))
    assert (a["cls"] == exits.RED).sum() < (b["cls"] == exits.RED).sum()
    assert (a["cls"] == exits.GREEN).sum() < (b["cls"] == exits.GREEN).sum()
    ct = lab.class_table(a, ["QQQ"])
    assert set(ct["cls"]) >= {"all"} and ct.loc[ct["cls"] == "all", "n"].iloc[0] == 300


def test_lab_page_renders(m):
    at = AppTest.from_file(str(ROOT / "views" / "exits_lab.py"), default_timeout=300)
    at.session_state["lab_n"] = 200
    at.run()
    assert not at.exception, at.exception
    texts = " ".join(x.value for x in at.markdown)
    assert "### 청산 분류별 결과" in texts and "### 한눈에 보는 비교" in texts and "### 주사위 한 번 굴리기" in texts
