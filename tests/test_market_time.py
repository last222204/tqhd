"""적립일(17일 · 휴장일)과 서머타임 전환 주간의 한국 시간표."""
from datetime import date, datetime, timezone

import pytest

from t6 import market_time as mt


@pytest.mark.parametrize(
    "year, month, expected",
    [
        (2026, 3, date(2026, 3, 17)),    # 평일 화요일 → 그대로
        (2026, 1, date(2026, 1, 20)),    # 17 토, 18 일, 19 마틴루터킹 데이 → 20 화
        (2025, 2, date(2025, 2, 18)),    # 17 월 = 대통령의 날 휴장 → 18 화
        (2024, 2, date(2024, 2, 20)),    # 17 토, 19 대통령의 날 → 20 화
        (2026, 10, date(2026, 10, 19)),  # 17 토 → 19 월
        (2025, 5, date(2025, 5, 19)),    # 17 토 → 19 월
    ],
)
def test_contribution_date(year, month, expected):
    assert mt.contribution_date(year, month) == expected


def test_next_contribution_date():
    assert mt.next_contribution_date(date(2026, 11, 13)) == date(2026, 11, 17)
    # 적립일 당일이 마감된 뒤라면 다음 달
    assert mt.next_contribution_date(date(2026, 11, 17)) == date(2026, 12, 17)
    # 1월로 넘어감: 2027-01-17 일, 18 마틴루터킹 데이 → 19 화
    assert mt.next_contribution_date(date(2026, 12, 18)) == date(2027, 1, 19)


def _hm(dt):
    return (dt.month, dt.day, dt.hour, dt.minute)


def test_spring_dst_week_2026():
    # 미국 서머타임 시작: 2026-03-08(일)
    fri = mt.session_kst(date(2026, 3, 6))     # 겨울
    assert not fri.summer
    assert _hm(fri.open_kst) == (3, 6, 23, 30)
    assert _hm(fri.close_kst) == (3, 7, 6, 0)
    assert _hm(fri.after_end_kst) == (3, 7, 10, 0)
    mon = mt.session_kst(date(2026, 3, 9))     # 여름
    assert mon.summer
    assert _hm(mon.open_kst) == (3, 9, 22, 30)
    assert _hm(mon.close_kst) == (3, 10, 5, 0)
    assert _hm(mon.after_start_kst) == (3, 10, 5, 0)
    assert _hm(mon.after_end_kst) == (3, 10, 9, 0)


def test_fall_dst_week_2026():
    # 미국 서머타임 끝: 2026-11-01(일)
    fri = mt.session_kst(date(2026, 10, 30))
    assert fri.summer and _hm(fri.open_kst) == (10, 30, 22, 30) and _hm(fri.after_end_kst) == (10, 31, 9, 0)
    mon = mt.session_kst(date(2026, 11, 2))
    assert not mon.summer and _hm(mon.open_kst) == (11, 2, 23, 30) and _hm(mon.close_kst) == (11, 3, 6, 0)


def test_early_close_day_after_thanksgiving():
    s = mt.session_kst(date(2026, 11, 27))     # 13:00 ET 조기 폐장
    assert s.early_close
    assert _hm(s.close_kst) == (11, 28, 3, 0)
    assert _hm(s.after_end_kst) == (11, 28, 7, 0)


def test_last_completed_session():
    kst = mt.KST
    # 토요일 05:59 KST (겨울) → 금요일 장은 아직 마감 전 → 목요일
    assert mt.last_completed_session(datetime(2026, 11, 14, 5, 59, tzinfo=kst)) == date(2026, 11, 12)
    # 토요일 06:00 KST → 금요일 마감
    assert mt.last_completed_session(datetime(2026, 11, 14, 6, 0, tzinfo=kst)) == date(2026, 11, 13)
    # 여름: 05:00 KST 에 마감
    assert mt.last_completed_session(datetime(2026, 7, 9, 5, 0, tzinfo=kst)) == date(2026, 7, 8)
    # 휴장일(추수감사절 2026-11-26) 다음 아침에도 수요일 종가
    assert mt.last_completed_session(datetime(2026, 11, 27, 9, 0, tzinfo=kst)) == date(2026, 11, 25)
    with pytest.raises(ValueError):
        mt.last_completed_session(datetime(2026, 1, 1))
    assert mt.last_completed_session(datetime(2026, 11, 14, 1, 0, tzinfo=timezone.utc)) == date(2026, 11, 13)
