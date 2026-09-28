"""
Kunal Quant - Option Session Semantics Audit

READ-ONLY diagnostic for the apparent difference between:
  older option data: 375 candles, 09:15-15:29
  recent option data: 385 candles, 09:15-15:39

No data is modified.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH

TZ = ZoneInfo("Asia/Kolkata")
SOURCE = "FYERS_FNO_HISTORY"


def local_minute(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=TZ).replace(second=0, microsecond=0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only audit of FYERS option candle session semantics"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Optional calendar year to restrict the audit.",
    )
    args = parser.parse_args()

    with sqlite3.connect(DATABASE_PATH) as db:
        where = [
            "c.source = ?",
            "c.resolution = '1'",
            "i.underlying = 'NIFTY'",
            "i.option_type IN ('CE','PE')",
        ]
        params: list[object] = [SOURCE]

        if args.year is not None:
            where.append(
                "strftime('%Y', datetime(c.timestamp, 'unixepoch', '+5 hours', '+30 minutes')) = ?" 
            )
            params.append(str(args.year))

        where_sql = " AND ".join(where)

        duplicate_rows = db.execute(
            f"""
            SELECT COUNT(*)
            FROM (
                SELECT c.instrument_id, c.timestamp, c.resolution
                FROM candles c
                JOIN instruments i ON i.id = c.instrument_id
                WHERE {where_sql}
                GROUP BY c.instrument_id, c.timestamp, c.resolution
                HAVING COUNT(*) > 1
            )
            """
            ,
            params,
        ).fetchone()[0]

        daily_rows = db.execute(
            f"""
            SELECT
                i.symbol,
                i.expiry_date,
                i.strike,
                i.option_type,
                date(datetime(c.timestamp, 'unixepoch',
                              '+5 hours', '+30 minutes')) AS trade_date,
                COUNT(*) AS candle_count,
                MIN(c.timestamp) AS first_ts,
                MAX(c.timestamp) AS last_ts
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE {where_sql}
            GROUP BY i.id, trade_date
            ORDER BY trade_date DESC, i.id
            """
            ,
            params,
        ).fetchall()

        count_distribution = Counter(int(row[5]) for row in daily_rows)

        print("=" * 110)
        print("KUNAL QUANT - FYERS OPTION SESSION SEMANTICS AUDIT")
        print("=" * 110)
        print("READ-ONLY — no database changes")
        print()
        print(f"Database                 : {DATABASE_PATH}")
        print(f"FYERS F&O 1M instrument-days: {len(daily_rows):,}")
        print(f"Duplicate timestamp sets  : {int(duplicate_rows):,}")
        print()

        print("DAILY CANDLE COUNT DISTRIBUTION")
        for count, frequency in sorted(count_distribution.items()):
            print(f"{count:4d} candles/day -> {frequency:,} instrument-days")

        print()
        print("NON-375 DAYS (first 100)")
        shown = 0

        for row in daily_rows:
            count = int(row[5])
            if count == 375:
                continue

            first_dt = local_minute(int(row[6]))
            last_dt = local_minute(int(row[7]))

            print(
                f"{row[4]} | "
                f"{row[0]:30s} | "
                f"{row[3]} | "
                f"count={count:4d} | "
                f"{first_dt:%H:%M} -> {last_dt:%H:%M} | "
                f"expiry={row[1]} | strike={row[2]}"
            )

            shown += 1
            if shown >= 100:
                break

        print()
        print("RECENT DAYS WITH 385 CANDLES")
        shown = 0
        for row in daily_rows:
            if int(row[5]) != 385:
                continue

            first_dt = local_minute(int(row[6]))
            last_dt = local_minute(int(row[7]))

            print(
                f"{row[4]} | "
                f"{row[0]:30s} | "
                f"{row[3]} | "
                f"{first_dt:%H:%M} -> {last_dt:%H:%M}"
            )

            shown += 1
            if shown >= 50:
                break

        print()
        print("INTERPRETATION DATA ONLY")
        print(
            "This audit deliberately does not decide whether 375 or 385 is "
            "the correct completeness rule. It only measures the stored data."
        )


if __name__ == "__main__":
    main()