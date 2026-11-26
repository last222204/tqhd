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
def state():
    return json.loads((ROOT / "data" / "state.json").read_text(encoding="utf-8"))
