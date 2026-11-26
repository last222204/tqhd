"""모든 페이지를 Streamlit AppTest 로 실행: 예외·경고·걸린 시간 기록.  사용: python qa/apptest_all.py"""
import json
import sys
import time
import traceback
import warnings
from pathlib import Path

sys.path.insert(0, ".")
from streamlit.testing.v1 import AppTest  # noqa: E402

ROOT = Path(".").resolve()
results = []


def scenario(name, setup=None, clicks=(), page="app.py", switch=None):
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        t = time.time()
        err = None
        try:
            at = AppTest.from_file(str(ROOT / page), default_timeout=300)
            if setup:
                setup(at)
            at.run()
            if switch:
                at.switch_page(switch)
                at.run()
            for c in clicks:
                c(at)
                at.run()
            if at.exception:
                err = " | ".join(e.value[:400] for e in at.exception)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}"
            at = None
        dt = time.time() - t
    warns = sorted({f"{x.category.__name__}: {str(x.message)[:160]} ({Path(x.filename).name}:{x.lineno})"
                    for x in w if "site-packages" not in x.filename or "streamlit" not in x.filename})
    info = {"name": name, "sec": round(dt, 1), "error": err, "warnings": warns}
    if at is not None:
        info["warnings_ui"] = [x.value[:200] for x in at.warning]
        info["errors_ui"] = [x.value[:200] for x in at.error]
        info["info_ui"] = [x.value[:200] for x in at.info]
    results.append(info)
    print(f"[{'❌' if err else '✅'}] {name}  {dt:.1f}s  {err or ''}"[:500], flush=True)
    return at


P = "views/"
scenario("오늘", switch=P + "today.py")
scenario("차트", switch=P + "charts.py")
scenario("연간 점검", switch=P + "review.py")
scenario("시뮬레이터 기본", switch=P + "simulator.py")
for k in range(7):
    scenario(f"시뮬레이터 프리셋 {k}", switch=P + "simulator.py",
             clicks=[lambda at, k=k: at.button(key=f"preset_{k}").click()])
scenario("시뮬레이터 모든 시기 평균", switch=P + "simulator.py",
         clicks=[lambda at: at.button(key="preset_avg").click()])
for rule in ["종료일 직접", "졸업 A: 전고점 졸업", "졸업 B: 목표 배수 졸업", "하락장 강제 청산", "무작위 청산"]:
    scenario(f"시뮬레이터 규칙 {rule}", setup=lambda at, r=rule: at.session_state.__setitem__("sim_rule", r),
             switch=P + "simulator.py")
scenario("시뮬레이터 검산 모드", setup=lambda at: at.session_state.__setitem__("sim_colab", True), switch=P + "simulator.py")
scenario("시뮬레이터 달러 기준 + 보유 유지",
         setup=lambda at: (at.session_state.__setitem__("sim_cur", "달러 기준 (환율 고정)"),
                           at.session_state.__setitem__("sim_final", "보유 유지 (세전 평가)")),
         switch=P + "simulator.py")
scenario("시뮬레이터 처음 0원", setup=lambda at: at.session_state.__setitem__("sim_init", 0), switch=P + "simulator.py")
scenario("시뮬레이터 적립 0원", setup=lambda at: at.session_state.__setitem__("sim_month", 0), switch=P + "simulator.py")
scenario("시뮬레이터 비교 대상 없음", setup=lambda at: at.session_state.__setitem__("sim_cmp", []), switch=P + "simulator.py")
scenario("청산 시나리오 기본(2000)", switch=P + "exits_lab.py")
for label in ["🎲 아무거나 한 번", "🔴 하락장 청산만 뽑기", "🟢 상승장 청산만 뽑기"]:
    scenario(f"청산 시나리오 주사위 {label}", switch=P + "exits_lab.py",
             clicks=[lambda at, l=label: next(b for b in at.button if b.label == l).click()])
scenario("청산 시나리오 보유 15~20년", setup=lambda at: at.session_state.__setitem__("lab_hold", (15.0, 20.0)),
         switch=P + "exits_lab.py")

Path("qa").mkdir(exist_ok=True)
json.dump(results, open("qa/apptest_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("저장: qa/apptest_results.json")
