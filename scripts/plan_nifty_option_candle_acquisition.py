"""Build a deterministic acquisition manifest for empty NIFTY option contracts.

This script is planning-only: it never calls FYERS and never writes candles.
It uses the canonical KunalQuant SQLite database.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "research" / "nifty_option_acquisition_plan.csv")
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    args.output.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(database_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            """
            SELECT
                i.id,
                i.symbol,
                i.expiry_date,
                i.strike,
                i.option_type,
                i.broker_token,
                COALESCE(c.cnt, 0) AS candle_count
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
              AND i.strike > 0
              AND COALESCE(c.cnt, 0) = 0
            ORDER BY i.expiry_date, i.strike, i.option_type
            """
        ).fetchall()

    fields = [
        "instrument_id", "symbol", "expiry_date", "strike", "option_type",
        "broker_token", "candle_count", "status",
    ]
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "instrument_id": row["id"],
                "symbol": row["symbol"],
                "expiry_date": row["expiry_date"],
                "strike": row["strike"],
                "option_type": row["option_type"],
                "broker_token": row["broker_token"] or "",
                "candle_count": row["candle_count"],
                "status": "PROBE_REQUIRED",
            })

    print("=" * 90)
    print("KUNAL QUANT — NIFTY OPTION CANDLE ACQUISITION PLAN")
    print("=" * 90)
    print(f"Database : {database_path}")
    print(f"Manifest : {args.output}")
    print(f"Empty valid contracts : {len(rows):,}")
    print("Invalid-strike records are excluded from the acquisition plan.")


if __name__ == "__main__":
    main()
