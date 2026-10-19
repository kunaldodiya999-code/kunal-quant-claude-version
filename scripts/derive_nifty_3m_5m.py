from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH, PROCESSED_DATA_DIR, TIMEZONE
from market_data.derived_store import replace_bars
from market_data.resampling import Candle, aggregate_day


SYMBOL = "NSE:NIFTY50-INDEX"
SOURCE_1M = "FYERS_HISTORY"
DERIVED_SOURCE = "KQ_DERIVED_FROM_FYERS_1M"
MARKET_TZ = ZoneInfo(TIMEZONE)
SESSION_START = time(9, 15)
SESSION_END = time(15, 29)
MAX_CONSECUTIVE_MISSING = 3
SPECIAL_SESSION_DATES = frozenset(
    {date(2021, 11, 4), date(2024, 3, 2), date(2024, 5, 18)}
)
OUTPUT_DB = PROCESSED_DATA_DIR / "nifty_derived.db"


def load_candles() -> list[Candle]:
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close,
                   c.volume, c.open_interest
            FROM candles AS c
            JOIN instruments AS i ON i.id = c.instrument_id
            WHERE i.broker = 'FYERS'
              AND i.symbol = ?
              AND c.resolution = '1'
              AND c.source = ?
            ORDER BY c.timestamp
            """,
            (SYMBOL, SOURCE_1M),
        ).fetchall()
    return [Candle(*row) for row in rows]


def session_bounds(day: date) -> tuple[int, int]:
    start = datetime.combine(day, SESSION_START, tzinfo=MARKET_TZ)
    end = datetime.combine(day, SESSION_END, tzinfo=MARKET_TZ)
    return int(start.timestamp()), int(end.timestamp())


def classify_days(candles: list[Candle]) -> dict[date, str]:
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        grouped[datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date()].append(candle)

    result: dict[date, str] = {}
    for day, day_candles in grouped.items():
        if day in SPECIAL_SESSION_DATES or day.weekday() >= 5:
            result[day] = "EXCLUDE_SPECIAL_SESSION"
            continue

        start, end = session_bounds(day)
        regular = [c for c in day_candles if start <= c.timestamp <= end]
        if len(regular) != len(day_candles):
            result[day] = "EXCLUDE_NON_REGULAR_SESSION"
            continue

        if any(
            not (c.low <= c.open <= c.high and c.low <= c.close <= c.high)
            for c in regular
        ):
            result[day] = "EXCLUDE_INVALID_OHLC"
            continue

        if any(min(c.open, c.high, c.low, c.close) <= 0 for c in regular):
            result[day] = "EXCLUDE_NON_POSITIVE_PRICE"
            continue

        actual = {c.timestamp for c in regular}
        missing = sorted(set(range(start, end + 60, 60)) - actual)

        max_run = 0
        run = 0
        previous = None
        for timestamp in missing:
            run = run + 1 if previous is not None and timestamp == previous + 60 else 1
            max_run = max(max_run, run)
            previous = timestamp

        result[day] = (
            "EXCLUDE_EXCESSIVE_GAP"
            if max_run > MAX_CONSECUTIVE_MISSING
            else "KEEP"
        )

    return result


def derive_for_resolution(
    candles: list[Candle],
    classifications: dict[date, str],
    minutes: int,
):
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        day = datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date()
        if classifications.get(day) == "KEEP":
            grouped[day].append(candle)

    bars = []
    for day in sorted(grouped):
        bars.extend(aggregate_day(grouped[day], minutes))
    return bars


def main() -> None:
    candles = load_candles()
    classifications = classify_days(candles)
    counts = Counter(classifications.values())

    print("=" * 80)
    print("KUNAL QUANT — NIFTY 3M / 5M DERIVED DATA BUILD")
    print("=" * 80)
    print(f"Source DB : {DATABASE_PATH}")
    print(f"Output DB : {OUTPUT_DB}")
    print(f"1M rows   : {len(candles):,}")
    print(f"KEEP days : {counts.get('KEEP', 0):,}")
    print()

    for minutes in (3, 5):
        bars = derive_for_resolution(candles, classifications, minutes)
        written = replace_bars(
            OUTPUT_DB,
            SYMBOL,
            str(minutes),
            DERIVED_SOURCE,
            bars,
        )
        complete = sum(bar.complete for bar in bars)
        incomplete = len(bars) - complete
        print(
            f"{minutes}M: written={written:,}, "
            f"complete={complete:,}, incomplete={incomplete:,}"
        )

    print()
    print("BUILD COMPLETE")
    print("Raw FYERS candles were not modified.")


if __name__ == "__main__":
    main()
