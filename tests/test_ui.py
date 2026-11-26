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
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    rule = re.search(r"\.grid \.v \{[^}]*\}", css).group(0)
    assert "white-space: nowrap" in rule
    assert ".bb > .grid" in css and "grid-column: 1 / -1" in css          # 휴장 칸은 마스코트 아래 전체 폭


def test_gauges_are_plain_divs_6px():
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\.gb \{[^}]*height: 6px", css) and "border-radius: 3px" in css
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    assert "[5, 15, 50].forEach" in js and "조기 폐장" in js
