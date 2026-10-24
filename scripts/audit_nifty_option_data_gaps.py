"""Research audit for NIFTY expired-option metadata and candle gaps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    print(f"Database : {database_path}")

    with sqlite3.connect(database_path) as db:
        summary = db.execute(
            """
            SELECT
                COUNT(*),
                SUM(CASE WHEN strike IS NULL OR strike <= 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN candles.cnt IS NULL OR candles.cnt = 0 THEN 1 ELSE 0 END),
                SUM(CASE WHEN candles.cnt > 0 THEN 1 ELSE 0 END)
            FROM instruments i
            LEFT JOIN (
                SELECT instrument_id, COUNT(*) AS cnt
                FROM candles
                WHERE resolution='1' AND source='FYERS_FNO_HISTORY'
                GROUP BY instrument_id
            ) candles ON candles.instrument_id=i.id
            WHERE i.broker='FYERS'
              AND i.underlying='NIFTY'
              AND i.option_type IN ('CE','PE')
              AND i.expiry_date <= date('now')
            """
        ).fetchone()

        print("=" * 90)
        print("KUNAL QUANT — NIFTY OPTION DATA GAP AUDIT")
        print("=" * 90)
        print(f"Historical contracts : {summary[0]:,}")
        print(f"Invalid strike       : {summary[1]:,}")
        print(f"Empty 1m contracts   : {summary[2]:,}")
        print(f"Populated 1m contracts: {summary[3]:,}")
        print()

        rows = db.execute(
            """
            SELECT
                i.expiry_date,
                COUNT(*) AS contracts,
                SUM(CASE WHEN i.strike IS NULL OR i.strike <= 0 THEN 1 ELSE 0 END) AS bad_strikes,
                SUM(CASE WHEN COALESCE(c.cnt,0)=0 THEN 1 ELSE 0 END) AS empty,
                SUM(CASE WHEN COALESCE(c.cnt,0)>0 THEN 1 ELSE 0 END) AS populated,
                SUM(COALESCE(c.cnt,0)) AS candles
            FROM instruments i
            LEFT JOIN (
                SELECT instrument_id, COUNT(*) AS cnt
                FROM candles
                WHERE resolution='1' AND source='FYERS_FNO_HISTORY'
                GROUP BY instrument_id
            ) c ON c.instrument_id=i.id
            WHERE i.broker='FYERS'
              AND i.underlying='NIFTY'
              AND i.option_type IN ('CE','PE')
              AND i.expiry_date <= date('now')
            GROUP BY i.expiry_date
            ORDER BY i.expiry_date
            """
        ).fetchall()

        print("BY EXPIRY")
        for row in rows:
            print(
                f"{row[0]} contracts={row[1]:4d} "
                f"bad_strikes={row[2]:4d} empty={row[3]:4d} "
                f"populated={row[4]:4d} candles={row[5]:,}"
            )


if __name__ == "__main__":
    main()
