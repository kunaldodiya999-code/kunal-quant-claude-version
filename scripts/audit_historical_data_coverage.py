"""Audit historical data coverage before launching multi-day backtests.

Research-only. Read-only against the canonical SQLite database.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def audit(database_path: Path) -> None:
    with sqlite3.connect(database_path) as db:
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        required = {"instruments", "candles"}
        missing = required - tables
        if missing:
            raise RuntimeError(f"missing required tables: {sorted(missing)}")

        print("=" * 100)
        print("KUNAL QUANT — HISTORICAL DATA COVERAGE AUDIT")
        print("=" * 100)

        print("\n[INSTRUMENTS]")
        rows = db.execute(
            """
            SELECT broker, underlying, option_type, COUNT(*) AS contracts,
                   MIN(expiry_date), MAX(expiry_date)
            FROM instruments
            WHERE broker = 'FYERS'
            GROUP BY broker, underlying, option_type
            ORDER BY underlying, option_type
            """
        ).fetchall()
        for row in rows:
            print(
                f"broker={row[0]} underlying={row[1]} option_type={row[2]} "
                f"contracts={row[3]} expiry={row[4]}..{row[5]}"
            )

        print("\n[NIFTY 1M]")
        row = db.execute(
            """
            SELECT COUNT(*), MIN(c.timestamp), MAX(c.timestamp)
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker='FYERS'
              AND i.symbol='NSE:NIFTY50-INDEX'
              AND c.resolution='1'
            """
        ).fetchone()
        print(f"candles={row[0]} timestamp={row[1]}..{row[2]}")

        print("\n[OPTION CANDLE COVERAGE]")
        rows = db.execute(
            """
            SELECT
                i.id, i.symbol, i.expiry_date, i.strike, i.option_type,
                COUNT(c.timestamp) AS candles,
                MIN(c.timestamp) AS first_ts,
                MAX(c.timestamp) AS last_ts
            FROM instruments i
            LEFT JOIN candles c
              ON c.instrument_id=i.id
             AND c.resolution='1'
             AND c.source='FYERS_FNO_HISTORY'
            WHERE i.broker='FYERS'
              AND i.underlying='NIFTY'
              AND i.option_type IN ('CE','PE')
            GROUP BY i.id, i.symbol, i.expiry_date, i.strike, i.option_type
            ORDER BY i.expiry_date, i.strike, i.option_type
            """
        ).fetchall()

        total = len(rows)
        with_data = sum(1 for r in rows if r[5] > 0)
        empty = total - with_data
        print(f"contracts={total} with_candles={with_data} empty={empty}")

        by_expiry = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            expiry = r[2]
            by_expiry[expiry][0] += 1
            if r[5] > 0:
                by_expiry[expiry][1] += 1
            by_expiry[expiry][2] += r[5]

        print("\n[BY EXPIRY]")
        for expiry, (contracts, populated, candles) in sorted(by_expiry.items()):
            print(
                f"{expiry} contracts={contracts} populated={populated} "
                f"empty={contracts-populated} candles={candles}"
            )

        print("\n[EMPTY CONTRACTS — FIRST 50]")
        for r in [r for r in rows if r[5] == 0][:50]:
            print(
                f"id={r[0]} {r[1]} expiry={r[2]} strike={r[3]} type={r[4]}"
            )

        print("\n[DATA SOURCES]")
        rows = db.execute(
            """
            SELECT source, resolution, COUNT(*) AS candles
            FROM candles
            GROUP BY source, resolution
            ORDER BY source, resolution
            """
        ).fetchall()
        for row in rows:
            print(f"source={row[0]} resolution={row[1]} candles={row[2]}")

        print("=" * 100)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH

        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    audit(database_path)


if __name__ == "__main__":
    main()
