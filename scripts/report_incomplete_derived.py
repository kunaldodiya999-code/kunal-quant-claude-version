from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import PROCESSED_DATA_DIR, TIMEZONE


DB_PATH = PROCESSED_DATA_DIR / "nifty_derived.db"
TZ = ZoneInfo(TIMEZONE)


def main() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        rows = connection.execute(
            """
            SELECT resolution, timestamp, open, high, low, close,
                   actual_1m_candles, expected_1m_candles
            FROM derived_candles
            WHERE complete = 0
            ORDER BY resolution, timestamp
            """
        ).fetchall()

    print("=" * 80)
    print("KUNAL QUANT — INCOMPLETE DERIVED BAR REPORT")
    print("=" * 80)
    print(f"Database: {DB_PATH}")
    print(f"Incomplete bars: {len(rows)}")
    print()

    for resolution, timestamp, open_, high, low, close, actual, expected in rows:
        dt = datetime.fromtimestamp(timestamp, tz=TZ)
        print(
            f"{resolution}M | {dt.isoformat()} | "
            f"OHLC={open_},{high},{low},{close} | "
            f"source candles={actual}/{expected}"
        )

    if not rows:
        print("No incomplete derived bars found.")


if __name__ == "__main__":
    main()
