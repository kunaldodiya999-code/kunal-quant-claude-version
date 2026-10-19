from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from database.schema import initialize_database
from config.settings import DATABASE_PATH
from downloader.historical import HistoricalDownloader

SYMBOL = "NSE:NIFTY50-INDEX"
RESOLUTION = "1"
FROM_DATE = "2021-09-24"
TO_DATE = "2026-09-23"


def main() -> None:
    print("=" * 80)
    print("KUNAL QUANT — GITHUB 5-YEAR NIFTY 1-MINUTE DOWNLOAD")
    print("=" * 80)
    print(f"Symbol: {SYMBOL}")
    print(f"Range : {FROM_DATE} -> {TO_DATE}")
    print()

    initialize_database(DATABASE_PATH)

    downloader = HistoricalDownloader(
        database_path=DATABASE_PATH,
        max_attempts=5,
        retry_delay_seconds=5.0,
    )

    result = downloader.download_symbol(
        symbol=SYMBOL,
        range_from=FROM_DATE,
        range_to=TO_DATE,
        resolution=RESOLUTION,
        mode="standard",
    )

    print("\nDOWNLOAD SUMMARY")
    print(json.dumps(result, indent=2))

    if int(result.get("failed", 0)) != 0:
        raise RuntimeError(
            f"Download finished with {result['failed']} failed chunk(s)."
        )

    with sqlite3.connect(DATABASE_PATH) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*),
                MIN(timestamp),
                MAX(timestamp)
            FROM candles
            WHERE instrument_id = (
                SELECT id
                FROM instruments
                WHERE broker = 'FYERS'
                  AND symbol = ?
                LIMIT 1
            )
              AND resolution = ?
              AND source = 'FYERS_HISTORY'
            """,
            (SYMBOL, RESOLUTION),
        ).fetchone()

    count, min_timestamp, max_timestamp = row

    print("\nDATABASE VALIDATION")
    print(f"Candles: {count}")
    print(f"Min timestamp: {min_timestamp}")
    print(f"Max timestamp: {max_timestamp}")

    if not count or count < 400_000:
        raise RuntimeError(
            f"Unexpectedly low candle count: {count}"
        )

    if min_timestamp is None or max_timestamp is None:
        raise RuntimeError("Missing timestamp coverage.")

    print("\n5-YEAR NIFTY DOWNLOAD VALIDATION PASSED")


if __name__ == "__main__":
    main()
