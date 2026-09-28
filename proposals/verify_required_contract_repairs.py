"""
Kunal Quant - Verify Required Option Contract Repairs

READ-ONLY post-repair verifier for the current KTMI sample.

It reconstructs the same required (expiry, strike, CE/PE) set used by
the resolver, checks exact local instrument metadata, checks symbol-decoded
strike/type, and reports candle coverage.

No FYERS calls. No database writes. No downloads.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from config.settings import DATABASE_PATH
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")


def parse_symbol(symbol: str) -> tuple[int | None, str | None]:
    value = str(symbol).strip().upper()
    option_type = "CE" if value.endswith("CE") else "PE" if value.endswith("PE") else None
    if option_type is None or not value.startswith("NSE:NIFTY"):
        return None, option_type
    body = value[len("NSE:NIFTY"):-2]
    match = re.search(r"(\d{4,5})$", body)
    return (int(match.group(1)) if match else None), option_type


def build_required():
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)
    required = {}

    for event in pipeline.events:
        bar = bars[event.index]
        entry_date = datetime.fromtimestamp(bar.timestamp, tz=TZ).date()
        option_type = "CE" if event.direction.value == "LONG" else "PE"
        expiry = resolver.find_nearest_expiry(entry_date, option_type).isoformat()
        strike = resolver.calculate_atm_strike(bar.close)
        key = (expiry, strike, option_type)
        required[key] = required.get(key, 0) + 1

    return len(bars), len(pipeline.events), required


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars, events, required = build_required()

    exact = []
    failures = []
    zero_candles = []
    nonzero = []

    with sqlite3.connect(DATABASE_PATH) as db:
        for (expiry, strike, option_type), event_count in sorted(required.items()):
            row = db.execute(
                """
                SELECT id, symbol, expiry_date, strike, option_type
                FROM instruments
                WHERE broker='FYERS'
                  AND underlying='NIFTY'
                  AND expiry_date=?
                  AND strike=?
                  AND option_type=?
                ORDER BY id
                LIMIT 1
                """,
                (expiry, strike, option_type),
            ).fetchone()

            if row is None:
                failures.append({
                    "expiry": expiry,
                    "strike": strike,
                    "option_type": option_type,
                    "event_count": event_count,
                    "reason": "EXACT_INSTRUMENT_NOT_FOUND",
                })
                continue

            parsed_strike, parsed_type = parse_symbol(row[1])
            candle_count = int(db.execute(
                """
                SELECT COUNT(*)
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source='FYERS_FNO_HISTORY'
                """,
                (int(row[0]),),
            ).fetchone()[0])

            record = {
                "instrument_id": int(row[0]),
                "symbol": str(row[1]),
                "expiry": str(row[2]),
                "stored_strike": int(float(row[3])),
                "stored_option_type": str(row[4]),
                "parsed_strike": parsed_strike,
                "parsed_option_type": parsed_type,
                "expected_expiry": expiry,
                "expected_strike": strike,
                "expected_option_type": option_type,
                "event_count": event_count,
                "candle_count": candle_count,
            }

            if (
                str(row[2]) != expiry
                or int(float(row[3])) != strike
                or str(row[4]) != option_type
                or parsed_strike != strike
                or parsed_type != option_type
            ):
                failures.append({**record, "reason": "METADATA_MISMATCH"})
            else:
                exact.append(record)
                (zero_candles if candle_count == 0 else nonzero).append(record)

    print("=" * 100)
    print("KUNAL QUANT - REQUIRED CONTRACT REPAIR VERIFICATION")
    print("=" * 100)
    print("READ-ONLY: no database writes, no FYERS calls, no downloads")
    print()
    print(f"3M bars examined          : {bars:,}")
    print(f"KTMI events examined      : {events:,}")
    print(f"Required contracts        : {len(required):,}")
    print(f"Exact verified contracts  : {len(exact):,}")
    print(f"Verification failures     : {len(failures):,}")
    print(f"Verified zero-candle      : {len(zero_candles):,}")
    print(f"Verified with candles     : {len(nonzero):,}")
    print()

    if zero_candles:
        print("ZERO-CANDLE REQUIRED CONTRACTS")
        for item in zero_candles:
            print(
                f"{item['expected_expiry']} | {int(item['expected_strike']):>6} | "
                f"{item['expected_option_type']} | events={item['event_count']:>3} | "
                f"id={item['instrument_id']} | {item['symbol']}"
            )
        print()

    if failures:
        print("VERIFICATION FAILURES")
        for item in failures:
            print(item)
        print()

    status = "PASS" if len(exact) == len(required) and not failures else "FAIL"
    print(f"VERIFICATION STATUS       : {status}")

    report = {
        "database_path": str(DATABASE_PATH),
        "sample_3m_bars": bars,
        "ktmi_events": events,
        "required_contracts": len(required),
        "exact_verified": exact,
        "verification_failures": failures,
        "zero_candle": zero_candles,
        "with_candles": nonzero,
        "status": status,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
