"""
Kunal Quant - Contract Metadata Integrity Audit

READ-ONLY diagnostic for historical FYERS NIFTY option instruments.

Purpose:
- detect cases where a local instrument symbol encodes strike/type that
  disagree with the stored instruments.strike / option_type fields
- distinguish "truly missing" required contracts from contracts that exist
  locally by symbol but were registered with bad metadata
- does not modify the database
- does not call FYERS
- does not download or register anything
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

from config.settings import DATABASE_PATH
from diagnose_required_contract_gaps import (
    build_required_contracts,
)


def option_type_from_symbol(symbol: str) -> str | None:
    value = str(symbol).strip().upper()
    if value.endswith("CE"):
        return "CE"
    if value.endswith("PE"):
        return "PE"
    return None


def strike_from_symbol(symbol: str) -> int | None:
    """
    Parse the trailing NIFTY option strike.

    Supported historical examples include:
      NSE:NIFTY2692223250CE -> 23250
      NSE:NIFTY26SEP23400CE -> 23400
      NSE:NIFTY24N2118200CE -> 18200
    """
    value = str(symbol).strip().upper()
    if not value.startswith("NSE:NIFTY"):
        return None
    if not value.endswith(("CE", "PE")):
        return None

    body = value[len("NSE:NIFTY") : -2]
    match = re.search(r"(\d{4,5})$", body)
    if not match:
        return None

    return int(match.group(1))


def audit_local_metadata() -> dict[str, object]:
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT
                id,
                symbol,
                expiry_date,
                strike,
                option_type,
                underlying,
                broker
            FROM instruments
            WHERE broker = 'FYERS'
              AND underlying = 'NIFTY'
              AND option_type IN ('CE','PE')
            ORDER BY expiry_date, symbol, id
            """
        ).fetchall()

    mismatches: list[dict[str, object]] = []
    unparseable: list[dict[str, object]] = []
    duplicate_symbols: Counter[str] = Counter()

    for row in rows:
        instrument_id, symbol, expiry, stored_strike, stored_type, *_ = row
        symbol_value = str(symbol)
        duplicate_symbols[symbol_value] += 1

        parsed_strike = strike_from_symbol(symbol_value)
        parsed_type = option_type_from_symbol(symbol_value)

        if parsed_strike is None or parsed_type is None:
            unparseable.append(
                {
                    "instrument_id": int(instrument_id),
                    "symbol": symbol_value,
                    "expiry": str(expiry),
                    "stored_strike": stored_strike,
                    "stored_option_type": str(stored_type),
                    "parsed_strike": parsed_strike,
                    "parsed_option_type": parsed_type,
                }
            )
            continue

        try:
            stored_strike_int = int(float(stored_strike))
        except (TypeError, ValueError):
            stored_strike_int = None

        if (
            stored_strike_int != parsed_strike
            or str(stored_type).upper() != parsed_type
        ):
            mismatches.append(
                {
                    "instrument_id": int(instrument_id),
                    "symbol": symbol_value,
                    "expiry": str(expiry),
                    "stored_strike": stored_strike,
                    "stored_option_type": str(stored_type),
                    "parsed_strike": parsed_strike,
                    "parsed_option_type": parsed_type,
                }
            )

    duplicate_symbol_rows = [
        {"symbol": symbol, "count": count}
        for symbol, count in duplicate_symbols.items()
        if count > 1
    ]

    return {
        "total_option_instruments": len(rows),
        "metadata_mismatches": mismatches,
        "unparseable_symbols": unparseable,
        "duplicate_symbols": duplicate_symbol_rows,
    }


def crosscheck_required_contracts(
    required: dict[tuple[str, int, str], dict[str, object]],
) -> list[dict[str, object]]:
    """
    For each required contract that is missing by exact database fields,
    look for a local instrument whose SYMBOL itself encodes the requested
    expiry/strike/type. This is intentionally a read-only reconciliation.
    """
    results: list[dict[str, object]] = []

    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT
                id,
                symbol,
                expiry_date,
                strike,
                option_type
            FROM instruments
            WHERE broker = 'FYERS'
              AND underlying = 'NIFTY'
              AND option_type IN ('CE','PE')
            """
        ).fetchall()

    parsed_rows = []
    for row in rows:
        parsed_rows.append(
            {
                "instrument_id": int(row[0]),
                "symbol": str(row[1]),
                "expiry": str(row[2]),
                "stored_strike": row[3],
                "stored_type": str(row[4]),
                "parsed_strike": strike_from_symbol(str(row[1])),
                "parsed_type": option_type_from_symbol(str(row[1])),
            }
        )

    for (expiry, strike, option_type), metadata in sorted(required.items()):
        exact_rows = [
            row
            for row in parsed_rows
            if row["expiry"] == expiry
            and row["parsed_strike"] == strike
            and row["parsed_type"] == option_type
        ]

        if exact_rows:
            results.append(
                {
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": option_type,
                    "event_count": int(metadata["event_count"]),
                    "status": "PRESENT_BY_SYMBOL_METADATA_MISMATCH",
                    "matching_rows": exact_rows,
                }
            )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only FYERS NIFTY contract metadata integrity audit"
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    args = parser.parse_args()

    print("=" * 100)
    print("KUNAL QUANT - CONTRACT METADATA INTEGRITY AUDIT")
    print("=" * 100)
    print("READ-ONLY: no database writes, no FYERS calls, no downloads")
    print()

    metadata_report = audit_local_metadata()
    mismatches = list(metadata_report["metadata_mismatches"])
    unparseable = list(metadata_report["unparseable_symbols"])
    duplicates = list(metadata_report["duplicate_symbols"])

    print("LOCAL INSTRUMENT TABLE")
    print(
        f"Total FYERS NIFTY option instruments : "
        f"{int(metadata_report['total_option_instruments']):,}"
    )
    print(f"Metadata mismatches                 : {len(mismatches):,}")
    print(f"Unparseable NIFTY option symbols     : {len(unparseable):,}")
    print(f"Duplicate symbol groups             : {len(duplicates):,}")
    print()

    print("SAMPLE METADATA MISMATCHES (first 50)")
    for item in mismatches[:50]:
        print(
            f"{item['expiry']} | {item['symbol']:32s} | "
            f"stored strike={item['stored_strike']} "
            f"parsed strike={item['parsed_strike']} | "
            f"stored type={item['stored_option_type']} "
            f"parsed type={item['parsed_option_type']}"
        )
    print()

    bar_count, event_count, required, _ = build_required_contracts()
    symbol_matches = crosscheck_required_contracts(required)

    print("REQUIRED-CONTRACT RECONCILIATION")
    print(f"3M bars examined          : {bar_count:,}")
    print(f"KTMI events examined      : {event_count:,}")
    print(f"Unique required contracts : {len(required):,}")
    print(
        "Required contracts present by symbol but not by exact stored "
        f"metadata : {len(symbol_matches):,}"
    )
    print()

    for item in symbol_matches:
        print(
            f"{item['expiry']} | {int(item['strike']):>6} | "
            f"{item['option_type']} | events={int(item['event_count']):>3} | "
            f"symbol={item['matching_rows'][0]['symbol']}"
        )

    report = {
        "database_path": str(DATABASE_PATH),
        "metadata": metadata_report,
        "required_contracts": {
            "sample_3m_bars": bar_count,
            "ktmi_events": event_count,
            "unique_required_contracts": len(required),
            "present_by_symbol_metadata_mismatch": symbol_matches,
        },
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"JSON report written to: {args.json}")

    print()
    print("NO DATABASE CHANGES WERE MADE.")


if __name__ == "__main__":
    main()
