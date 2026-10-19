"""Targeted coverage-depth audit for recently acquired NIFTY option contracts."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SYMBOLS = [
    "NSE:NIFTY2110710600CE",
    "NSE:NIFTY2110710600PE",
    "NSE:NIFTY2110710650CE",
    "NSE:NIFTY2110710650PE",
    "NSE:NIFTY2110710700CE",
]


def fmt(ts: int) -> str:
    return datetime.fromtimestamp(
        int(ts), tz=timezone.utc
    ).astimezone(
        timezone(timedelta(hours=5, minutes=30))
    ).strftime("%Y-%m-%d %H:%M:%S%z")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS)
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    with sqlite3.connect(database_path) as db:
        print("=" * 110)
        print("KUNAL QUANT — NIFTY OPTION COVERAGE DEPTH AUDIT")
        print("=" * 110)
        print(f"Database : {database_path}")
        print()

        for symbol in args.symbols:
            instrument = db.execute(
                """
                SELECT id, symbol, expiry_date, strike, option_type
                FROM instruments
                WHERE broker='FYERS' AND symbol=?
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()

            print("-" * 110)
            print(f"SYMBOL: {symbol}")

            if instrument is None:
                print("  NOT FOUND IN INSTRUMENTS")
                continue

            instrument_id, _, expiry, strike, option_type = instrument

            row = db.execute(
                """
                SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source='FYERS_FNO_HISTORY'
                """,
                (instrument_id,),
            ).fetchone()

            count, first_ts, last_ts = row

            day_rows = db.execute(
                """
                SELECT
                    date(datetime(timestamp, 'unixepoch',
                                  '+5 hours', '+30 minutes')) AS day,
                    COUNT(*) AS candles
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source='FYERS_FNO_HISTORY'
                GROUP BY day
                ORDER BY day
                """,
                (instrument_id,),
            ).fetchall()

            print(f"  Instrument ID : {instrument_id}")
            print(f"  Expiry        : {expiry}")
            print(f"  Strike        : {strike}")
            print(f"  Type          : {option_type}")
            print(f"  Candles       : {count or 0:,}")
            print(f"  Trading days  : {len(day_rows):,}")

            if first_ts is None:
                print("  First candle  : NONE")
                print("  Last candle   : NONE")
                continue

            counts = [int(r[1]) for r in day_rows]
            print(f"  First candle  : {fmt(first_ts)}")
            print(f"  Last candle   : {fmt(last_ts)}")
            print(
                f"  Per-day candles: min={min(counts)}, "
                f"max={max(counts)}, avg={sum(counts)/len(counts):.1f}"
            )
            print(
                "  Coverage days  : "
                + ", ".join(f"{r[0]}={r[1]}" for r in day_rows)
            )


if __name__ == "__main__":
    main()
