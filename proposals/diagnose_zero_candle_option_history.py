"""
Kunal Quant - Zero-Candle Option History Diagnostic

READ-ONLY diagnostic for required option contracts that are now correctly
registered but have zero FYERS_FNO_HISTORY candles.

It:
- reconstructs the current 2,500-bar / 300-event KTMI requirement set
- identifies required contracts with zero stored candles
- calls FYERS expired_history for only those symbols
- uses the associated event-date range
- reports returned candle count and first/last timestamps

No database writes, instrument registration, or candle downloads.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api.fyers_client import FyersClient
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")
SOURCE = "FYERS_FNO_HISTORY"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    required = {}

    for event in pipeline.events:
        bar = bars[event.index]
        event_date = datetime.fromtimestamp(bar.timestamp, tz=TZ).date()
        direction = event.direction.value
        option_type = "CE" if direction == "LONG" else "PE"
        expiry = resolver.find_nearest_expiry(event_date, option_type).isoformat()
        strike = resolver.calculate_atm_strike(bar.close)
        key = (expiry, strike, option_type)
        item = required.setdefault(
            key,
            {
                "event_count": 0,
                "event_dates": [],
            },
        )
        item["event_count"] += 1
        item["event_dates"].append(event_date.isoformat())

    zero = []

    with sqlite3.connect(DATABASE_PATH) as db:
        for (expiry, strike, option_type), meta in sorted(required.items()):
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
                continue

            candle_count = int(db.execute(
                """
                SELECT COUNT(*)
                FROM candles
                WHERE instrument_id=?
                  AND resolution='1'
                  AND source=?
                """,
                (int(row[0]), SOURCE),
            ).fetchone()[0])

            if candle_count == 0:
                zero.append({
                    "instrument_id": int(row[0]),
                    "symbol": str(row[1]),
                    "expiry": str(row[2]),
                    "strike": int(float(row[3])),
                    "option_type": str(row[4]),
                    "event_count": int(meta["event_count"]),
                    "event_date_from": min(meta["event_dates"]),
                    "event_date_to": max(meta["event_dates"]),
                })

    client = FyersClient()
    results = []

    print("=" * 100)
    print("KUNAL QUANT - ZERO-CANDLE OPTION HISTORY DIAGNOSTIC")
    print("=" * 100)
    print("READ-ONLY: no database writes, no registrations, no candle downloads")
    print()
    print(f"3M bars examined            : {len(bars):,}")
    print(f"KTMI events examined        : {len(pipeline.events):,}")
    print(f"Required zero-candle symbols: {len(zero):,}")
    print()

    for item in zero:
        print(
            f"Checking {item['symbol']} | "
            f"events={item['event_count']} | "
            f"range={item['event_date_from']} -> {item['event_date_to']}"
        )

        record = dict(item)
        try:
            response = client.expired_history(
                symbol=item["symbol"],
                resolution="1",
                range_from=item["event_date_from"],
                range_to=item["event_date_to"],
                include_oi="1",
                include_greeks="1",
                date_format="1",
            )
            candles = response.get("candles", [])
            if not isinstance(candles, list):
                candles = []

            record["fyers_status"] = "OK"
            record["fyers_candle_count"] = len(candles)

            if candles:
                timestamps = [int(float(c[0])) for c in candles if c]
                record["fyers_first_timestamp"] = min(timestamps)
                record["fyers_last_timestamp"] = max(timestamps)
                record["fyers_first_local"] = datetime.fromtimestamp(
                    min(timestamps), tz=TZ
                ).isoformat()
                record["fyers_last_local"] = datetime.fromtimestamp(
                    max(timestamps), tz=TZ
                ).isoformat()

            print(f"  FYERS candles: {len(candles):,}")
            if candles:
                print(
                    f"  Range returned: {record['fyers_first_local']} -> "
                    f"{record['fyers_last_local']}"
                )
        except Exception as exc:
            record["fyers_status"] = "ERROR"
            record["error"] = str(exc)
            print(f"  FYERS ERROR: {exc}")

        results.append(record)

        if args.delay > 0:
            import time
            time.sleep(args.delay)

    print()
    print("RESULTS")
    for item in results:
        print(
            f"{item['symbol']} | FYERS={item['fyers_status']} | "
            f"candles={item.get('fyers_candle_count', 0)}"
        )

    payload = {
        "database_path": str(DATABASE_PATH),
        "sample_3m_bars": len(bars),
        "ktmi_events": len(pipeline.events),
        "required_zero_candle_symbols": zero,
        "fyers_results": results,
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
