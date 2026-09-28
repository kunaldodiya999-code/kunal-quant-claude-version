"""
Kunal Quant - Required Option Contract Gap Audit

READ-ONLY PROPOSAL

This diagnostic reconstructs the exact unique option contracts required by
the current KTMI event pipeline, compares them with the canonical local
instruments/candles tables, and checks only the missing contracts against
FYERS' expired-contract endpoint.

Safety:
- no database writes
- no instrument registration
- no candle downloads
- no resolver changes
- no KTMI/strategy changes
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api.fyers_client import FyersClient
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from strategies.option_contract_resolver import OptionContractResolver


TZ = ZoneInfo("Asia/Kolkata")
UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
CANDLE_SOURCE = "FYERS_FNO_HISTORY"


def extract_option_symbols(response: object) -> set[str]:
    """Extract NIFTY option symbols from supported FYERS response shapes."""
    if not isinstance(response, dict):
        return set()

    data = response.get("data", {})
    if not isinstance(data, dict):
        return set()

    candidates: list[object] = []

    legacy_symbols = data.get("symbols", [])
    if isinstance(legacy_symbols, list):
        candidates.extend(legacy_symbols)

    contracts = data.get("contracts", {})
    if isinstance(contracts, dict):
        options = contracts.get("options", [])
        if isinstance(options, list):
            candidates.extend(options)

    return {
        value.strip()
        for value in candidates
        if isinstance(value, str)
        and value.strip().startswith("NSE:NIFTY")
        and value.strip().endswith(("CE", "PE"))
    }


def option_type_from_symbol(symbol: str) -> str | None:
    """Return CE/PE for a NIFTY option symbol."""
    if not isinstance(symbol, str):
        return None

    if symbol.endswith("CE"):
        return "CE"
    if symbol.endswith("PE"):
        return "PE"
    return None


def strike_from_symbol(symbol: str) -> int | None:
    """
    Parse the trailing strike from historical FYERS NIFTY symbols.

    Supported examples:
      NSE:NIFTY2692223250CE -> 23250
      NSE:NIFTY26SEP23400CE -> 23400
      NSE:NIFTY24N2118200CE -> 18200
    """
    if not isinstance(symbol, str):
        return None

    if not (
        symbol.startswith("NSE:NIFTY")
        and symbol.endswith(("CE", "PE"))
    ):
        return None

    body = symbol[len("NSE:NIFTY") : -2]

    digits = []
    for char in reversed(body):
        if char.isdigit():
            digits.append(char)
        else:
            break

    if not digits:
        return None

    trailing_digits = "".join(reversed(digits))

    # NIFTY strikes in the supported historical sample are represented
    # by 4- or 5-digit integers. Prefer 5 digits but accept 4 digits.
    for width in (5, 4):
        if len(trailing_digits) >= width:
            candidate = trailing_digits[-width:]
            try:
                return int(candidate)
            except ValueError:
                return None

    return None


def build_required_contracts() -> tuple[
    int,
    int,
    dict[tuple[str, int, str], dict[str, object]],
    list[dict[str, object]],
]:
    """
    Reconstruct unique contracts required by the existing KTMI pipeline.

    Returns:
      bar_count
      event_count
      required map keyed by (expiry, strike, option_type)
      expiry lookup failures
    """
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )
    resolver = OptionContractResolver(DATABASE_PATH)

    required: dict[
        tuple[str, int, str],
        dict[str, object],
    ] = {}

    expiry_failures: list[dict[str, object]] = []

    for event in pipeline.events:
        bar = bars[event.index]
        entry_date = datetime.fromtimestamp(
            bar.timestamp,
            tz=TZ,
        ).date()

        option_type = (
            "CE"
            if event.direction.value == "LONG"
            else "PE"
        )

        strike = resolver.calculate_atm_strike(
            bar.close
        )

        try:
            expiry = resolver.find_nearest_expiry(
                entry_date=entry_date,
                option_type=option_type,
            )
        except LookupError as exc:
            expiry_failures.append(
                {
                    "timestamp": int(bar.timestamp),
                    "event_date": entry_date.isoformat(),
                    "price": float(bar.close),
                    "option_type": option_type,
                    "error": str(exc),
                }
            )
            continue

        key = (
            expiry.isoformat(),
            strike,
            option_type,
        )

        item = required.get(key)

        if item is None:
            required[key] = {
                "event_count": 1,
                "first_event_date": entry_date.isoformat(),
                "last_event_date": entry_date.isoformat(),
            }
        else:
            item["event_count"] = int(item["event_count"]) + 1
            item["first_event_date"] = min(
                str(item["first_event_date"]),
                entry_date.isoformat(),
            )
            item["last_event_date"] = max(
                str(item["last_event_date"]),
                entry_date.isoformat(),
            )

    return (
        len(bars),
        len(pipeline.events),
        required,
        expiry_failures,
    )


def audit_local_contract(
    expiry: str,
    strike: int,
    option_type: str,
) -> dict[str, object] | None:
    """Return local instrument/candle information for one exact contract."""
    with sqlite3.connect(DATABASE_PATH) as db:
        row = db.execute(
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
              AND expiry_date = ?
              AND strike = ?
              AND option_type = ?
            ORDER BY id
            LIMIT 1
            """,
            (expiry, strike, option_type),
        ).fetchone()

        if row is None:
            return None

        candle_count = db.execute(
            """
            SELECT COUNT(*)
            FROM candles
            WHERE instrument_id = ?
              AND resolution = '1'
              AND source = ?
            """,
            (int(row[0]), CANDLE_SOURCE),
        ).fetchone()[0]

    return {
        "instrument_id": int(row[0]),
        "symbol": str(row[1]),
        "expiry": str(row[2]),
        "strike": int(row[3]),
        "option_type": str(row[4]),
        "candle_count": int(candle_count),
    }


