import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def js():
    """assets/core.js 를 V8 에 올려 놓고 TQHD.<함수>(인자...) 를 부르는 도우미."""
    from py_mini_racer import MiniRacer
    ctx = MiniRacer()
    ctx.eval((ROOT / "assets" / "core.js").read_text(encoding="utf-8"))

    def call(fn, *args):
        out = ctx.eval(f"JSON.stringify(TQHD.{fn}.apply(null, {json.dumps(list(args))}))")
        return None if out is None else json.loads(out)
    call.ctx = ctx
    return call


@pytest.fixture(scope="session")
def prices():
    df = pd.read_csv(ROOT / "data" / "prices.csv", index_col="date", parse_dates=True)
    return df


@pytest.fixture(scope="session")
def state(prices):
    """2026-11-25 종가 기준으로 고정한 state (매일 갱신되는 data/state.json 과 무관하게 같은 시험)."""
    from datetime import datetime, timezone
    import update_state as U
    p = prices.loc[:"2026-11-25"]
    st, _ = U.build_state(p["qqq"], p["tqqq"], datetime(2026, 11, 26, 14, 0, tzinfo=timezone.utc),
                          (26105.5, "2026-11-25T21:00:00Z", "5분봉"), {"price": 1343.25, "date": "2026-11-26"})
    return json.loads(json.dumps(st))
