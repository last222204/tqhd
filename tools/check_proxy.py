"""프록시 연결 테스트.  사용: python tools/check_proxy.py https://tqhd-quotes.<계정>.workers.dev/quotes

확인: 응답 200, CORS 허용 헤더, 네 종목의 가격·시각 형식, 25초 캐시 헤더, 값이 상식 범위인지.
"""
import json
import sys
import time
import urllib.request

RANGES = {"QQQ": (100, 3000), "TQQQ": (1, 2000), "NQ": (5000, 100000), "USDKRW": (500, 3000)}


def check(url):
    req = urllib.request.Request(url, headers={"Origin": "https://example.github.io", "User-Agent": "tqhd-check"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=20) as r:
        status, headers, body = r.status, r.headers, json.loads(r.read())
    dt = time.time() - t0
    problems = []
    if status != 200:
        problems.append(f"상태 {status}")
    if headers.get("Access-Control-Allow-Origin") not in ("*", "https://example.github.io"):
        problems.append("CORS 허용 헤더 없음")
    for k, (lo, hi) in RANGES.items():
        q = body.get("quotes", {}).get(k)
        if not q:
            problems.append(f"{k} 없음 ({body.get('errors', {}).get(k)})")
            continue
        if not (lo <= q["price"] <= hi):
            problems.append(f"{k} 가격 이상 {q['price']}")
        age = time.time() - q["time"]
        print(f"  {k:7s} {q['price']:>12,.2f}   거래 시각 {time.strftime('%m/%d %H:%M:%S', time.localtime(q['time']))}"
              f"  ({age / 60:,.0f}분 전)")
    print(f"  응답 {dt:.2f}초 · Cache-Control: {headers.get('Cache-Control')}")
    return problems


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8780/quotes"
    print(url)
    p = check(url)
    print("✅ 통과" if not p else "❌ " + " / ".join(p))
    sys.exit(1 if p else 0)
