"""
Kunal Quant — Register Required Missing-Expiry Contracts

PROPOSAL / DATA REPAIR TOOL

Default is DRY RUN.
Use --apply to:
1. verify the audit JSON contains the expected 30 FYERS-found tuples;
2. create a timestamped SQLite backup;
3. register only those exact FYERS symbols in instruments;
4. verify expiry/strike/type/symbol metadata.

No candle downloads.
Canonical Python source files are not modified.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSAL_ROOT = HERE.parent
CANONICAL_ROOT = HERE.parents[1]
for root in (PROPOSAL_ROOT, CANONICAL_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from config.settings import DATABASE_PATH
from instruments.expired_contract_registry import ExpiredContractRegistry
from database.repository import DatabaseRepository


EXPECTED_TOTAL = 30
EXPECTED_EXPIRIES = {
    "2026-08-25": 7,
    "2026-09-01": 14,
    "2026-09-08": 9,
}


def load_found_records(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = list(payload.get("fyers_found", []))
    return records


def validate_records(records: list[dict]) -> None:
    if len(records) != EXPECTED_TOTAL:
        raise RuntimeError(
            f"Expected {EXPECTED_TOTAL} FYERS-found contracts, got {len(records)}."
        )

    seen: set[tuple[str, int, str]] = set()
    counts: dict[str, int] = {}
    for item in records:
        key = (
            str(item["expiry"]),
            int(item["strike"]),
            str(item["option_type"]).upper(),
        )
        if key in seen:
            raise RuntimeError(f"Duplicate required contract: {key}")
        seen.add(key)
        expiry = key[0]
        counts[expiry] = counts.get(expiry, 0) + 1
        symbol = str(item.get("fyers_symbol", "")).strip()
        if not symbol:
            raise RuntimeError(f"Missing FYERS symbol for {key}.")
        if not symbol.startswith("NSE:NIFTY") or not symbol.endswith(("CE", "PE")):
            raise RuntimeError(f"Unexpected FYERS symbol for {key}: {symbol}")

    if counts != EXPECTED_EXPIRIES:
        raise RuntimeError(
            f"Unexpected per-expiry counts: {counts}; expected {EXPECTED_EXPIRIES}"
        )


def build_instrument(record: dict) -> dict:
    registry = ExpiredContractRegistry(database_path=DATABASE_PATH)
    return registry._build_instrument(
        symbol=str(record["fyers_symbol"]),
        underlying="NIFTY",
        expiry_date=str(record["expiry"]),
        broker_token=None,
    )


def verify(records: list[dict]) -> list[dict]:
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = []
        for item in records:
            row = db.execute(
                """
                SELECT id, symbol, expiry_date, strike, option_type
                FROM instruments
                WHERE broker = 'FYERS'
                  AND symbol = ?
                """,
                (str(item["fyers_symbol"]),),
            ).fetchone()
            rows.append((item, row))

    failures = []
    for item, row in rows:
        expected = (
            str(item["fyers_symbol"]),
            str(item["expiry"]),
            int(item["strike"]),
            str(item["option_type"]).upper(),
        )
        actual = None if row is None else (
            str(row[1]),
            str(row[2]),
            int(float(row[3])),
            str(row[4]).upper(),
        )
        if actual != expected:
            failures.append(
                {
                    "expected": expected,
                    "actual": actual,
                }
            )
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        type=Path,
        default=Path.home() / "Desktop" / "missing_expiry_contracts.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually register the 30 contracts. Without this flag, dry-run only.",
    )
    args = parser.parse_args()

    records = load_found_records(args.json)
    validate_records(records)

    print("=" * 100)
    print("KUNAL QUANT — REQUIRED MISSING-EXPIRY CONTRACT REGISTRATION")
    print("=" * 100)
    print(f"Audit JSON                     : {args.json}")
    print(f"Exact FYERS contracts          : {len(records)}")
    print(f"Apply mode                     : {args.apply}")
    print()

    before_failures = verify(records)
    already_present = len(records) - len(before_failures)
    print(f"Already correctly registered   : {already_present}")
    print(f"Not yet correctly registered   : {len(before_failures)}")
    print()

    if not args.apply:
        print("DRY RUN ONLY — no database changes.")
        print("Use --apply only after confirming the 30-record audit result.")
        return

    database_path = Path(DATABASE_PATH)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = database_path.with_name(
        f"{database_path.stem}.backup_missing_expiry_{timestamp}{database_path.suffix}"
    )
    shutil.copy2(database_path, backup_path)

    repository = DatabaseRepository(database_path)

    for record in records:
        instrument = build_instrument(record)
        repository.upsert_instrument(instrument)

    failures = verify(records)
    if failures:
        raise RuntimeError(
            f"Post-registration verification failed for {len(failures)} contracts: "
            f"{failures[:3]}"
        )

    print(f"Backup created                 : {backup_path}")
    print(f"Contracts registered/confirmed : {len(records)}")
    print("Metadata verification          : PASS")
    print("NO CANDLE DOWNLOADS WERE PERFORMED.")


if __name__ == "__main__":
    main()
