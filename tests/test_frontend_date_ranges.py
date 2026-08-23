from __future__ import annotations

from datetime import date

from frontend.date_ranges import resolve_date_range


def test_this_month():
    start, end = resolve_date_range("This Month", today=date(2026, 8, 23))
    assert start == date(2026, 8, 1)
    assert end == date(2026, 8, 23)


def test_last_month():
    start, end = resolve_date_range("Last Month", today=date(2026, 8, 5))
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_last_month_crosses_year_boundary():
    start, end = resolve_date_range("Last Month", today=date(2026, 1, 15))
    assert start == date(2025, 12, 1)
    assert end == date(2025, 12, 31)


def test_ytd():
    start, end = resolve_date_range("YTD", today=date(2026, 8, 23))
    assert start == date(2026, 1, 1)
    assert end == date(2026, 8, 23)


def test_last_12_months():
    start, end = resolve_date_range("Last 12 Months", today=date(2026, 8, 23))
    assert start == date(2025, 8, 23)
    assert end == date(2026, 8, 23)


def test_last_12_months_handles_leap_day():
    start, end = resolve_date_range("Last 12 Months", today=date(2028, 2, 29))
    assert start == date(2027, 2, 28)
    assert end == date(2028, 2, 29)
