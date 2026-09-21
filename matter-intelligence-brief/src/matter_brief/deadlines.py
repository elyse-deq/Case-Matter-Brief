"""Deterministic deadline arithmetic.

No model ever computes a due date. Extractors capture the trigger date and the
period; this module does the math, the same way every time.

The holiday and roll-forward rules are a simplified illustration (US federal
holidays, roll to the next business day). Real deadlines depend on the governing
court rules, so treat every computed date as something a lawyer verifies.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Any


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    first_of_next = date(year + (month == 12), (month % 12) + 1, 1)
    last = first_of_next - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:  # Saturday, observed Friday
        return d - timedelta(days=1)
    if d.weekday() == 6:  # Sunday, observed Monday
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=None)
def federal_holidays(year: int) -> frozenset[date]:
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4),
             date(year, 11, 11), date(year, 12, 25)]
    holidays = {
        _nth_weekday(year, 1, 0, 3),   # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),   # Washington's Birthday
        _last_weekday(year, 5, 0),     # Memorial Day
        _nth_weekday(year, 9, 0, 1),   # Labor Day
        _nth_weekday(year, 10, 0, 2),  # Columbus Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
    }
    for d in fixed:
        holidays.add(d)
        holidays.add(_observed(d))
    return frozenset(holidays)


def is_business_day(d: date) -> bool:
    if d.weekday() >= 5:
        return False
    # A January 1 that falls on Saturday is observed on the prior December 31.
    return d not in federal_holidays(d.year) and d not in federal_holidays(d.year + 1)


def roll_forward(d: date) -> date:
    while not is_business_day(d):
        d += timedelta(days=1)
    return d


def add_days(start: date, days: int, day_type: str = "calendar") -> date:
    if day_type == "calendar":
        return start + timedelta(days=days)
    if day_type == "business":
        current, remaining = start, days
        while remaining > 0:
            current += timedelta(days=1)
            if is_business_day(current):
                remaining -= 1
        return current
    raise ValueError(f"unknown day_type: {day_type!r}")


def compute_due(data: dict[str, Any]) -> date | None:
    """Due date for a deadline record, or None if it cannot be computed.

    A record is either fixed (`date`, set by a court order) or rule-based
    (`trigger_date` + `days`). Agreed extensions are added afterward.
    """
    if data.get("date"):
        due = date.fromisoformat(data["date"])
    elif data.get("trigger_date") and data.get("days") is not None:
        raw = add_days(date.fromisoformat(data["trigger_date"]), int(data["days"]),
                       data.get("day_type", "calendar"))
        due = roll_forward(raw)
    else:
        return None
    extension = int(data.get("extension_days", 0) or 0)
    if extension:
        due = roll_forward(due + timedelta(days=extension))
    return due


def days_remaining(due: date, as_of: date) -> int:
    return (due - as_of).days
