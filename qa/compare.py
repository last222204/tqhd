"""고치기 전·후 캡처를 나란히 붙인 비교 그림 만들기.  사용: python qa/compare.py"""
from pathlib import Path

from playwright.sync_api import sync_playwright

Q = Path("qa/shots").resolve()
PAIRS = [
    ("1_QQQ와신호_데스크톱", "시뮬레이터 › QQQ와 신호 (데스크톱·어두운 화면)", "simulator_1440_dark_06", "simulator_1440_dark_tab3"),
    ("2_차트QQQ_데스크톱", "차트 › QQQ 일봉 (데스크톱·어두운 화면)", "charts_1440_dark_00", "charts_1440_dark_00"),
    ("3_계좌차트_휴대폰", "시뮬레이터 › 계좌 차트 (휴대폰)", "simulator_390_light_04", "simulator_390_light_03"),
    ("4_오늘_휴대폰", "오늘 (휴대폰·어두운 화면)", "today_390_dark_00", "today_390_dark_00"),
    ("5_피신손익_데스크톱", "차트 › 피신 기간별 손익 (진행 중 처리)", "charts_1440_dark_01", "charts_1440_dark_01"),
    ("6_청산분포_데스크톱", "청산 시나리오 › 분포 차트", "exits_lab_1440_light_02", "exits_lab_1440_light_02"),
]
HTML = """<html><head><meta charset='utf-8'><style>
body{{margin:0;padding:16px;background:#f4f4f2;font-family:'Malgun Gothic',sans-serif}}
h2{{margin:0 0 10px 0;font-size:20px}} .row{{display:flex;gap:16px;align-items:flex-start}}
.col{{flex:1}} .col b{{display:block;margin-bottom:6px;font-size:16px}} img{{width:100%;border:1px solid #ccc}}
</style></head><body><h2>{title}</h2><div class='row'>
<div class='col'><b>고치기 전</b><img src='{before}'></div>
<div class='col'><b>고친 뒤</b><img src='{after}'></div></div></body></html>"""

out = Path("qa/비교")
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    b = pw.chromium.launch()
    for fname, title, bf, af in PAIRS:
        mobile = "_390_" in bf
        page = b.new_page(viewport={"width": 900 if mobile else 1800, "height": 600})
        html = out / "_tmp.html"
        html.write_text(HTML.format(title=title, before=(Q / "before" / f"{bf}.png").as_uri(),
                                    after=(Q / "after" / f"{af}.png").as_uri()), encoding="utf-8")
        page.goto(html.resolve().as_uri())
        page.wait_for_timeout(500)
        page.screenshot(path=str(out / f"{fname}.png"), full_page=True)
        page.close()
    (out / "_tmp.html").unlink()
    b.close()
print("저장:", sorted(p.name for p in out.glob("*.png")))
