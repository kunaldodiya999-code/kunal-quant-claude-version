"""
Kunal Quant — Acquire Required Missing-Expiry Option Candles

PROPOSAL / DATA ACQUISITION TOOL

Default is DRY RUN.
Use --run to download only the exact FYERS-found contracts in the
missing-expiry audit JSON.

For each contract, the range is:
    first_event_date -> expiry date

This is sufficient for the bounded sample because each required contract
belongs to the nearest weekly expiry used by its events and expires on the
expiry date.

The downloader uses the canonical HistoricalDownloader in expired mode,
1-minute resolution, with its existing resume-safe job/candle storage.

No source-code changes are made to canonical KunalQuant.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSAL_ROOT = HERE.parent
CANONICAL_ROOT = HERE.parents[1]
for root in (PROPOSAL_ROOT, CANONICAL_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from config.settings import DATABASE_PATH
from downloader.historical import HistoricalDownloader


EXPECTED_TOTAL = 30


def load_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("fyers_found", []))
    if len(records) != EXPECTED_TOTAL:
        raise RuntimeError(
            f"Expected {EXPECTED_TOTAL} FYERS-found contracts, got {len(records)}."
        )
    return records


def validate_record(item: dict) -> tuple[str, str, str, int]:
    symbol = str(item["fyers_symbol"]).strip()
    expiry = str(item["expiry"])
    first_event = str(item["first_event_date"])
    strike = int(item["strike"])
    option_type = str(item["option_type"]).upper()

    if not symbol.startswith("NSE:NIFTY") or not symbol.endswith(("CE", "PE")):
        raise RuntimeError(f"Invalid FYERS option symbol: {symbol}")
    if option_type not in {"CE", "PE"}:
        raise RuntimeError(f"Invalid option type: {option_type}")
    if first_event > expiry:
        raise RuntimeError(
            f"first_event_date {first_event} is after expiry {expiry} for {symbol}"
        )

    return symbol, first_event, expiry, strike


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=Path.home() / "Desktop" / "missing_expiry_contracts.json",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually download candles. Without this flag, dry-run only.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay between contract downloads in seconds.",
    )
    args = parser.parse_args()

    records = load_records(args.json)

    # Stable ordering makes logs deterministic.
    records.sort(
        key=lambda item: (
            str(item["expiry"]),
            int(item["strike"]),
            str(item["option_type"]),
            str(item["fyers_symbol"]),
        )
    )

    print("=" * 100)
    print("KUNAL QUANT — REQUIRED MISSING-EXPIRY OPTION CANDLE ACQUISITION")
    print("=" * 100)
    print(f"Audit JSON          : {args.json}")
    print(f"Contracts            : {len(records)}")
    print(f"Execution mode       : {'RUN' if args.run else 'DRY RUN'}")
    print()

    by_expiry = defaultdict(int)
    for item in records:
        by_expiry[str(item["expiry"])] += 1

    print("CONTRACT PLAN")
    for expiry, count in sorted(by_expiry.items()):
        print(f"  {expiry} : {count} contracts")
    print()

    for item in records:
        symbol, first_event, expiry, strike = validate_record(item)
        print(
            f"{symbol:32s} | {strike:>6} | "
            f"{str(item['option_type']).upper()} | "
            f"{first_event} -> {expiry}"
        )

    print()
    if not args.run:
        print("DRY RUN ONLY — no API calls and no database changes.")
        print("Use --run after the 30-contract registration has been verified.")
        return

    downloader = HistoricalDownloader(
        database_path=DATABASE_PATH,
        retry_delay_seconds=2.0,
    )

    totals = {
        "received": 0,
        "inserted": 0,
        "duplicates": 0,
        "failed": 0,
        "empty": 0,
    }

    import time

    for index, item in enumerate(records, start=1):
        symbol, first_event, expiry, _ = validate_record(item)

        print()
        print(f"[{index}/{len(records)}] {symbol} | {first_event} -> {expiry}")

        result = downloader.download_symbol(
            symbol=symbol,
            range_from=first_event,
            range_to=expiry,
            resolution="1",
            mode="expired",
        )

        for key in totals:
            totals[key] += int(result.get(key, 0))

        if args.delay > 0 and index < len(records):
            time.sleep(args.delay)

    print()
    print("=" * 100)
    print("ACQUISITION SUMMARY")
    print("=" * 100)
    for key, value in totals.items():
        print(f"{key:>10} : {value}")
    print()
    print("Acquisition run complete.")


if __name__ == "__main__":
    main()
