from datetime import date
from bizdays import business_days


def test_weekend_holiday_ignored():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 1, 10)]) == 5


def test_duplicate_holiday_counts_once():
    h = date(2026, 1, 7)
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [h, h]) == 4


def test_friday_to_monday():
    assert business_days(date(2026, 1, 9), date(2026, 1, 12)) == 1


def test_saturday_to_monday():
    assert business_days(date(2026, 1, 10), date(2026, 1, 12)) == 0


def test_three_weeks():
    assert business_days(date(2026, 1, 5), date(2026, 1, 26)) == 15
    assert business_days(date(2026, 1, 5), date(2026, 1, 26), [date(2026, 1, 6), date(2026, 1, 20)]) == 13


def test_holiday_on_end_not_counted():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 1, 12)]) == 5


def test_holiday_outside_range():
    assert business_days(date(2026, 1, 5), date(2026, 1, 12), [date(2026, 2, 2)]) == 5


def test_reversed_with_holiday():
    assert business_days(date(2026, 1, 12), date(2026, 1, 5), [date(2026, 1, 7)]) == -4
