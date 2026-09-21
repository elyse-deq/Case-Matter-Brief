"""Small date helpers shared by the extractor, validator, and renderer."""
from __future__ import annotations

import re
from datetime import date

MONTHS = [
    "January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December",
]
_MONTH_NUM = {name: i for i, name in enumerate(MONTHS, start=1)}

_LONG = re.compile(r"\b(" + "|".join(MONTHS) + r") (\d{1,2}), (\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

LONG_DATE_PATTERN = r"((?:" + "|".join(MONTHS) + r") \d{1,2}, \d{4})"


def parse_long_date(text: str) -> date:
    """Parse 'August 12, 2026' into a date."""
    m = _LONG.fullmatch(text.strip())
    if not m:
        raise ValueError(f"not a long-form date: {text!r}")
    return date(int(m.group(3)), _MONTH_NUM[m.group(1)], int(m.group(2)))


def dates_in_text(text: str) -> set[date]:
    """Every date written as 'Month D, YYYY' or 'YYYY-MM-DD' in the text."""
    found: set[date] = set()
    for m in _LONG.finditer(text):
        try:
            found.add(date(int(m.group(3)), _MONTH_NUM[m.group(1)], int(m.group(2))))
        except ValueError:
            continue
    for m in _ISO.finditer(text):
        try:
            found.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            continue
    return found


def fmt(d: date | None) -> str:
    """'Sep 11, 2026 (Fri)'."""
    if d is None:
        return "unknown"
    return f"{d:%b} {d.day}, {d.year} ({d:%a})"
