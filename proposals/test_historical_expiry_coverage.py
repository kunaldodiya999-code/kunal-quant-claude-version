"""
Synthetic tests for historical NIFTY weekly expiry coverage logic.

Proposal-only. No database/API access.
"""

from __future__ import annotations

from datetime import date, timedelta

from diagnose_historical_expiry_coverage import expected_weekly_expiries


def build_week(start: date, missing: set[date] | None = None) -> list[date]:
    missing = missing or set()
    return [
        start + timedelta(days=i)
        for i in range(7)
        if start + timedelta(days=i) not in missing
    ]


def test_thursday_rule_before_change() -> None:
    trading = build_week(date(2025, 8, 25))
    result = expected_weekly_expiries(
        trading,
        date(2025, 8, 25),
        date(2025, 8, 31),
    )
    assert result == [date(2025, 8, 28)]


def test_tuesday_rule_after_change() -> None:
    trading = build_week(date(2025, 9, 1))
    result = expected_weekly_expiries(
        trading,
        date(2025, 9, 1),
        date(2025, 9, 7),
    )
    assert result == [date(2025, 9, 2)]


def test_holiday_uses_previous_trading_day() -> None:
    week = date(2026, 11, 23)
    trading = build_week(week, missing={date(2026, 11, 24)})
    result = expected_weekly_expiries(
        trading,
        date(2026, 11, 23),
        date(2026, 11, 29),
    )
    assert result == [date(2026, 11, 23)]


def main() -> None:
    tests = [
        test_thursday_rule_before_change,
        test_tuesday_rule_after_change,
        test_holiday_uses_previous_trading_day,
    ]
    for test in tests:
        test()
        print(f"[PASS] {test.__name__}")
    print("All historical-expiry coverage tests passed.")


if __name__ == "__main__":
    main()
