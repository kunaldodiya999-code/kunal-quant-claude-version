"""Repair FYERS NIFTY expired-option metadata without changing candle rows.

This is a data-maintenance utility. It preserves existing instrument IDs and
candle rows and updates only broker token / expiry / strike / option type /
active-state metadata from FYERS expired-contract responses.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sqlite3
import time
from datetime import date
from pathlib import Path

from config.settings import DATABASE_PATH
from instruments.instrument_manager import InstrumentManager


def historical_expiries(database_path: Path) -> list[str]:
    with sqlite3.connect(database_path) as db:
        rows = db.execute(
            """
            SELECT DISTINCT expiry_date
            FROM instruments
            WHERE broker='FYERS'
              AND underlying='NIFTY'
              AND option_type IN ('CE','PE')
              AND expiry_date IS NOT NULL
              AND expiry_date <= ?
            ORDER BY expiry_date
            """,
            (date.today().isoformat(),),
        ).fetchall()
    return [str(row[0]) for row in rows]


def repair_expiry(manager: InstrumentManager, expiry: str) -> tuple[int, int]:
    response = manager.fyers.expired_contracts(
        "NSE:NIFTY50-INDEX",
        expiry,
    )
    contracts = (
        response.get("data", {})
        .get("contracts", {})
        .get("options", [])
    )

    updated = 0
    missing = 0

    with sqlite3.connect(manager.repository.database_path) as db:
        for contract in contracts:
            symbol, token = manager._extract_contract_symbol(contract)
            try:
                record = manager._build_expired_instrument(
                    symbol=symbol,
                    underlying="NIFTY",
                    expiry_date=expiry,
                    broker_token=token,
                )
            except ValueError:
                continue

            cursor = db.execute(
                """
                UPDATE instruments
                SET broker_token=?,
                    expiry_date=?,
                    strike=?,
                    option_type=?,
                    is_active=0,
                    updated_at=CURRENT_TIMESTAMP
                WHERE broker='FYERS'
                  AND symbol=?
                  AND underlying='NIFTY'
                """,
                (
                    record["broker_token"],
                    record["expiry_date"],
                    record["strike"],
                    record["option_type"],
                    record["symbol"],
                ),
            )
            if cursor.rowcount:
                updated += cursor.rowcount
            else:
                missing += 1

        db.commit()

    return updated, missing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument("--sleep", type=float, default=0.35)
    args = parser.parse_args()

    manager = InstrumentManager(args.database)
    expiries = historical_expiries(args.database)

    print("=" * 90)
    print("KUNAL QUANT — FYERS NIFTY EXPIRED OPTION METADATA REPAIR")
    print("=" * 90)
    print(f"Database : {args.database}")
    print(f"Expiries : {len(expiries)}")
    print()

    total_updated = 0
    total_missing = 0

    for index, expiry in enumerate(expiries, start=1):
        try:
            updated, missing = repair_expiry(manager, expiry)
            total_updated += updated
            total_missing += missing
            print(
                f"[{index:03d}/{len(expiries):03d}] "
                f"{expiry} updated={updated:,} api_only={missing:,}"
            )
        except Exception as exc:
            print(f"[ERROR] {expiry}: {exc}")
        time.sleep(max(args.sleep, 0.0))

    print()
    print(f"Updated existing instruments : {total_updated:,}")
    print(f"FYERS contracts not registered: {total_missing:,}")
    print("METADATA REPAIR COMPLETE")


if __name__ == "__main__":
    main()
