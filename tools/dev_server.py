"""로컬 미리보기 서버: 사이트 파일 + /quotes (worker/worker.js 와 같은 일을 하는 파이썬 쌍둥이).

사용: python tools/dev_server.py [포트=8780]
  /quotes            야후에서 실제 현재가 (워커와 같은 형식)
  /quotes?fail=1     프록시 실패 흉내 (502)
  /quotes?at=<초>&qqq=..&tqqq=..&nq=..&nq_at=<초>&fx=..   정해 둔 값 (화면 시험용)
화면 쪽 시계는 localhost 에서만 ?now=2026-11-27T16:00:00Z 로 바꿀 수 있다 (assets/app.js).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYMBOLS = {"QQQ": "QQQ", "TQQQ": "TQQQ", "NQ": "NQ=F", "USDKRW": "KRW=X"}
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/"
CACHE_SECONDS = 25
_cache: dict = {"t": 0, "body": None}


def parse_chart(j):
    """worker.js 의 parseChart 와 같은 규칙."""
    try:
        m = j["chart"]["result"][0]["meta"]
    except (KeyError, IndexError, TypeError):
        return None
    p, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
    if not isinstance(p, (int, float)) or isinstance(p, bool) or not isinstance(t, (int, float)):
        return None
    pc = m.get("chartPreviousClose")
    return {"price": p, "time": t, "prev_close": pc if isinstance(pc, (int, float)) else None}


def _one(sym):
    url = YAHOO + urllib.parse.quote(sym) + "?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        q = parse_chart(json.loads(r.read()))
    if q is None:
        raise ValueError("형식 다름")
    return q


def get_quotes():
    out = {"fetched_at": int(time.time()), "quotes": {}, "errors": {}}
    with ThreadPoolExecutor(4) as ex:
        futs = {k: ex.submit(_one, s) for k, s in SYMBOLS.items()}
    for k, f in futs.items():
        try:
            out["quotes"][k] = f.result()
        except Exception as e:  # noqa: BLE001
            out["quotes"][k] = None
            out["errors"][k] = str(e)
    return out


def fake_quotes(qs):
    g = lambda k, d=None: float(qs[k][0]) if k in qs else d  # noqa: E731
    at = g("at", time.time())
    q = {}
    for key, name in (("QQQ", "qqq"), ("TQQQ", "tqqq"), ("NQ", "nq"), ("USDKRW", "fx")):
        if name in qs:
            q[key] = {"price": g(name), "time": int(g(name + "_at", at)), "prev_close": None}
        else:
            q[key] = None
    return {"fetched_at": int(at), "quotes": q, "errors": {}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        if u.path != "/quotes":
            return super().do_GET()
        qs = urllib.parse.parse_qs(u.query)
        if "fail" in qs:
            return self._json({"error": "흉내 낸 실패"}, 502)
        if "at" in qs or "qqq" in qs:
            return self._json(fake_quotes(qs), 200)
        if time.time() - _cache["t"] > CACHE_SECONDS or _cache["body"] is None:
            _cache["body"], _cache["t"] = get_quotes(), time.time()
        body = _cache["body"]
        self._json(body, 200 if any(body["quotes"].values()) else 502)

    def _json(self, body, status):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8780
    print(f"http://localhost:{port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
