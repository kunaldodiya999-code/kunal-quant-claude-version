"""
Kunal Quant - Required Option Contract Repair Plan

READ-ONLY preflight for the 49 contracts required by the current KTMI
sample. It identifies:
  - exact local matches
  - local symbol matches whose metadata is wrong
  - missing symbols

It does not call FYERS, change the database, or download data.

The output is intended to be the gate immediately before repairing the
33 metadata-corrupted required contracts and running targeted acquisition.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH
from strategies.option_contract_resolver import OptionContractResolver
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)


def option_type_from_symbol(symbol: str) -> str | None:
    value = str(symbol).strip().upper()
    if value.endswith("CE"):
        return "CE"
    if value.endswith("PE"):
        return "PE"
    return None


def strike_from_symbol(symbol: str) -> int | None:
    value = str(symbol).strip().upper()
    if not value.startswith("NSE:NIFTY"):
        return None
    if not value.endswith(("CE", "PE")):
        return None
    body = value[len("NSE:NIFTY") : -2]
    match = re.search(r"(\d{4,5})$", body)
    return int(match.group(1)) if match else None


def build_required_contracts() -> tuple[int, int, dict[tuple[str, int, str], dict[str, int]]]:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    required: dict[tuple[str, int, str], dict[str, int]] = {}

    for event in pipeline.events:
        bar = bars[event.index]
        entry_date = __import__("datetime").datetime.fromtimestamp(
            bar.timestamp,
            tz=__import__("zoneinfo").ZoneInfo("Asia/Kolkata"),
        ).date()
        option_type = "CE" if event.direction.value == "LONG" else "PE"
        expiry = resolver.find_nearest_expiry(entry_date, option_type).isoformat()
        strike = resolver.calculate_atm_strike(bar.close)
        key = (expiry, strike, option_type)
        item = required.setdefault(key, {"event_count": 0})
        item["event_count"] += 1

    return len(bars), len(pipeline.events), required


def plan(
    required: dict[tuple[str, int, str], dict[str, int]]
) -> dict[str, list[dict[str, object]]]:
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT id, symbol, expiry_date, strike, option_type
            FROM instruments
            WHERE broker = 'FYERS'
              AND underlying = 'NIFTY'
              AND option_type IN ('CE','PE')
            ORDER BY id
            """
        ).fetchall()

        by_exact = {}
        by_symbol_contract = {}

        for row in rows:
            record = {
                "instrument_id": int(row[0]),
                "symbol": str(row[1]),
                "expiry_date": str(row[2]),
                "strike": int(float(row[3])) if row[3] is not None else None,
                "option_type": str(row[4]),
            }
            by_exact[
                (record["expiry_date"], record["strike"], record["option_type"])
            ] = record

            parsed_strike = strike_from_symbol(record["symbol"])
            parsed_type = option_type_from_symbol(record["symbol"])
            by_symbol_contract[
                (record["expiry_date"], parsed_strike, parsed_type)
            ] = record

        exact: list[dict[str, object]] = []
        repairs: list[dict[str, object]] = []
        missing: list[dict[str, object]] = []

        for (expiry, strike, option_type), metadata in sorted(required.items()):
            key = (expiry, strike, option_type)
            if key in by_exact:
                record = dict(by_exact[key])
                record["event_count"] = metadata["event_count"]
                exact.append(record)
                continue

            record = by_symbol_contract.get(key)
            if record is None:
                missing.append(
                    {
                        "expiry": expiry,
                        "strike": strike,
                        "option_type": option_type,
                        "event_count": metadata["event_count"],
                    }
                )
                continue

            candles = db.execute(
                """
                SELECT COUNT(*)
                FROM candles
                WHERE instrument_id = ?
                  AND source = 'FYERS_FNO_HISTORY'
                  AND resolution = '1'
                """,
                (record["instrument_id"],),
            ).fetchone()[0]

            repairs.append(
                {
                    **record,
                    "expected_strike": strike,
                    "expected_option_type": option_type,
                    "expected_expiry": expiry,
                    "event_count": metadata["event_count"],
                    "candle_count": int(candles),
                }
            )

    return {
        "exact": exact,
        "metadata_repairs": repairs,
        "missing_symbols": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars, events, required = build_required_contracts()
    report = plan(required)

    print("=" * 100)
    print("KUNAL QUANT - REQUIRED CONTRACT REPAIR PLAN")
    print("=" * 100)
    print("READ-ONLY: no database writes, no FYERS calls, no downloads")
    print()
    print(f"3M bars examined          : {bars:,}")
    print(f"KTMI events examined      : {events:,}")
    print(f"Required contracts        : {len(required):,}")
    print(f"Exact local matches       : {len(report['exact']):,}")
    print(f"Metadata repairs required : {len(report['metadata_repairs']):,}")
    print(f"Missing local symbols     : {len(report['missing_symbols']):,}")
    print()

    if report["metadata_repairs"]:
        print("METADATA REPAIRS")
        for item in report["metadata_repairs"]:
            print(
                f"{item['expected_expiry']} | {int(item['expected_strike']):>6} | "
                f"{item['expected_option_type']} | events={int(item['event_count']):>3} | "
                f"id={int(item['instrument_id'])} | {item['symbol']} | "
                f"stored_strike={item['strike']} | candles={int(item['candle_count'])}"
            )
        print()

    if report["missing_symbols"]:
        print("MISSING LOCAL SYMBOLS")
        for item in report["missing_symbols"]:
            print(
                f"{item['expiry']} | {int(item['strike']):>6} | "
                f"{item['option_type']} | events={int(item['event_count']):>3}"
            )
        print()

    payload = {
        "database_path": str(DATABASE_PATH),
        "sample_3m_bars": bars,
        "ktmi_events": events,
        "required_contracts": len(required),
        **report,
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report written to: {args.json}")

    print()
    print("NO DATABASE CHANGES WERE MADE.")


if __name__ == "__main__":
    main()