def fetch_fyers_expiry(
    client: FyersClient,
    expiry: str,
) -> dict[tuple[int, str], str]:
    """Fetch one FYERS expiry and index returned options by strike/type."""
    response = client.expired_contracts(
        symbol=UNDERLYING_SYMBOL,
        expiry_date=expiry,
    )

    indexed: dict[tuple[int, str], str] = {}

    for symbol in extract_option_symbols(response):
        strike = strike_from_symbol(symbol)
        option_type = option_type_from_symbol(symbol)

        if strike is None or option_type is None:
            continue

        indexed[(strike, option_type)] = symbol

    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only required NIFTY option contract gap audit"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.25,
        help="Delay in seconds between FYERS expiry calls.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional JSON report path.",
    )
    args = parser.parse_args()

    print("=" * 100)
    print("KUNAL QUANT - REQUIRED OPTION CONTRACT GAP AUDIT")
    print("=" * 100)
    print("READ-ONLY: no database writes, no downloads, no registrations")
    print()

    (
        bar_count,
        event_count,
        required,
        expiry_failures,
    ) = build_required_contracts()

    print(f"3M bars examined          : {bar_count:,}")
    print(f"KTMI events examined      : {event_count:,}")
    print(f"Unique required contracts : {len(required):,}")
    print(f"Expiry lookup failures    : {len(expiry_failures):,}")
    print()

    local_present: list[dict[str, object]] = []
    local_missing: list[dict[str, object]] = []
    local_zero_candle: list[dict[str, object]] = []

    for (expiry, strike, option_type), metadata in sorted(required.items()):
        local = audit_local_contract(
            expiry,
            strike,
            option_type,
        )

        record: dict[str, object] = {
            "expiry": expiry,
            "strike": strike,
            "option_type": option_type,
            **metadata,
            "local": local,
        }

        if local is None:
            local_missing.append(record)
        else:
            local_present.append(record)
            if int(local["candle_count"]) == 0:
                local_zero_candle.append(record)

    print("LOCAL COVERAGE")
    print(f"Already registered       : {len(local_present):,}")
    print(f"Missing locally          : {len(local_missing):,}")
    print(f"Registered, zero candles : {len(local_zero_candle):,}")
    print()

    missing_by_expiry: dict[str, list[dict[str, object]]] = defaultdict(list)
    for record in local_missing:
        missing_by_expiry[str(record["expiry"])].append(record)

    client = FyersClient()
    fyers_by_expiry: dict[str, dict[tuple[int, str], str]] = {}

    api_errors: list[dict[str, object]] = []

    print("FYERS DISCOVERY")
    print(f"Expiries requiring checks : {len(missing_by_expiry):,}")
    print()

    for expiry in sorted(missing_by_expiry):
        print(f"Checking expiry {expiry} ...")
        try:
            fyers_by_expiry[expiry] = fetch_fyers_expiry(
                client,
                expiry,
            )
            print(
                f"  FYERS option symbols: "
                f"{len(fyers_by_expiry[expiry]):,}"
            )
        except Exception as exc:
            api_errors.append(
                {
                    "expiry": expiry,
                    "error": str(exc),
                }
            )
            print(f"  API ERROR: {exc}")

        if args.delay > 0:
            time.sleep(args.delay)

    fyers_found: list[dict[str, object]] = []
    fyers_not_found: list[dict[str, object]] = []
    fyers_api_error_records: list[dict[str, object]] = []

    error_expiries = {
        str(item["expiry"])
        for item in api_errors
    }

    for record in local_missing:
        expiry = str(record["expiry"])
        key = (
            int(record["strike"]),
            str(record["option_type"]),
        )

        if expiry in error_expiries:
            record["fyers_status"] = "API_ERROR"
            fyers_api_error_records.append(record)
            continue

        symbol = fyers_by_expiry.get(expiry, {}).get(key)

        if symbol is None:
            record["fyers_status"] = "NOT_FOUND"
            fyers_not_found.append(record)
        else:
            record["fyers_status"] = "FOUND"
            record["fyers_symbol"] = symbol
            fyers_found.append(record)

    print()
    print("=" * 100)
    print("RESULT SUMMARY")
    print("=" * 100)
    print(f"Unique required contracts       : {len(required):,}")
    print(f"Already registered locally      : {len(local_present):,}")
    print(f"Missing locally                 : {len(local_missing):,}")
    print(f"Missing + FOUND at FYERS        : {len(fyers_found):,}")
    print(f"Missing + NOT FOUND at FYERS    : {len(fyers_not_found):,}")
    print(f"Missing + FYERS API errors      : {len(fyers_api_error_records):,}")
    print(f"Registered + zero candles       : {len(local_zero_candle):,}")
    print()

    def print_records(
        title: str,
        records: list[dict[str, object]],
    ) -> None:
        if not records:
            return

        print(title)
        for record in records:
            suffix = ""
            if "fyers_symbol" in record:
                suffix = f" | {record['fyers_symbol']}"
            elif record.get("local"):
                suffix = (
                    f" | {record['local']['symbol']}"
                    f" | candles={record['local']['candle_count']}"
                )

            print(
                f"{record['expiry']} | "
                f"{int(record['strike']):>6} | "
                f"{record['option_type']} | "
                f"events={int(record['event_count']):>3}"
                f"{suffix}"
            )
        print()

    print_records(
        "MISSING LOCALLY BUT FOUND AT FYERS",
        fyers_found,
    )
    print_records(
        "MISSING LOCALLY AND NOT FOUND AT FYERS",
        fyers_not_found,
    )
    print_records(
        "REGISTERED LOCALLY BUT ZERO CANDLES",
        local_zero_candle,
    )

    report = {
        "database_path": str(DATABASE_PATH),
        "sample_3m_bars": bar_count,
        "ktmi_events": event_count,
        "unique_required_contracts": len(required),
        "expiry_lookup_failures": expiry_failures,
        "already_registered": local_present,
        "missing_locally": local_missing,
        "missing_found_at_fyers": fyers_found,
        "missing_not_found_at_fyers": fyers_not_found,
        "missing_fyers_api_errors": fyers_api_error_records,
        "fyers_expiry_api_errors": api_errors,
        "registered_zero_candle": local_zero_candle,
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report written to: {args.json}")

    print("NO DATABASE CHANGES WERE MADE.")
    print("NO INSTRUMENTS WERE REGISTERED.")
    print("NO CANDLES WERE DOWNLOADED.")


if __name__ == "__main__":
    main()
