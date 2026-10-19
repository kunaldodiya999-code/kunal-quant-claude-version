from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH, TIMEZONE
from market_data.resampling import Candle, aggregate_day


SYMBOL = "NSE:NIFTY50-INDEX"
RESOLUTION_1M = "1"
SOURCE = "FYERS_HISTORY"
MARKET_TZ = ZoneInfo(TIMEZONE)

SESSION_START = time(9, 15)
SESSION_END = time(15, 29)
MAX_CONSECUTIVE_MISSING = 3
SPECIAL_SESSION_DATES = frozenset(
    {
        date(2021, 11, 4),
        date(2024, 3, 2),
        date(2024, 5, 18),
    }
)


def load_candles(connection: sqlite3.Connection) -> list[Candle]:
    rows = connection.execute(
        """
        SELECT c.timestamp, c.open, c.high, c.low, c.close,
               c.volume, c.open_interest
        FROM candles AS c
        JOIN instruments AS i ON i.id = c.instrument_id
        WHERE i.broker = 'FYERS'
          AND i.symbol = ?
          AND c.resolution = ?
          AND c.source = ?
        ORDER BY c.timestamp
        """,
        (SYMBOL, RESOLUTION_1M, SOURCE),
    ).fetchall()
    return [Candle(*row) for row in rows]


def session_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, SESSION_START, tzinfo=MARKET_TZ)
    end = datetime.combine(day, SESSION_END, tzinfo=MARKET_TZ)
    return int(start.timestamp()), int(end.timestamp())


def classify_source_days(candles: list[Candle]) -> dict[date, str]:
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        grouped[datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date()].append(candle)

    classifications: dict[date, str] = {}
    for day, day_candles in grouped.items():
        if day in SPECIAL_SESSION_DATES or day.weekday() >= 5:
            classifications[day] = "EXCLUDE_SPECIAL_SESSION"
            continue

        start, end = session_bounds(day)
        regular = [c for c in day_candles if start <= c.timestamp <= end]
        if len(regular) != len(day_candles):
            classifications[day] = "EXCLUDE_NON_REGULAR_SESSION"
            continue

        invalid = any(not (c.low <= c.open <= c.high and c.low <= c.close <= c.high) for c in regular)
        if invalid:
            classifications[day] = "EXCLUDE_INVALID_OHLC"
            continue

        non_positive = any(
            min(c.open, c.high, c.low, c.close) <= 0 for c in regular
        )
        if non_positive:
            classifications[day] = "EXCLUDE_NON_POSITIVE_PRICE"
            continue

        actual = {c.timestamp for c in regular}
        expected = set(range(start, end + 60, 60))
        missing = sorted(expected - actual)

        max_run = 0
        run = 0
        previous = None
        for timestamp in missing:
            run = run + 1 if previous is not None and timestamp == previous + 60 else 1
            max_run = max(max_run, run)
            previous = timestamp

        classifications[day] = (
            "EXCLUDE_EXCESSIVE_GAP"
            if max_run > MAX_CONSECUTIVE_MISSING
            else "KEEP"
        )

    return classifications


def derive(candles: list[Candle], minutes: int) -> list:
    classifications = classify_source_days(candles)
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        day = datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date()
        if classifications.get(day) == "KEEP":
            grouped[day].append(candle)

    result = []
    for day in sorted(grouped):
        result.extend(aggregate_day(grouped[day], minutes))
    return result


def main() -> None:
    connection = sqlite3.connect(DATABASE_PATH)
    try:
        candles = load_candles(connection)
    finally:
        connection.close()

    classifications = classify_source_days(candles)
    counts = Counter(classifications.values())

    print("=" * 80)
    print("KUNAL QUANT — NIFTY DERIVED 3M / 5M DATA VALIDATION")
    print("=" * 80)
    print(f"Database rows : {len(candles):,}")
    print(f"KEEP days     : {counts.get('KEEP', 0):,}")
    print(f"Excluded days : {sum(v for k, v in counts.items() if k != 'KEEP'):,}")
    print()

    for minutes in (3, 5):
        bars = derive(candles, minutes)
        complete = [bar for bar in bars if bar.complete]
        incomplete = [bar for bar in bars if not bar.complete]
        expected_per_day = 375 // minutes
        expected_total = counts.get("KEEP", 0) * expected_per_day

        print(f"{minutes}-MINUTE")
        print(f"  Bars generated        : {len(bars):,}")
        print(f"  Complete bars         : {len(complete):,}")
        print(f"  Incomplete bars       : {len(incomplete):,}")
        print(f"  Expected complete bars: {expected_total:,}")
        print(f"  Complete-only delta   : {len(complete) - expected_total:+,}")
        print()

    print("Raw FYERS database was not modified.")


if __name__ == "__main__":
    main()
