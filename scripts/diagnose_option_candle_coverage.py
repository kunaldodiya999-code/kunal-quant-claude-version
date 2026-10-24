"""Read-only diagnostic for stored FYERS NIFTY option candle coverage."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH

TZ = ZoneInfo("Asia/Kolkata")
SOURCE = "FYERS_FNO_HISTORY"


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as db:
        ids = [
            row[0]
            for row in db.execute(
                """
                SELECT DISTINCT instrument_id
                FROM candles
                WHERE source = ? AND resolution = '1'
                ORDER BY instrument_id
                LIMIT 30
                """,
                (SOURCE,),
            )
        ]

        print("=" * 100)
        print("KUNAL QUANT — STORED NIFTY OPTION CANDLE COVERAGE")
        print("=" * 100)
        print("READ-ONLY DIAGNOSTIC — no database changes")
        print()

        total = db.execute(
            """
            SELECT COUNT(*)
            FROM candles
            WHERE source = ? AND resolution = '1'
            """,
            (SOURCE,),
        ).fetchone()[0]
        distinct = db.execute(
            """
            SELECT COUNT(DISTINCT instrument_id)
            FROM candles
            WHERE source = ? AND resolution = '1'
            """,
            (SOURCE,),
        ).fetchone()[0]
        print(f"FYERS F&O 1M rows       : {total:,}")
        print(f"Distinct instruments   : {distinct:,}")
        print()

        print("SAMPLE STORED OPTION INSTRUMENTS")
        rows = db.execute(
            """
            SELECT i.id, i.symbol, i.expiry_date, i.strike, i.option_type,
                   COUNT(c.id), MIN(c.timestamp), MAX(c.timestamp)
            FROM instruments i
            JOIN candles c ON c.instrument_id = i.id
            WHERE c.source = ? AND c.resolution = '1'
              AND i.underlying = 'NIFTY'
              AND i.option_type IN ('CE','PE')
            GROUP BY i.id
            ORDER BY i.id
            LIMIT 30
            """,
            (SOURCE,),
        ).fetchall()

        for row in rows:
            first = datetime.fromtimestamp(row[6], TZ)
            last = datetime.fromtimestamp(row[7], TZ)
            print(
                f"id={row[0]:5d} | {row[1]:30s} | expiry={row[2]} | "
                f"strike={row[3]} | {row[4]} | candles={row[5]:6d} | "
                f"{first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M}"
            )

        print()
        print("KNOWN RESOLVED-SAMPLE INSTRUMENTS")
        for instrument_id in (5882, 5879, 5880, 5881, 5884):
            row = db.execute(
                """
                SELECT i.id, i.symbol, i.expiry_date, i.strike, i.option_type,
                       COUNT(c.id), MIN(c.timestamp), MAX(c.timestamp)
                FROM instruments i
                LEFT JOIN candles c
                  ON c.instrument_id = i.id
                 AND c.source = ?
                 AND c.resolution = '1'
                WHERE i.id = ?
                GROUP BY i.id
                """,
                (SOURCE, instrument_id),
            ).fetchone()

            if row is None:
                print(f"id={instrument_id}: INSTRUMENT NOT FOUND")
                continue

            if row[5]:
                first = datetime.fromtimestamp(row[6], TZ)
                last = datetime.fromtimestamp(row[7], TZ)
                coverage = f"{first:%Y-%m-%d %H:%M} -> {last:%Y-%m-%d %H:%M}"
            else:
                coverage = "NO STORED CANDLES"

            print(
                f"id={row[0]} | {row[1]} | expiry={row[2]} | "
                f"strike={row[3]} | {row[4]} | candles={row[5]} | {coverage}"
            )

        print()
        print("OPTION CANDLE COVERAGE BY DATE")
        date_rows = db.execute(
            """
            SELECT date(datetime(timestamp, 'unixepoch', '+5 hours', '+30 minutes')),
                   COUNT(*), COUNT(DISTINCT instrument_id)
            FROM candles
            WHERE source = ? AND resolution = '1'
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 30
            """,
            (SOURCE,),
        ).fetchall()

        for day, count, instruments in date_rows:
            print(f"{day} | candles={count:7d} | instruments={instruments:5d}")


if __name__ == "__main__":
    main()
