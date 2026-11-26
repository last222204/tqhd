"""빈 상태 점검: (1) 시세가 하나도 없고 받기도 실패, (2) 시세가 며칠 오래됐고 받기 실패, (3) 시뮬레이션 결과 0개."""
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")
from streamlit.testing.v1 import AppTest  # noqa: E402

from t6 import refresh, store  # noqa: E402
from t6.config import DB_PATH  # noqa: E402


class Down:
    name = "fake"

    def fetch_daily(self, *a, **k):
        raise ConnectionError("인터넷 끊김 (점검용)")


refresh.get_source = lambda: Down()
refresh.get_fred_source = lambda: Down()
ROOT = Path(".").resolve()
PAGES = ["today", "charts", "simulator", "exits_lab", "review"]


def run_all(label):
    for pg in PAGES:
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=300)
        at.run()
        at.switch_page(f"views/{pg}.py")
        at.run()
        exc = [e.value[:300] for e in at.exception]
        msgs = [x.value[:120] for x in list(at.info) + list(at.error) + list(at.warning)]
        md = [m.value[:120] for m in at.markdown if "t6-stale" in m.value or "아직 받은" in m.value]
        print(f"[{label}] {pg:10} {'❌ ' + str(exc) if exc else '✅'}  안내: {msgs[:3]} {md[:1]}")


tmp = Path(tempfile.mkdtemp())
# (1) 빈 DB
store.DB_PATH = tmp / "empty.db"
store.init_db()
run_all("빈 DB")

# (2) 오래된 시세 (마지막 3거래일 지움)
stale = tmp / "stale.db"
shutil.copy(DB_PATH, stale)
con = sqlite3.connect(stale)
con.execute("DELETE FROM prices WHERE symbol='QQQ' AND date >= '2026-11-11'")
con.execute("DELETE FROM fetch_log")
con.commit(); con.close()
store.DB_PATH = stale
run_all("오래된 시세")

# (3) 시뮬레이션 결과 0개: 실제 상품 구간에서 보유 18~20년 (데이터는 16.7년뿐)
store.DB_PATH = DB_PATH
at = AppTest.from_file(str(ROOT / "views/exits_lab.py"), default_timeout=300)
at.session_state["lab_hold"] = (18.0, 20.0)
at.run()
print("[결과 0개] 청산 시나리오 보유 18~20년:", "❌ " + str([e.value[:200] for e in at.exception]) if at.exception else "✅",
      [x.value[:120] for x in at.error])
at = AppTest.from_file(str(ROOT / "views/simulator.py"), default_timeout=300)
import datetime as dt  # noqa: E402
at.session_state["sim_start"] = dt.date(2026, 10, 1)
at.session_state["sim_avg"] = True
at.session_state["sim_years"] = 20
at.run()
print("[결과 0개] 시뮬레이터 모든 시기 평균 20년:", "❌ " + str([e.value[:200] for e in at.exception]) if at.exception else "✅",
      [x.value[:120] for x in at.info])
shutil.rmtree(tmp, ignore_errors=True)
