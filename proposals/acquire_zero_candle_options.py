"""
Kunal Quant - Targeted Zero-Candle Option Acquisition Proposal

Targets only the three currently required option symbols that are correctly
registered but have zero stored FYERS_FNO_HISTORY candles.

Default: DRY RUN. Use --apply to download and insert exactly the FYERS
history returned for each symbol over its required event-date range.

Implementation deliberately reuses canonical HistoricalDownloader logic
but supplies a runtime-safe completed-job lookup because the current
canonical helper's source argument is not represented in its SQL predicate.

No canonical source files are modified by this proposal.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from types import MethodType
from typing import Any

from api.fyers_client import FyersClient
from config.settings import DATABASE_PATH
from downloader.historical import HistoricalDownloader


TARGETS = (
    ("NSE:NIFTY26SEP23400CE", "2026-09-23", "2026-09-23"),
    ("NSE:NIFTY26SEP23400PE", "2026-09-23", "2026-09-23"),
    ("NSE:NIFTY26SEP23450CE", "2026-09-23", "2026-09-23"),
)


def safe_find_completed_job(
    self: HistoricalDownloader,
    symbol: str,
    resolution: str,
    range_from: str,
    range_to: str,
    source: str,
) -> dict[str, Any] | None:
    query = """
        SELECT *
        FROM download_jobs
        WHERE broker = 'FYERS'
          AND symbol = ?
          AND resolution = ?
          AND range_from = ?
          AND range_to = ?
        ORDER BY id DESC
        LIMIT 1
    """
    with self._connect() as connection:
        row = connection.execute(
            query,
            (symbol, resolution, range_from, range_to),
        ).fetchone()
    return dict(row) if row is not None else None


def inspect_targets():
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = []
        for symbol, range_from, range_to in TARGETS:
            instrument = db.execute(
                """
                SELECT id, symbol, expiry_date, strike, option_type
                FROM instruments
                WHERE broker='FYERS' AND symbol=?
                """,
                (symbol,),
            ).fetchone()
            if instrument is None:
                rows.append({
                    "symbol": symbol,
                    "status": "INSTRUMENT_MISSING",
                    "range_from": range_from,
                    "range_to": range_to,
                })
                continue

            candle_count = int(db.execute(
                """
                SELECT COUNT(*)
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source='FYERS_FNO_HISTORY'
                """,
                (int(instrument[0]),),
            ).fetchone()[0])

            rows.append({
                "instrument_id": int(instrument[0]),
                "symbol": str(instrument[1]),
                "expiry_date": str(instrument[2]),
                "strike": float(instrument[3]),
                "option_type": str(instrument[4]),
                "range_from": range_from,
                "range_to": range_to,
                "stored_candles": candle_count,
                "status": "READY" if candle_count == 0 else "ALREADY_HAS_CANDLES",
            })
    return rows


def apply_downloads():
    targets = inspect_targets()
    bad = [
        item for item in targets
        if item["status"] != "READY"
    ]
    if bad:
        raise RuntimeError(
            "Refusing acquisition because target preconditions are not met: "
            + json.dumps(bad, indent=2)
        )

    downloader = HistoricalDownloader()
    downloader._find_completed_job = MethodType(
        safe_find_completed_job,
        downloader,
    )

    results = []
    for symbol, range_from, range_to in TARGETS:
        print(
            f"\nACQUIRING {symbol} | {range_from} -> {range_to}"
        )
        result = downloader.download_symbol(
            symbol=symbol,
            range_from=range_from,
            range_to=range_to,
            resolution="1",
            mode="expired",
        )
        results.append(result)

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually download and store the three target histories.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    args = parser.parse_args()

    print("=" * 100)
    print("KUNAL QUANT - TARGETED ZERO-CANDLE OPTION ACQUISITION")
    print("=" * 100)
    print("Targets only 3 required symbols.")
    print("Canonical source files are not modified.")
    print()

    targets = inspect_targets()
    for item in targets:
        print(
            f"{item['symbol']} | id={item.get('instrument_id')} | "
            f"expiry={item.get('expiry_date')} | strike={item.get('strike')} | "
            f"type={item.get('option_type')} | stored_candles={item.get('stored_candles')} | "
            f"{item['status']}"
        )

    if not args.apply:
        print()
        print("DRY RUN ONLY — no downloads and no database changes.")
        print("Use --apply to acquire exactly these three histories.")
        return

    results = apply_downloads()

    print()
    print("=" * 100)
    print("TARGETED ACQUISITION RESULT")
    print("=" * 100)
    print(json.dumps(results, indent=2))

    payload = {
        "targets": TARGETS,
        "results": results,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
