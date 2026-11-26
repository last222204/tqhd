"""'오늘' 화면 계산: 교체일 할 일과 시간 안내 (서머타임 시작 주말을 걸쳐서)."""
from datetime import date, datetime

import pandas as pd

from t6 import market_time as mt
from t6 import today
from t6.strategy import signal_frame


def _frame_ending(last_day: date, prices):
    s = mt.sessions()
    end = s.searchsorted(pd.Timestamp(last_day), side="right")
    idx = s[end - len(prices):end]
    p = pd.Series(prices, index=idx, dtype=float)
    return pd.DataFrame({"open": p, "high": p, "low": p, "close": p, "adj_close": p})


def _switch_view(now):
    px = _frame_ending(date(2026, 3, 6), [100.0] * 220 + [90.0])   # 금요일 종가에 둘 다 아래로
    return today.build(signal_frame(px), signal_frame(px, "close"), now)


def test_switch_day_after_hours_window():
    v = _switch_view(datetime(2026, 3, 7, 7, 0, tzinfo=mt.KST))
    assert v.as_of == date(2026, 3, 6)
    assert v.signal == "SGOV" and v.prev_signal == "TQQQ" and v.switched
    assert v.steps[0] == "TQQQ 전량 매도 (지정가)"
    assert v.steps[1] == "매도 대금은 현금(달러)으로 보유"          # 피신 자금은 현금으로 (화면 표기만)
    assert v.when[0] == "1순위: 애프터마켓 3/7(토) 06:00 ~ 10:00"
    # 다음 정규장은 서머타임이 시작된 월요일 → 22:30
    assert v.when[1] == "못 하면: 그날 밤 정규장 3/9(월) 22:30 ~ 3/10(화) 05:00에서 마무리"


def test_switch_day_after_hours_missed():
    v = _switch_view(datetime(2026, 3, 7, 11, 0, tzinfo=mt.KST))
    assert v.when[0].startswith("애프터마켓은 끝났습니다")
    assert v.when[1] == "지금 할 일: 정규장 3/9(월) 22:30 ~ 3/10(화) 05:00에서 마무리"


def test_no_switch_and_next_contribution():
    px = _frame_ending(date(2026, 11, 13), [100.0] * 230)
    v = today.build(signal_frame(px), signal_frame(px, "close"), datetime(2026, 11, 14, 9, 0, tzinfo=mt.KST))
    assert not v.switched and v.steps == []
    assert v.next_contribution == date(2026, 11, 17)
    assert v.next_session.session == date(2026, 11, 16)
    assert v.next_judgement_kst.hour == 6
