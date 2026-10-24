"""Resume-safe repair of missing/partial historical NIFTY option candles.

Uses the existing HistoricalDownloader and FYERS F&O history endpoint. It
never fabricates candles. Partial contracts are re-queried in shorter windows
so older 90-day completed-job checkpoints do not suppress the repair requests.
Default mode is dry-run; pass --execute to write downloaded candles to SQLite.
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

DEFAULT_MIN_CANDLES = 3000
DEFAULT_LIMIT = 5
DEFAULT_DAYS_BEFORE = 90
DEFAULT_CHUNK_DAYS = 15
DEFAULT_PAUSE = 1.2
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "research" / "nifty_option_repair_checkpoint.csv"
FIELDS = [
    "instrument_id", "symbol", "expiry_date", "strike", "option_type",
    "existing_candles", "range_from", "range_to", "status",
    "received", "inserted", "duplicates", "failed_chunks", "empty_chunks", "error",
]


def build_chunks(range_from: str, range_to: str, chunk_days: int = DEFAULT_CHUNK_DAYS) -> list[tuple[str, str]]:
    """Split inclusive date ranges into bounded, non-overlapping chunks."""
    if chunk_days < 1:
        raise ValueError("chunk_days must be >= 1")
    start, end = date.fromisoformat(range_from), date.fromisoformat(range_to)
    if start > end:
        raise ValueError("range_from cannot be after range_to")
    chunks = []
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        chunks.append((current.isoformat(), chunk_end.isoformat()))
        current = chunk_end + timedelta(days=1)
    return chunks


def load_repair_candidates(
    database_path: Path,
    *,
    limit: int | None,
    min_candles: int = DEFAULT_MIN_CANDLES,
    symbols: list[str] | None = None,
) -> list[sqlite3.Row]:
    """Return empty contracts, plus partial contracts below the candle threshold."""
    if min_candles < 1:
        raise ValueError("min_candles must be >= 1")
    with sqlite3.connect(database_path) as db:
        db.row_factory = sqlite3.Row
        sql = """
            SELECT i.id AS instrument_id, i.symbol, i.expiry_date, i.strike,
                   i.option_type, COALESCE(c.cnt, 0) AS existing_candles
            FROM instruments i
            LEFT JOIN (
                SELECT instrument_id, COUNT(*) AS cnt
                FROM candles
                WHERE resolution='1' AND source='FYERS_FNO_HISTORY'
                GROUP BY instrument_id
            ) c ON c.instrument_id=i.id
            WHERE i.broker='FYERS' AND i.underlying='NIFTY'
              AND i.option_type IN ('CE','PE')
              AND i.expiry_date <= date('now') AND i.strike > 0
        """
        params: list[object] = []
        if symbols:
            sql += " AND i.symbol IN (" + ",".join("?" for _ in symbols) + ")"
            params.extend(symbols)
        sql += " AND COALESCE(c.cnt, 0) < ?"
        params.append(min_candles)
        sql += " ORDER BY COALESCE(c.cnt, 0), i.expiry_date, i.strike, i.option_type"
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
        writer.writerow({key: row.get(key, "") for key in FIELDS})
        handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair empty/partial NIFTY expired-option candles.")
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--days-before", type=int, default=DEFAULT_DAYS_BEFORE)
    parser.add_argument("--min-candles", type=int, default=DEFAULT_MIN_CANDLES,
                        help="Select contracts with fewer 1m candles than this threshold.")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                        help="Contracts per run; use 0 for all candidates.")
    parser.add_argument("--chunk-days", type=int, default=DEFAULT_CHUNK_DAYS,
                        help="Short windows help repair previously partial 90-day jobs.")
    parser.add_argument("--pause", type=float, default=DEFAULT_PAUSE)
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--execute", action="store_true",
                        help="Actually download and write candles. Without this flag, only preview.")
    args = parser.parse_args()

    if args.days_before < 0:
        parser.error("--days-before must be >= 0")
    if args.chunk_days < 1:
        parser.error("--chunk-days must be >= 1")
    database_path = args.database
    if database_path is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)

    limit = None if args.limit == 0 else max(1, args.limit)
    rows = load_repair_candidates(
        database_path, limit=limit, min_candles=args.min_candles, symbols=args.symbols
    )
    print("=" * 92)
    print("KUNAL QUANT — NIFTY OPTION DATA REPAIR")
    print("=" * 92)
    print(f"Database        : {database_path}")
    print(f"Candidates      : {len(rows)}")
    print(f"Threshold       : < {args.min_candles:,} candles per contract")
    print(f"Window          : {args.days_before} calendar days ending at expiry")
    print(f"Chunk size      : {args.chunk_days} days")
    print(f"Mode            : {'EXECUTE — writes to SQLite' if args.execute else 'DRY RUN — no downloads or DB writes'}")
    print(f"Checkpoint      : {args.output}")
    for row in rows:
        range_from = (date.fromisoformat(row["expiry_date"]) - timedelta(days=args.days_before)).isoformat()
        range_to = row["expiry_date"]
        chunks = build_chunks(range_from, range_to, args.chunk_days)
        print(f"{row['symbol']} | expiry={range_to} | stored={row['existing_candles']:,} | {range_from}->{range_to} | chunks={len(chunks)}")

    if not args.execute:
        print("\nPreview only. Re-run with --execute after reviewing the candidate list.")
        return
    if not rows:
        print("No contracts match the repair criteria.")
        return

    from downloader.historical import HistoricalDownloader
    downloader = HistoricalDownloader(database_path=database_path)
    for index, row in enumerate(rows, 1):
        range_from = (date.fromisoformat(row["expiry_date"]) - timedelta(days=args.days_before)).isoformat()
        range_to = row["expiry_date"]
        totals = {"received": 0, "inserted": 0, "duplicates": 0, "failed": 0, "empty": 0}
        errors = []
        print(f"\n[{index}/{len(rows)}] {row['symbol']} stored={row['existing_candles']:,}", flush=True)
        for chunk_from, chunk_to in build_chunks(range_from, range_to, args.chunk_days):
            try:
                result = downloader.download_chunk(
                    symbol=row["symbol"], range_from=chunk_from, range_to=chunk_to,
                    resolution="1", mode="expired",
                )
                for key in ("received", "inserted", "duplicates"):
                    totals[key] += int(result.get(key, 0))
                if result.get("status") == "FAILED":
                    totals["failed"] += 1
                    errors.append(str(result.get("error", "chunk failed")))
                if result.get("status") == "EMPTY":
                    totals["empty"] += 1
            except Exception as exc:
                totals["failed"] += 1
                errors.append(f"{chunk_from}->{chunk_to}: {exc}")
            time.sleep(max(0.0, args.pause))
        status = "FAILED" if totals["failed"] else "NO_DATA" if not totals["received"] else "PARTIAL" if totals["empty"] else "DOWNLOADED"
        append_checkpoint(args.output, {
            "instrument_id": row["instrument_id"], "symbol": row["symbol"],
            "expiry_date": row["expiry_date"], "strike": row["strike"],
            "option_type": row["option_type"], "existing_candles": row["existing_candles"],
            "range_from": range_from, "range_to": range_to, "status": status,
            **totals, "failed_chunks": totals["failed"], "empty_chunks": totals["empty"],
            "error": " | ".join(errors)[:3000],
        })
        print(f"CHECKPOINT {status} received={totals['received']:,} inserted={totals['inserted']:,} failed={totals['failed']}", flush=True)

    print(f"\nRepair run complete. Checkpoint: {args.output}")


if __name__ == "__main__":
    main()
