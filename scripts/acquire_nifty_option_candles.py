"""Controlled, resume-safe acquisition of empty NIFTY expired-option 1m candles.

This runner deliberately sits on top of HistoricalDownloader V1. It does not
change downloader, resolver, strategy, accounting, or candle semantics.

Default behavior is intentionally conservative:
- only empty, valid historical NIFTY option contracts
- 90 calendar days ending at contract expiry
- 5 contracts per run
- 1.2s pause between contracts
- CSV checkpoint after every contract

A later coverage audit can identify contracts whose returned history starts
later than the requested range; this runner does not fabricate or forward-fill
missing market data.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DAYS_BEFORE = 90
DEFAULT_LIMIT = 5
DEFAULT_PAUSE = 1.2
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "data"
    / "research"
    / "nifty_option_bulk_acquisition_checkpoint.csv"
)

FIELDS = [
    "instrument_id",
    "symbol",
    "expiry_date",
    "strike",
    "option_type",
    "range_from",
    "range_to",
    "status",
    "received",
    "inserted",
    "duplicates",
    "failed_chunks",
    "empty_chunks",
    "error",
]


def build_range(expiry_date: str, days_before: int) -> tuple[str, str]:
    if days_before < 0:
        raise ValueError("days_before must be >= 0")
    expiry = date.fromisoformat(expiry_date)
    return (expiry - timedelta(days=days_before)).isoformat(), expiry.isoformat()


def load_empty_contracts(database_path: Path, limit: int | None, symbols: list[str] | None = None) -> list[sqlite3.Row]:
    with sqlite3.connect(database_path) as db:
        db.row_factory = sqlite3.Row
        sql = """
            SELECT
                i.id AS instrument_id,
                i.symbol,
                i.expiry_date,
                i.strike,
                i.option_type
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
        params = []
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            sql = sql.replace(
                "ORDER BY i.expiry_date, i.strike, i.option_type",
                "AND i.symbol IN (" + placeholders + ") ORDER BY i.expiry_date, i.strike, i.option_type",
            )
            params.extend(symbols)
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return db.execute(sql, params).fetchall()


def append_checkpoint(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDS})
        handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Controlled NIFTY expired-option 1m acquisition runner."
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--days-before", type=int, default=DEFAULT_DAYS_BEFORE)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Contracts per run. Default 5. Use 0 for all remaining contracts.",
    )
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE)
    parser.add_argument("--symbols", nargs="+", default=None, help="Optional explicit symbols for controlled validation.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database

    limit = None if args.limit == 0 else max(1, args.limit)
    rows = load_empty_contracts(database_path, limit, args.symbols)

    print("=" * 90)
    print("KUNAL QUANT — CONTROLLED NIFTY OPTION ACQUISITION")
    print("=" * 90)
    print(f"Database      : {database_path}")
    print(f"Contracts run : {len(rows)}")
    print(f"Days before   : {args.days_before}")
    print(f"Pause         : {args.pause:.1f}s")
    print(f"Checkpoint    : {args.output}")

    if not rows:
        print("No empty valid contracts remain.")
        return

    from downloader.historical import HistoricalDownloader

    downloader = HistoricalDownloader()

    for index, row in enumerate(rows, 1):
        range_from, range_to = build_range(
            row["expiry_date"], args.days_before
        )
        symbol = row["symbol"]

        print()
        print(
            f"[{index:03d}/{len(rows):03d}] "
            f"{symbol} expiry={row['expiry_date']} "
            f"{range_from}->{range_to}",
            flush=True,
        )

        try:
            result = downloader.download_symbol(
                symbol=symbol,
                range_from=range_from,
                range_to=range_to,
                resolution="1",
                mode="expired",
            )
            checkpoint = {
                "instrument_id": row["instrument_id"],
                "symbol": symbol,
                "expiry_date": row["expiry_date"],
                "strike": row["strike"],
                "option_type": row["option_type"],
                "range_from": range_from,
                "range_to": range_to,
                "status": (
                    "FAILED"
                    if result["failed"] > 0
                    else "PARTIAL"
                    if result["empty"] > 0 and result["inserted"] > 0
                    else "EMPTY"
                    if result["inserted"] == 0
                    else "COMPLETED"
                ),
                "received": result["received"],
                "inserted": result["inserted"],
                "duplicates": result["duplicates"],
                "failed_chunks": result["failed"],
                "empty_chunks": result["empty"],
                "error": "",
            }
        except Exception as exc:
            checkpoint = {
                "instrument_id": row["instrument_id"],
                "symbol": symbol,
                "expiry_date": row["expiry_date"],
                "strike": row["strike"],
                "option_type": row["option_type"],
                "range_from": range_from,
                "range_to": range_to,
                "status": "ERROR",
                "received": 0,
                "inserted": 0,
                "duplicates": 0,
                "failed_chunks": 0,
                "empty_chunks": 0,
                "error": str(exc),
            }

        append_checkpoint(args.output, checkpoint)
        print(
            f"CHECKPOINT {checkpoint['status']} "
            f"inserted={checkpoint['inserted']} "
            f"received={checkpoint['received']}",
            flush=True,
        )

        if index < len(rows):
            time.sleep(max(0.0, args.pause))

    print()
    print("=" * 90)
    print("CONTROLLED ACQUISITION COMPLETE")
    print("=" * 90)
    print(f"Checkpoint: {args.output}")


if __name__ == "__main__":
    main()
