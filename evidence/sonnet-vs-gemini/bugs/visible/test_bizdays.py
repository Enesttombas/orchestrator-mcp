from datetime import date
from bizdays import business_days

MON = date(2026, 1, 5)
NEXT_MON = date(2026, 1, 12)


def test_one_week():
    assert business_days(MON, NEXT_MON) == 5


def test_weekday_holiday():
    assert business_days(MON, NEXT_MON, [date(2026, 1, 7)]) == 4


def test_reversed_is_negative():
    assert business_days(NEXT_MON, MON) == -5


def test_end_is_exclusive():
    assert business_days(MON, MON) == 0
    assert business_days(MON, date(2026, 1, 6)) == 1
