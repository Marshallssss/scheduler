from __future__ import annotations

from datetime import date, timedelta


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def weighted_progress(values: list[tuple[float, float]]) -> float:
    """values: list of (progress, weight)."""
    if not values:
        return 0.0
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return 0.0
    return round(sum(progress * weight for progress, weight in values) / total_weight, 2)


def week_range(any_date: date) -> tuple[date, date]:
    monday = any_date - timedelta(days=any_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def month_range(any_date: date) -> tuple[date, date]:
    month_start = any_date.replace(day=1)
    if any_date.month == 12:
        next_month_start = any_date.replace(year=any_date.year + 1, month=1, day=1)
    else:
        next_month_start = any_date.replace(month=any_date.month + 1, day=1)
    month_end = next_month_start - timedelta(days=1)
    return month_start, month_end


def is_last_day_of_month(any_date: date) -> bool:
    _, month_end = month_range(any_date)
    return any_date == month_end
