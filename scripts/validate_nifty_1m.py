from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH, EXPECTED_1M_CANDLES, TIMEZONE


SYMBOL = "NSE:NIFTY50-INDEX"
RESOLUTION = "1"
SOURCE = "FYERS_HISTORY"
MARKET_TZ = ZoneInfo(TIMEZONE)
EXPECTED_INTERVAL_SECONDS = 60

MAX_CONSECUTIVE_MISSING = 3
REGULAR_SESSION_START = time(9, 15)
REGULAR_SESSION_END = time(15, 29)

# Known non-regular sessions which must not enter the regular-session dataset.
SPECIAL_SESSION_DATES = frozenset(
    {
        date(2021, 11, 4),  # Muhurat session
        date(2024, 3, 2),   # Saturday special session
        date(2024, 5, 18),  # Saturday special session
    }
)


def _load_rows(connection: sqlite3.Connection) -> list[tuple]:
    return connection.execute(
        """
        SELECT c.timestamp, c.open, c.high, c.low, c.close
        FROM candles AS c
        JOIN instruments AS i ON i.id = c.instrument_id
        WHERE i.broker = 'FYERS'
          AND i.symbol = ?
          AND c.resolution = ?
          AND c.source = ?
        ORDER BY c.timestamp
        """,
        (SYMBOL, RESOLUTION, SOURCE),
    ).fetchall()


def _session_timestamp_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, REGULAR_SESSION_START, tzinfo=MARKET_TZ)
    end = datetime.combine(day, REGULAR_SESSION_END, tzinfo=MARKET_TZ)
    return int(start.timestamp()), int(end.timestamp())


def _missing_runs(day: date, timestamps: list[int]) -> list[list[int]]:
    expected_start, expected_end = _session_timestamp_bounds(day)
    actual = {
        timestamp
        for timestamp in timestamps
        if expected_start <= timestamp <= expected_end
    }
    expected = range(
        expected_start,
        expected_end + EXPECTED_INTERVAL_SECONDS,
        EXPECTED_INTERVAL_SECONDS,
    )

    runs: list[list[int]] = []
    current_run: list[int] = []

    for timestamp in expected:
        if timestamp not in actual:
            current_run.append(timestamp)
            continue

        if current_run:
            runs.append(current_run)
            current_run = []

    if current_run:
        runs.append(current_run)

    return runs


def _has_out_of_session_candles(timestamps: list[int]) -> bool:
    expected_start, expected_end = _session_timestamp_bounds(
        datetime.fromtimestamp(timestamps[0], tz=MARKET_TZ).date()
    )
    return any(
        timestamp < expected_start or timestamp > expected_end
        for timestamp in timestamps
    )


def classify_day(
    day: date,
    timestamps: list[int],
    invalid_ohlc_timestamps: set[int],
    non_positive_timestamps: set[int],
) -> tuple[str, int, list[list[int]]]:
    """Return (classification, max_missing_run, missing_runs)."""

    if day in SPECIAL_SESSION_DATES or day.weekday() >= 5:
        return "EXCLUDE_SPECIAL_SESSION", 0, []

    if _has_out_of_session_candles(timestamps):
        return "EXCLUDE_NON_REGULAR_SESSION", 0, []

    missing_runs = _missing_runs(day, timestamps)
    max_missing_run = max((len(run) for run in missing_runs), default=0)

    if invalid_ohlc_timestamps.intersection(timestamps):
        return "EXCLUDE_INVALID_OHLC", max_missing_run, missing_runs

    if non_positive_timestamps.intersection(timestamps):
        return "EXCLUDE_NON_POSITIVE_PRICE", max_missing_run, missing_runs

    if max_missing_run > MAX_CONSECUTIVE_MISSING:
        return "EXCLUDE_EXCESSIVE_GAP", max_missing_run, missing_runs

    return "KEEP", max_missing_run, missing_runs


