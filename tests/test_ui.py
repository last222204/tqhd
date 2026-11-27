"""다듬기 지시서: 오늘 할 일 문구(직전 상태 → 오늘 상태), 배지, 그리고 '하지 말 것' (굵기·그림자·그라데이션·애니메이션·둥글기)."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ui():
    from py_mini_racer import MiniRacer
    ctx = MiniRacer()
    ctx.eval((ROOT / "assets" / "core.js").read_text(encoding="utf-8"))
    ctx.eval((ROOT / "assets" / "ui.js").read_text(encoding="utf-8"))

    def call(expr):
        return json.loads(ctx.eval(f"JSON.stringify({expr})"))
    return call


def S(s, w):
    return {"state": s, "weight": w}


# 지시서 4절 ① 표 + 양방향 비중 변화
@pytest.mark.parametrize("prev, cur, text", [
    (S("day", 100), S("day", 100), "보유 유지"),          # 낮 · 이미 보유
    (S("night", 0), S("day", 100), "TQQQ 전액 매수"),      # 낮 · 현금에서 전환
    (S("night", 0), S("night", 0), "할 일 없음"),          # 밤 · 현금
    (S("day", 100), S("night", 0), "전량 매도"),           # 밤 · 보유 중
    (S("night", 0), S("hunt", 50), "TQQQ 절반 매수"),      # 사냥 50% 진입
    (S("night", 0), S("hunt", 100), "TQQQ 전액 매수"),     # 사냥 100% 진입
    (S("hunt", 100), S("hunt", 50), "절반 매도"),          # 사냥 → 50% 로 축소
    (S("hunt", 50), S("night", 0), "전량 매도"),           # 사냥 청산
    (S("hunt", 100), S("night", 0), "전량 매도"),
    (S("hunt", 50), S("hunt", 100), "TQQQ 절반 추가 매수"),
    (S("hunt", 50), S("hunt", 50), "보유 유지"),
    (S("day", 100), S("hunt", 50), "절반 매도"),           # 낮 → 밤 되는 날 바로 사냥 50%
    (S("day", 100), S("hunt", 100), "보유 유지"),
    (S("hunt", 50), S("day", 100), "TQQQ 절반 추가 매수"),  # 사냥 중 선 회복 → 낮
    (S("hunt", 100), S("day", 100), "보유 유지"),
])
def test_todo_from_transition(ui, prev, cur, text):
    assert ui(f"TQHD_UI.todo({json.dumps(prev)}, {json.dumps(cur)}).text") == text


def ms(y, mo, d, h, mi=0):
    return int(datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


def quotes(t, qqq):
    q = {"price": qqq, "time": t / 1000}
    return {"fetched_at": t / 1000, "quotes": {"QQQ": q, "TQQQ": {"price": 40.0, "time": t / 1000},
                                                "NQ": {"price": 26300.0, "time": t / 1000}, "USDKRW": {"price": 1345.0, "time": t / 1000}}}


def view(ui, state, q, now):
    return ui(f"(function(){{var v=TQHD.buildView({json.dumps(state)},{json.dumps(q)},{now});"
              f"return {{line: TQHD_UI.todayLine(v), badge: TQHD_UI.badge(v), mode: v.mode}};}})()")


def test_today_line_by_mode(ui, state):
    live = ms(2026, 11, 27, 16, 0)
    assert view(ui, state, quotes(live - 20_000, 611.0), live)["line"]["text"] == "TQQQ 절반 매수"   # 밤 → 사냥 50%
    assert view(ui, state, quotes(live - 20_000, 640.0), live)["line"]["text"] == "할 일 없음"
    assert view(ui, state, None, live)["line"]["text"] == "실시간 없음 · 판단 보류"
    hol = ms(2026, 11, 26, 15, 0)
    r = view(ui, state, quotes(hol, 640.0), hol)
    assert r["line"]["text"] == "휴장 · 대기" and r["badge"] == {"emoji": "🏈", "text": "추수감사절 휴장"}
    stale = ms(2026, 12, 1, 15, 0)
    r = view(ui, state, quotes(stale, 640.0), stale)
    assert r["line"]["text"] == "데이터 멈춤 · 판단 보류" and r["badge"]["emoji"] == "⚠️"
    r = view(ui, state, None, live)
    assert r["badge"]["emoji"] == "🔌"


# ── 5절 '하지 말 것' ─────────────────────────────
CSS = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_no_heavy_weights_shadows_gradients_animation():
    weights = [int(w) for w in re.findall(r"font-weight:\s*(\d+)", CSS)]
    assert weights and max(weights) <= 600
    for bad in ("gradient", "box-shadow", "text-shadow", "animation", "transition", "@keyframes"):
        assert bad not in CSS, bad
    radii = [int(r) for r in re.findall(r"border-radius:\s*(\d+)px", CSS)]
    assert max(radii) <= 16


def test_single_font_with_fallback():
    assert "pretendardvariable-dynamic-subset.css" in HTML and "pretendard@v1.3.9" in HTML
    assert "--font: 'Pretendard Variable', Pretendard," in CSS and "system-ui" in CSS and "sans-serif" in CSS
    assert CSS.count("font-family") == 1


def test_mascot_slot_hidden_and_no_loading_text():
    assert '<picture class="mascot" id="mascot" hidden>' in HTML and '<img id="mascotImg" alt="" width="64" height="64"' in HTML
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'addEventListener("error"' in js and "hidden = true" in js and "display: none" not in js
    assert "불러오는 중" not in HTML and "불러오는 중" not in (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert "판정은 종가 기준 · 장중은 참고" in HTML


def test_no_service_worker():
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert "serviceWorker" not in js and "serviceWorker" not in HTML


def test_gap_number_and_change_stay_on_one_line():
    """휴장 갭 카드(맨 아래): 숫자와 등락률은 한 줄, 정규장 중에는 회색 비활성."""
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.gp \.v \{[^}]*\}", css).group(0)
    assert "white-space: nowrap" in rule
    off = re.search(r"\.gapc\.off \{[^}]*\}", css).group(0)
    assert "opacity: 0.45" in off and "grayscale(1)" in off
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert '"card gapc" + (off ? " off" : "")' in js and "정규장 중 · 휴장 때만 씀" in js


def test_section_order():
    """① 가격 → ② 지금 상태 → ③ 기준선 → ④ 흐름 → ⑤ 휴장 갭 → ⑥ 각오. 따로 있던 TQQQ 카드는 없어짐."""
    order = [HTML.index(f'id="{k}"') for k in ("prices", "banner", "card", "hist", "gap", "resolve")]
    assert order == sorted(order)
    assert 'id="tqqq"' not in HTML
    assert HTML.count('class="sec"') == 6


def test_tqqq_always_before_qqq():
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    line = next(l for l in js.splitlines() if 'priceCell("TQQQ"' in l)            # ① 가격 두 칸
    assert line.index('priceCell("TQQQ"') < line.index('priceCell("QQQ"')
    assert "<span></span><span>TQQQ</span><span>QQQ</span>" in js                  # ③ 표 머리
    box = next(l for l in js.splitlines() if 'pline("TQQQ"' in l)                   # ③ 바뀌는 가격 상자
    assert box.index('pline("TQQQ"') < box.index('pline("QQQ"')
    row = next(l for l in js.splitlines() if "pc(r.tqqq" in l)                      # ③ 표 줄
    assert row.index("pc(r.tqqq") < row.index("pc(r.price")
    gap = js.index("예상 시가 TQQQ")                                               # ⑤ 휴장 갭
    assert gap < js.index("예상 시가 QQQ")


def test_card_export_is_prev_close_basis(ui, state):
    """휴장 때 기준선은 선물 예상 시가가 아니라 확정 종가 기준 (T.card(state, null))."""
    c = ui(f"TQHD.card({json.dumps(state)}, null)")
    assert c["basisIsPrev"] and c["ref"] is None and c["prev"] == state["qqq_prev_close"]
    assert [r["key"] for r in c["rows"]] == ["sma50", "sma200", "hunt_half", "hunt_full", "hunt_exit"]


def test_basis_toggle_is_safe():
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert '"tqhd.basis"' in js and js.count("try {") >= 2 and "catch (e)" in js


def test_gauges_are_plain_divs_6px():
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.gb \{[^}]*height: 6px", css) and "border-radius: 3px" in css
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert "[5, 15, 50].forEach" in js and "조기 폐장" in js


# ── 기준선 차트 ─────────────────────────────────
CHART = (ROOT / "assets" / "chart.js").read_text(encoding="utf-8")


def test_chart_library_pinned_with_attribution():
    assert 'var VERSION = "5.2.1"' in CHART and "lightweight-charts@\" + VERSION + \"/dist/" in CHART
    assert 'SRI = "sha384-' in CHART and "s.integrity = SRI" in CHART
    assert "attributionLogo: true" in CHART


def test_chart_touch_and_panes():
    assert "vertTouchDrag: false" in CHART and "horzTouchDrag: true" in CHART and "pinch: true" in CHART
    assert "panes[1].setHeight(100)" in CHART and "minValue: 0, maxValue: 100" in CHART
    live = CHART[CHART.index("function live(c)"):CHART.index("function applyRange")]
    assert ".update(" in live and "setData" not in live                    # 30초 갱신은 update 로만


def test_chart_failure_falls_back_to_numbers():
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'onFail: chartFail' in js and '$("nums").open = true' in js and '$("chartBox").hidden = true' in js
    assert '<details id="nums" class="nums"><summary>숫자로 보기</summary>' in HTML
    assert HTML.index("assets/chart.js") < HTML.index("assets/app.js")


def test_top_prices_come_only_from_best_prices():
    """맨 위 가격 칸은 core 의 bestPrices 결과만 그린다 (판정용 buildView 와 따로)."""
    app = read("assets/app.js")
    body = app.split("function prices()")[1].split("// ── ② 지금 상태")[0]
    assert "T.bestPrices(state, quotes, now())" in body
    assert "evaluate" not in body and "v.live" not in body
    for word in ("실시간", "프리장", "애프터장", "선물 추정", "확정 종가", "정규장 종가", "≈"):
        assert word in app
    css = read("assets/style.css")
    assert ".num-big.dim" in css and ".pbase" in css


def test_cache_version_same_everywhere():
    html = read("index.html")
    vs = set(re.findall(r"\?v=(\d+)", html))
    assert len(vs) == 1, vs


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")
