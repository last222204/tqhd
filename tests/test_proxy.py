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
        assert out["quotes"][k] == D.parse_for(k, yahoo(FIX[k]))
        old = D.parse_chart(yahoo(FIX[k]))                                     # 옛 필드는 그대로
        assert {f: out["quotes"][k][f] for f in old} == old


def test_twin_fake_quotes_shape():
    out = D.fake_quotes({"at": ["1795700000"], "qqq": ["640"], "nq": ["26300"], "nq_at": ["1795690000"]})
    assert out["quotes"]["QQQ"] == {"price": 640.0, "time": 1795700000, "prev_close": None, "last": None, "regular_close": None}
    assert out["quotes"]["NQ"]["time"] == 1795690000 and out["quotes"]["TQQQ"] is None


# ── 시간외 포함 응답 (1분봉 · 5분봉) ─────────────────
EXT = [("QQQ", "QQQ_1m_pre"), ("TQQQ", "TQQQ_1m_pre"), ("QQQ", "QQQ_1m_post"), ("TQQQ", "TQQQ_1m_post"),
       ("NQ", "NQ_F_5m"), ("QQQ", "QQQ"), ("NQ", "NQ_F"), ("USDKRW", "KRW_X")]


@pytest.mark.parametrize("key, name", EXT)
def test_worker_and_twin_same_extended_fields(worker, key, name):
    j = yahoo(name)
    js = json.loads(worker.eval(f"JSON.stringify(parseFor({json.dumps(key)}, {json.dumps(j)}))"))
    assert js == D.parse_for(key, j)


def test_extended_fields_from_real_premarket():
    q = D.parse_for("QQQ", yahoo("QQQ_1m_pre"))
    assert q["price"] == 633.93 and q["time"] == 1795640401                  # 정규장 값은 그대로 (하위 호환)
    assert q["last"]["time"] > q["time"] and q["last"]["price"] > 0           # 프리장 체결이 마지막
    assert q["regular_close"] is None                                         # 오늘 정규장은 아직 → 없음
    t = D.parse_for("TQQQ", yahoo("TQQQ_1m_pre"))
    assert t["last"]["time"] > t["time"]


def test_regular_close_only_after_close():
    q = D.parse_for("QQQ", yahoo("QQQ_1m_post"))
    assert q["regular_close"] == {"price": 633.93, "time": 1795640401}
    assert q["last"]["time"] >= 1795640400                                    # 애프터장 체결


def test_nq_bars_are_time_close_pairs():
    n = D.parse_for("NQ", yahoo("NQ_F_5m"))
    b = n["bars"]
    assert len(b) > 100 and all(len(x) == 2 and x[1] > 0 for x in b)
    assert [x[0] for x in b] == sorted(x[0] for x in b)
    assert all(b[i + 1][0] - b[i][0] >= 300 for i in range(len(b) - 1))
    assert "bars" not in D.parse_for("USDKRW", yahoo("KRW_X")) and "last" not in n


def test_urls_same_in_worker_and_twin(worker):
    now = 1795771000
    for k in ("QQQ", "TQQQ", "NQ", "USDKRW"):
        assert worker.eval(f"urlFor({json.dumps(k)}, {now})") == D.url_for(k, now)
    assert "interval=1m&period1=1795425400&period2=1795771000&includePrePost=true" in D.url_for("QQQ", now)
    assert D.url_for("NQ", now).endswith("NQ%3DF?interval=5m&range=5d&includePrePost=true")
    assert D.url_for("USDKRW", now).endswith("?interval=1d&range=5d")


def test_worker_get_quotes_adds_new_fields_keeps_old(worker):
    fixtures = {"QQQ": yahoo("QQQ_1m_pre"), "TQQQ": yahoo("TQQQ_1m_pre"), "NQ%3DF": yahoo("NQ_F_5m"), "KRW%3DX": yahoo("KRW_X")}
    worker.eval("var FIX2 = " + json.dumps(fixtures) + ";")
    worker.eval("""
      var OUT2 = null;
      getQuotes(function (url) {
        var sym = url.split('/chart/')[1].split('?')[0];
        return Promise.resolve({ ok: true, json: function () { return Promise.resolve(FIX2[sym]); } });
      }, 1795771000).then(function (o) { OUT2 = o; });
    """)
    out = json.loads(worker.eval("JSON.stringify(OUT2)"))
    for k in ("QQQ", "TQQQ", "NQ", "USDKRW"):
        assert {"price", "time", "prev_close"} <= set(out["quotes"][k])
    assert out["quotes"]["QQQ"] == D.parse_for("QQQ", yahoo("QQQ_1m_pre"))
    assert out["quotes"]["NQ"]["bars"] == D.parse_for("NQ", yahoo("NQ_F_5m"))["bars"]


def test_twin_fake_quotes_extended():
    out = D.fake_quotes({"at": ["1795700000"], "qqq": ["640"], "qqq_last": ["642"], "qqq_last_at": ["1795699900"],
                         "qqq_close": ["640"], "qqq_close_at": ["1795640401"], "nq": ["26300"], "nq_bars": ["1795699500:26290,1795699800:26295"]})
    q = out["quotes"]["QQQ"]
    assert q["last"] == {"price": 642.0, "time": 1795699900} and q["regular_close"] == {"price": 640.0, "time": 1795640401}
    assert out["quotes"]["NQ"]["bars"] == [[1795699500, 26290.0], [1795699800, 26295.0]]
