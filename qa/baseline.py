"""다듬기 전·후 숫자가 똑같은지 비교하기 위한 기준값 저장.

사용: python qa/baseline.py qa/baseline_before.json
      python qa/baseline.py qa/baseline_after.json --compare qa/baseline_before.json
"""
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from t6 import store  # noqa: E402
from t6.sim import data, engine, exits, lab, metrics  # noqa: E402

S = [engine.UMBRELLA, "QQQ", "QLD", "TQQQ"]


def r(x):
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), 10)


def main(out, compare=None):
    store.init_db()
    m = data.build()
    pay = data.pay_mask(m, 17)
    res = {}

    # 2차 검산: 실제 상품 5년, 시작 월 141개 (검산 모드 + 현실 모드)
    wins = []
    for y in range(2010, 2022):
        for mo in range(1, 13):
            if (2010, 3) <= (y, mo) <= (2021, 11):
                a = m.i_on_or_after(f"{y}-{mo:02d}-01")
                wins.append((a, m.i_on_or_before(m.idx[a] + pd.DateOffset(years=5))))
    for colab in (True, False):
        for s in S:
            mult = [engine.run(m, s, engine.Params(start=m.idx[a], end=m.idx[b], colab=colab), pay, (a, b)).multiple
                    for a, b in wins]
            res[f"5y_{'colab' if colab else 'real'}_{s}"] = [r(x) for x in mult]

    # 3차 검산: 졸업 A·B (검산 모드)
    p = engine.Params(start=m.idx[0], end=m.idx[1], colab=True)
    for kind in ("ath", "target"):
        df = exits.scan_rule(m, S, p, exits.Rule(kind, 5, 15, 2.0), exits.Thresholds())
        for s in S:
            g = df[df["strategy"] == s]
            res[f"grad_{kind}_{s}"] = {c: [r(x) for x in g[c]] for c in ("multiple", "irr", "low", "years")}

    # 단일 시뮬레이션 상세 (현실 모드, 기본 조건) — 요약·연도별·피신 기록
    pr = engine.Params(start=pd.Timestamp("2021-11-15"), end=pd.Timestamp("2026-11-13"))
    a, b = engine.window(m, pr.start, pr.end)
    for s in S:
        rr = engine.run(m, s, pr, pay, (a, b))
        sm = metrics.summary(rr)
        res[f"single_{s}"] = {k: (r(v) if isinstance(v, (int, float, np.floating)) else str(v)) for k, v in sm.items()}
        res[f"single_yearly_{s}"] = metrics.yearly(rr).round(8).astype(str).values.tolist()
    res["single_refuge"] = metrics.refuge_records(m, a, b).round(10).astype(str).values.tolist()

    # 무작위 청산 300개 (시드 0)
    d = lab.draw(m, 300, 0, 3, 10, False)
    df = lab.simulate(m, S, engine.Params(start=m.idx[0], end=m.idx[1]), d, exits.Thresholds())
    res["lab"] = df.sort_values(["draw", "strategy"])[["multiple", "irr", "cls"]].astype(str).values.tolist()

    json.dump(res, open(out, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"저장: {out} ({len(res)}개 항목)")

    if compare:
        old = json.load(open(compare, encoding="utf-8"))
        diff = [k for k in old if old[k] != res.get(k)]
        print("비교:", "완전히 같음 ✅" if not diff else f"다름 ❌ {diff}")


if __name__ == "__main__":
    args = sys.argv[1:]
    cmp_ = args[args.index("--compare") + 1] if "--compare" in args else None
    main(args[0], cmp_)
