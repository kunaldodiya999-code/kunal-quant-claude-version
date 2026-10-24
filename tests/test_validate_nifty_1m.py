from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from scripts.validate_nifty_1m import (
    MAX_CONSECUTIVE_MISSING,
    REGULAR_SESSION_END,
    REGULAR_SESSION_START,
    classify_day,
)


TZ = ZoneInfo("Asia/Kolkata")


def _session_timestamps(day: date) -> list[int]:
    start = datetime.combine(day, REGULAR_SESSION_START, tzinfo=TZ)
    end = datetime.combine(day, REGULAR_SESSION_END, tzinfo=TZ)
    return list(range(int(start.timestamp()), int(end.timestamp()) + 60, 60))


def _remove_minutes(timestamps: list[int], *minutes: str) -> list[int]:
    blocked = {
        int(datetime.combine(
            date(2024, 1, 2),
            time.fromisoformat(minute),
            tzinfo=TZ,
        ).timestamp())
        for minute in minutes
    }
    return [timestamp for timestamp in timestamps if timestamp not in blocked]


def test_three_consecutive_missing_candles_are_tolerated() -> None:
    day = date(2024, 1, 2)
    timestamps = _remove_minutes(
        _session_timestamps(day),
        "10:22",
        "10:23",
        "10:24",
    )

    classification, max_missing, _ = classify_day(day, timestamps, set(), set())

    assert MAX_CONSECUTIVE_MISSING == 3
    assert max_missing == 3
    assert classification == "KEEP"


def test_four_consecutive_missing_candles_exclude_day() -> None:
    day = date(2024, 1, 2)
    timestamps = _remove_minutes(
        _session_timestamps(day),
        "10:22",
        "10:23",
        "10:24",
        "10:25",
    )

    classification, max_missing, _ = classify_day(day, timestamps, set(), set())

    assert max_missing == 4
    assert classification == "EXCLUDE_EXCESSIVE_GAP"


def test_known_special_session_is_excluded() -> None:
    day = date(2024, 3, 2)
    timestamps = _session_timestamps(day)

    classification, _, _ = classify_day(day, timestamps, set(), set())

    assert classification == "EXCLUDE_SPECIAL_SESSION"


def test_invalid_ohlc_excludes_day() -> None:
    day = date(2024, 1, 2)
    timestamps = _session_timestamps(day)

    classification, _, _ = classify_day(
        day,
        timestamps,
        {timestamps[0]},
        set(),
    )

    assert classification == "EXCLUDE_INVALID_OHLC"
