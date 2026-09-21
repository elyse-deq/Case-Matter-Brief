from datetime import date

from matter_brief.deadlines import add_days, compute_due, federal_holidays, is_business_day, roll_forward


def test_thirty_days_from_service():
    data = {"trigger_date": "2026-08-12", "days": 30}
    assert compute_due(data) == date(2026, 9, 11)  # a Friday


def test_extension_moves_the_due_date():
    data = {"trigger_date": "2026-08-12", "days": 30, "extension_days": 14}
    assert compute_due(data) == date(2026, 9, 25)


def test_weekend_rolls_to_monday():
    # 2026-08-13 + 30 days is Saturday, September 12.
    assert compute_due({"trigger_date": "2026-08-13", "days": 30}) == date(2026, 9, 14)


def test_holiday_rolls_forward():
    # 2026-08-08 + 30 days is Labor Day, Monday September 7.
    assert compute_due({"trigger_date": "2026-08-08", "days": 30}) == date(2026, 9, 8)


def test_fixed_court_date_is_not_rolled():
    assert compute_due({"date": "2027-01-29"}) == date(2027, 1, 29)


def test_business_day_counting_skips_weekends():
    assert add_days(date(2026, 9, 11), 1, "business") == date(2026, 9, 14)


def test_observed_holidays():
    # July 4, 2026 is a Saturday, so Friday July 3 is observed.
    assert date(2026, 7, 3) in federal_holidays(2026)
    assert not is_business_day(date(2026, 7, 3))
    assert roll_forward(date(2026, 7, 3)) == date(2026, 7, 6)


def test_incomplete_record_has_no_due_date():
    assert compute_due({"label": "Something"}) is None
