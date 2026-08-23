from __future__ import annotations

from datetime import date, timedelta

PRESETS = ["This Month", "Last Month", "YTD", "Last 12 Months", "Custom"]


def _last_month(today: date) -> tuple[date, date]:
    first_of_this_month = today.replace(day=1)
    last_day_prev_month = first_of_this_month - timedelta(days=1)
    return last_day_prev_month.replace(day=1), last_day_prev_month


def resolve_date_range(preset: str, today: date) -> tuple[date, date]:
    """Resolve an Overview date-range preset to a concrete (start, end) pair."""
    if preset == "This Month":
        return today.replace(day=1), today
    if preset == "Last Month":
        return _last_month(today)
    if preset == "YTD":
        return today.replace(month=1, day=1), today
    if preset == "Last 12 Months":
        try:
            start = today.replace(year=today.year - 1)
        except ValueError:  # today is Feb 29 and one year back isn't a leap year
            start = today.replace(year=today.year - 1, day=28)
        return start, today
    # "Custom" — sensible initial value before the user picks their own range via date_input.
    return today.replace(day=1), today
