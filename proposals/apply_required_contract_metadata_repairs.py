"""
Kunal Quant - Apply Required Option Contract Metadata Repairs

SAFETY-GATED repair for only the option contracts required by the current
KTMI sample.

Default: DRY RUN. No database changes.
Use --apply to:
  1. create a timestamped SQLite backup beside the database
  2. re-build the required-contract repair plan
  3. update only the planned instrument rows
  4. verify every repaired row now matches the expected strike/type/expiry

This does not call FYERS and does not download candles.
It intentionally does NOT repair every one of the historical metadata
mismatches in the database; only the current 49-contract KTMI sample is
eligible.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from config.settings import DATABASE_PATH
from plan_required_contract_repairs import build_required_contracts, plan


def apply_repairs(repairs: list[dict[str, object]]) -> Path:
    database_path = Path(DATABASE_PATH)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = database_path.with_name(
        f"{database_path.stem}.backup_{timestamp}{database_path.suffix}"
    )
    shutil.copy2(database_path, backup_path)

    with sqlite3.connect(database_path) as db:
        db.execute("BEGIN")

        for item in repairs:
            result = db.execute(
                """
                UPDATE instruments
                SET
                    expiry_date = ?,
                    strike = ?,
                    option_type = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND broker = 'FYERS'
                  AND underlying = 'NIFTY'
                  AND expiry_date = ?
                """,
                (
                    str(item["expected_expiry"]),
                    float(item["expected_strike"]),
                    str(item["expected_option_type"]),
                    int(item["instrument_id"]),
                    str(item["expiry_date"]),
                ),
            )

            if result.rowcount != 1:
                db.rollback()
                raise RuntimeError(
                    "Repair guard failed for "
                    f"id={item['instrument_id']} symbol={item['symbol']} "
                    f"(expected exactly one row to update)."
                )

        db.commit()

        for item in repairs:
            row = db.execute(
                """
                SELECT expiry_date, strike, option_type
                FROM instruments
                WHERE id = ?
                """,
                (int(item["instrument_id"]),),
            ).fetchone()

            if row is None:
                raise RuntimeError(
                    f"Verification failed: instrument disappeared: "
                    f"id={item['instrument_id']}"
                )

            actual = (
                str(row[0]),
                int(float(row[1])),
                str(row[2]),
            )
            expected = (
                str(item["expected_expiry"]),
                int(item["expected_strike"]),
                str(item["expected_option_type"]),
            )

            if actual != expected:
                raise RuntimeError(
                    "Verification failed for "
                    f"id={item['instrument_id']} symbol={item['symbol']}: "
                    f"actual={actual} expected={expected}"
                )

    return backup_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair only required NIFTY option metadata for the current KTMI sample"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually modify the database. Without this flag the script is dry-run only.",
    )
    args = parser.parse_args()

    bars, events, required = build_required_contracts()
    report = plan(required)
    repairs = list(report["metadata_repairs"])
    missing = list(report["missing_symbols"])

    print("=" * 100)
    print("KUNAL QUANT - REQUIRED CONTRACT METADATA REPAIR")
    print("=" * 100)
    print()
    print(f"3M bars examined          : {bars:,}")
    print(f"KTMI events examined      : {events:,}")
    print(f"Required contracts        : {len(required):,}")
    print(f"Exact local matches       : {len(report['exact']):,}")
    print(f"Metadata repairs planned  : {len(repairs):,}")
    print(f"Missing local symbols     : {len(missing):,}")
    print()

    if missing:
        raise SystemExit(
            "Refusing to apply: some required contracts have no local "
            "symbol match. Resolve acquisition/registration first."
        )

    if not repairs:
        print("No metadata repairs are required.")
        return

    if not args.apply:
        print("DRY RUN ONLY — no database changes.")
        print("Use --apply after reviewing the repair plan.")
        return

    backup_path = apply_repairs(repairs)

    print(f"Backup created: {backup_path}")
    print(f"Rows repaired : {len(repairs):,}")
    print("Verification   : PASS")
    print("Database repair complete.")


if __name__ == "__main__":
    main()