def main() -> None:
    print("=" * 80)
    print("KUNAL QUANT — NIFTY 1-MINUTE DATA QUALITY VALIDATION")
    print("=" * 80)
    print(f"Symbol    : {SYMBOL}")
    print(f"Resolution: {RESOLUTION}")
    print(f"Source    : {SOURCE}")
    print(f"Database  : {DATABASE_PATH}")
    print()
    print("REGULAR SESSION POLICY")
    print("  Session             : 09:15–15:29 IST")
    print("  Missing tolerance   : up to 3 consecutive candles")
    print("  Exclude threshold   : 4+ consecutive missing candles")
    print("  Special sessions    : excluded")
    print("  Synthetic candles   : never created")
    print()

    if not Path(DATABASE_PATH).exists():
        raise FileNotFoundError(f"Database not found: {DATABASE_PATH}")

    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = _load_rows(connection)

    if not rows:
        raise RuntimeError("No matching NIFTY 1-minute candles found.")

    timestamps = [row[0] for row in rows]
    distinct_timestamps = len(set(timestamps))

    invalid_ohlc = set()
    non_positive_prices = set()

    for timestamp, open_price, high, low, close in rows:
        if not (low <= open_price <= high and low <= close <= high and low <= high):
            invalid_ohlc.add(timestamp)
        if min(open_price, high, low, close) <= 0:
            non_positive_prices.add(timestamp)

    daily: dict[date, list[int]] = {}
    for timestamp in timestamps:
        day = datetime.fromtimestamp(timestamp, tz=MARKET_TZ).date()
        daily.setdefault(day, []).append(timestamp)

    classifications: dict[str, list[date]] = {}
    gap_details: list[tuple[date, int, list[list[int]]]] = []

    for day, day_timestamps in daily.items():
        classification, max_missing_run, missing_runs = classify_day(
            day,
            day_timestamps,
            invalid_ohlc,
            non_positive_prices,
        )
        classifications.setdefault(classification, []).append(day)

        if missing_runs:
            gap_details.append((day, max_missing_run, missing_runs))

    yearly_counts = Counter(
        datetime.fromtimestamp(ts, tz=MARKET_TZ).year
        for ts in timestamps
    )

    kept_days = classifications.get("KEEP", [])
    excluded_days = [
        day
        for classification, days in classifications.items()
        if classification != "KEEP"
        for day in days
    ]

    min_dt = datetime.fromtimestamp(min(timestamps), tz=MARKET_TZ)
    max_dt = datetime.fromtimestamp(max(timestamps), tz=MARKET_TZ)

    print("SUMMARY")
    print(f"Database rows       : {len(rows):,}")
    print(f"Distinct timestamps : {distinct_timestamps:,}")
    print(f"Duplicate timestamps: {len(rows) - distinct_timestamps:,}")
    print(f"Source days         : {len(daily):,}")
    print(f"Eligible regular days: {len(kept_days):,}")
    print(f"Excluded days       : {len(excluded_days):,}")
    print(f"Min timestamp       : {min_dt.isoformat()}")
    print(f"Max timestamp       : {max_dt.isoformat()}")
    print()

    print("OHLC VALIDATION")
    print(f"Invalid OHLC rows   : {len(invalid_ohlc):,}")
    print(f"Non-positive prices : {len(non_positive_prices):,}")
    print()

    print("SESSION CLASSIFICATION")
    for classification in sorted(classifications):
        print(f"{classification:30s}: {len(classifications[classification]):,}")
    print()

    print("YEARLY SOURCE COVERAGE")
    for year in sorted(yearly_counts):
        print(f"{year}: {yearly_counts[year]:,}")

    if gap_details:
        print()
        print("GAP DETAILS")
        for day, max_missing_run, missing_runs in gap_details:
            status = "KEEP" if max_missing_run <= MAX_CONSECUTIVE_MISSING else "EXCLUDE"
            print(
                f"{day}: max consecutive missing={max_missing_run} -> {status}"
            )
            for run in missing_runs:
                first = datetime.fromtimestamp(run[0], tz=MARKET_TZ).strftime(
                    "%H:%M"
                )
                last = datetime.fromtimestamp(run[-1], tz=MARKET_TZ).strftime(
                    "%H:%M"
                )
                print(f"  missing {first}–{last} ({len(run)} candle(s))")

    if invalid_ohlc:
        print()
        print("INVALID OHLC SAMPLE")
        for timestamp in sorted(invalid_ohlc)[:10]:
            print(
                datetime.fromtimestamp(timestamp, tz=MARKET_TZ).isoformat()
            )

    if non_positive_prices:
        raise RuntimeError(
            f"Found {len(non_positive_prices)} row(s) with non-positive prices."
        )

    if distinct_timestamps != len(rows):
        raise RuntimeError(
            f"Found {len(rows) - distinct_timestamps} duplicate timestamp(s)."
        )

    print()
    print("=" * 80)
    print("NIFTY 1-MINUTE DATA QUALITY VALIDATION PASSED")
    print("=" * 80)
    print(
        "Raw FYERS candles were not modified. "
        "Downstream research must use KEEP days only."
    )


if __name__ == "__main__":
    main()
