"""모든 페이지를 Playwright 로 캡처하고 자동 점검 (겹침·가로 넘침·로딩 시간).

사용: python qa/shots.py http://localhost:8503 qa/shots/before
결과: <out>/<page>_<width>_<scheme>_<NN>.png (화면 높이씩 잘라서), <out>/report.json
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1].rstrip("/"), Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
PAGES = {"today": "/", "charts": "/charts", "simulator": "/simulator", "exits_lab": "/exits_lab", "review": "/review", "gap": "/gap"}
SIZES = {"1440": (1440, 900), "390": (390, 844)}
SCHEMES = sys.argv[3].split(",") if len(sys.argv) > 3 else ["light", "dark"]
if len(sys.argv) > 4:
    PAGES = {k: v for k, v in PAGES.items() if k in sys.argv[4].split(",")}
# 계산이 오래 걸리는 페이지는 마지막 섹션이 그려질 때까지 기다린다
WAIT_TEXT = {"exits_lab": "주사위 한 번 굴리기", "simulator": "내보내기", "gap": "예상가 장부"}

# 차트 안 글자 상자들이 서로 겹치는지 (제목·범례·축 이름·주석)
JS_OVERLAP = r"""
() => {
  const out = [];
  const box = e => { const r = e.getBoundingClientRect(); return {x:r.left, y:r.top, w:r.width, h:r.height}; };
  const hit = (a, b) => a.w > 0 && b.w > 0 && a.x < b.x + b.w - 1 && b.x < a.x + a.w - 1 && a.y < b.y + b.h - 1 && b.y < a.y + a.h - 1;
  document.querySelectorAll('.js-plotly-plot').forEach((p, i) => {
    const title = (p.layout && p.layout.title && p.layout.title.text || '').replace(/<[^>]+>/g, '');
    const parts = [];
    p.querySelectorAll('.gtitle').forEach(e => parts.push(['제목', box(e)]));
    p.querySelectorAll('.legend').forEach(e => parts.push(['범례', box(e.querySelector('.bg') || e)]));
    p.querySelectorAll('.xtitle, .ytitle').forEach(e => parts.push(['축 이름', box(e)]));
    p.querySelectorAll('.annotation').forEach(e => parts.push(['주석:' + e.textContent.slice(0, 20), box(e)]));
    for (let a = 0; a < parts.length; a++) for (let b = a + 1; b < parts.length; b++)
      if (hit(parts[a][1], parts[b][1])) out.push({chart: i + 1, title, a: parts[a][0], b: parts[b][0]});
    // 그림 영역 밖으로 잘린 범례
    const pr = box(p);
    p.querySelectorAll('.legend').forEach(e => { const r = box(e); if (r.x < pr.x - 1 || r.x + r.w > pr.x + pr.w + 1) out.push({chart: i + 1, title, a: '범례', b: '차트 밖으로 잘림'}); });
  });
  return out;
}
"""
JS_OVERFLOW = r"""
() => {
  const W = window.innerWidth, out = [];
  document.querySelectorAll('[data-testid="stMain"] *').forEach(e => {
    const r = e.getBoundingClientRect();
    if (r.right > W + 2 && r.width > 0 && !e.closest('[data-testid="stDataFrame"]') && !e.closest('pre') && !e.closest('.js-plotly-plot'))
      out.push((e.getAttribute('data-testid') || e.tagName) + ' ' + Math.round(r.right));
  });
  return {pageScrollW: document.documentElement.scrollWidth, W, wide: [...new Set(out)].slice(0, 8)};
}
"""
JS_HEIGHT = "() => { const m = document.querySelector('[data-testid=\"stMain\"]'); return m ? m.scrollHeight : document.body.scrollHeight; }"
JS_BUSY = "() => !!document.querySelector('[data-testid=\"stStatusWidget\"]') || !!document.querySelector('.stSpinner, [data-testid=\"stSpinner\"]')"


def wait_ready(page, timeout=180):
    t = time.time()
    page.wait_for_selector('[data-testid="stMain"]', timeout=timeout * 1000)
    stable, last = 0, None
    while time.time() - t < timeout:
        busy = page.evaluate(JS_BUSY)
        n = page.evaluate("() => document.querySelectorAll('[data-testid=\"stMain\"] *').length")
        stable = stable + 1 if (not busy and n == last) else 0
        last = n
        if stable >= 4:
            break
        time.sleep(0.5)
    return time.time() - t


report = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for scheme in SCHEMES:
        for wkey, (w, h) in SIZES.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme,
                                      is_mobile=w < 600, has_touch=w < 600, device_scale_factor=1)
            page = ctx.new_page()
            errors = []
            page.on("console", lambda msg, errors=errors: errors.append(msg.text[:200]) if msg.type == "error" else None)
            for name, path in PAGES.items():
                t0 = time.time()
                page.goto(BASE + path)
                load = wait_ready(page)
                if name in WAIT_TEXT:
                    page.wait_for_function(f"() => document.body.innerText.includes({json.dumps(WAIT_TEXT[name])})",
                                           timeout=300_000)
                    load = time.time() - t0
                    wait_ready(page)
                H = page.evaluate(JS_HEIGHT)
                overlaps = page.evaluate(JS_OVERLAP)
                overflow = page.evaluate(JS_OVERFLOW)
                # 화면 높이씩 내려가며 캡처
                n = 0
                for y in range(0, max(H, 1), h - 60):
                    page.evaluate(f"() => {{ const m = document.querySelector('[data-testid=\"stMain\"]'); if (m) m.scrollTop = {y}; window.scrollTo(0, {y}); }}")
                    time.sleep(0.35)
                    page.screenshot(path=str(OUT / f"{name}_{wkey}_{scheme}_{n:02d}.png"))
                    n += 1
                    if n >= 40:
                        break
                # 탭이 있으면 탭마다 눌러서 내용도 찍는다 (탭 내용은 눌러야 보임)
                tabs = page.locator('[role="tab"]')
                for ti in range(1, tabs.count()):
                    try:
                        tabs.nth(ti).click()
                        time.sleep(1.2)
                        tabs.nth(ti).scroll_into_view_if_needed()
                        time.sleep(0.4)
                        overlaps += [dict(o, tab=ti) for o in page.evaluate(JS_OVERLAP)]
                        page.screenshot(path=str(OUT / f"{name}_{wkey}_{scheme}_tab{ti}.png"))
                        page.mouse.wheel(0, h - 120)
                        time.sleep(0.4)
                        page.screenshot(path=str(OUT / f"{name}_{wkey}_{scheme}_tab{ti}b.png"))
                    except Exception as e:  # noqa: BLE001
                        print("탭 캡처 실패", ti, e)
                report.append({"page": name, "width": wkey, "scheme": scheme, "load_sec": round(load, 1),
                               "total_sec": round(time.time() - t0, 1), "height": H, "tiles": n,
                               "overlaps": overlaps, "overflow": overflow})
                print(f"{name:10} {wkey:>4} {scheme:5} load {load:5.1f}s  height {H:6}  tiles {n:2}  "
                      f"overlaps {len(overlaps)}  pageScrollW {overflow['pageScrollW']}/{overflow['W']}", flush=True)
            report.append({"page": "_console", "width": wkey, "scheme": scheme, "errors": sorted(set(errors))[:20]})
            ctx.close()
    browser.close()
json.dump(report, open(OUT / "report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장:", OUT / "report.json")
