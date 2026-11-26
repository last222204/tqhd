"""프록시: worker.js 와 로컬 쌍둥이(dev_server.py)가 실제 야후 응답을 똑같이 읽는지, 한 종목이 실패해도 나머지는 오는지."""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import dev_server as D  # noqa: E402

FIX = {"QQQ": "QQQ", "TQQQ": "TQQQ", "NQ": "NQ_F", "USDKRW": "KRW_X"}


@pytest.fixture(scope="module")
def worker():
    from py_mini_racer import MiniRacer
    src = (ROOT / "worker" / "worker.js").read_text(encoding="utf-8")
    src = re.sub(r"^export default", "var __handler =", src, flags=re.M)
    src = re.sub(r"^export (const|async function|function)", r"\1", src, flags=re.M)
    ctx = MiniRacer()
    ctx.eval(src)
    return ctx


def yahoo(name):
    return json.loads((ROOT / "tests" / "fixtures" / f"yahoo_{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("key", list(FIX))
def test_worker_and_twin_read_real_yahoo_the_same(worker, key):
    j = yahoo(FIX[key])
    js = json.loads(worker.eval(f"JSON.stringify(parseChart({json.dumps(j)}))"))
    py = D.parse_chart(j)
    assert js == py and py["price"] > 0 and py["time"] > 1.7e9


def test_bad_payload_is_none(worker):
    for bad in ({}, {"chart": {"result": []}}, {"chart": {"result": [{"meta": {"regularMarketPrice": None}}]}}):
        assert worker.eval(f"JSON.stringify(parseChart({json.dumps(bad)}))") == "null"
        assert D.parse_chart(bad) is None


def test_one_symbol_failing_keeps_others(worker):
    fixtures = {sym: yahoo(FIX[k]) for k, sym in {"QQQ": "QQQ", "TQQQ": "TQQQ", "NQ": "NQ%3DF", "USDKRW": "KRW%3DX"}.items()}
    worker.eval("var FIX = " + json.dumps(fixtures) + ";")
    worker.eval("""
      var fakeFetch = function (url) {
        var sym = url.split('/chart/')[1].split('?')[0];
        if (sym === 'TQQQ') return Promise.resolve({ ok: false, status: 429 });
        return Promise.resolve({ ok: true, json: function () { return Promise.resolve(FIX[sym]); } });
      };
      var OUT = null;
      getQuotes(fakeFetch, 1795700000).then(function (o) { OUT = o; });
    """)
    out = json.loads(worker.eval("JSON.stringify(OUT)"))
    assert out["fetched_at"] == 1795700000
    assert out["quotes"]["TQQQ"] is None and out["errors"]["TQQQ"] == "HTTP 429"
    for k in ("QQQ", "NQ", "USDKRW"):
        assert out["quotes"][k] == D.parse_chart(yahoo(FIX[k]))


def test_twin_fake_quotes_shape():
    out = D.fake_quotes({"at": ["1795700000"], "qqq": ["640"], "nq": ["26300"], "nq_at": ["1795690000"]})
    assert out["quotes"]["QQQ"] == {"price": 640.0, "time": 1795700000, "prev_close": None}
    assert out["quotes"]["NQ"]["time"] == 1795690000 and out["quotes"]["TQQQ"] is None
