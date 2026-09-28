"""
Kunal Quant - Zero-Candle Full Trade-Range Diagnostic

READ-ONLY follow-up after the three required zero-candle symbols were
acquired for their entry date.

Purpose:
- determine the exact start/end date of the current 20-day sample
- for the three target symbols, query FYERS expired_history across the full
  sample range
- report per-day candle counts and returned first/last timestamps

No database writes, registrations, or downloads.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api.fyers_client import FyersClient
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")

TARGETS = (
    "NSE:NIFTY26SEP23400CE",
    "NSE:NIFTY26SEP23400PE",
    "NSE:NIFTY26SEP23450CE",
)


def candle_local_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=TZ).date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars = load_complete_3m_bars()
    start_date = datetime.fromtimestamp(bars[0].timestamp, tz=TZ).date().isoformat()
    end_date = datetime.fromtimestamp(bars[-1].timestamp, tz=TZ).date().isoformat()

    client = FyersClient()
    results = []

    print("=" * 100)
    print("KUNAL QUANT - ZERO-CANDLE FULL TRADE-RANGE DIAGNOSTIC")
    print("=" * 100)
    print("READ-ONLY: no database writes, no registrations, no candle downloads")
    print()
    print(f"3M sample range           : {start_date} -> {end_date}")
    print(f"3M bars examined          : {len(bars):,}")
    print()

    for symbol in TARGETS:
        with sqlite3.connect(DATABASE_PATH) as db:
            row = db.execute(
                """
                SELECT i.id, i.expiry_date, i.strike, i.option_type,
                       COUNT(c.id)
                FROM instruments i
                LEFT JOIN candles c
                  ON c.instrument_id = i.id
                 AND c.resolution = '1'
                 AND c.source = 'FYERS_FNO_HISTORY'
                WHERE i.broker='FYERS'
                  AND i.symbol=?
                GROUP BY i.id
                """,
                (symbol,),
            ).fetchone()

        record = {
            "symbol": symbol,
            "database_instrument_id": int(row[0]) if row else None,
            "expiry": str(row[1]) if row else None,
            "strike": float(row[2]) if row else None,
            "option_type": str(row[3]) if row else None,
            "stored_candles": int(row[4]) if row else None,
            "sample_range_from": start_date,
            "sample_range_to": end_date,
        }

        print(f"Checking {symbol} | {start_date} -> {end_date}")
        try:
            response = client.expired_history(
                symbol=symbol,
                resolution="1",
                range_from=start_date,
                range_to=end_date,
                include_oi="1",
                include_greeks="1",
                date_format="1",
            )
            candles = response.get("candles", [])
            if not isinstance(candles, list):
                candles = []

            per_day = Counter()
            timestamps = []
            for candle in candles:
                if not candle:
                    continue
                ts = int(float(candle[0]))
                timestamps.append(ts)
                per_day[candle_local_date(ts)] += 1

            record["fyers_status"] = "OK"
            record["fyers_candle_count"] = len(candles)
            record["daily_counts"] = dict(sorted(per_day.items()))
            if timestamps:
                first_ts = min(timestamps)
                last_ts = max(timestamps)
                record["fyers_first_local"] = datetime.fromtimestamp(
                    first_ts, tz=TZ
                ).isoformat()
                record["fyers_last_local"] = datetime.fromtimestamp(
                    last_ts, tz=TZ
                ).isoformat()

            print(f"  FYERS candles: {len(candles):,}")
            print(f"  Days returned: {len(per_day):,}")
            for day, count in sorted(per_day.items()):
                print(f"    {day} -> {count} candles")
            if timestamps:
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
            time.sleep(args.delay)

    payload = {
        "sample_range": {"from": start_date, "to": end_date},
        "bars": len(bars),
        "targets": results,
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print()
        print(f"JSON report written to: {args.json}")

    print()
    print("NO DATABASE CHANGES WERE MADE.")


if __name__ == "__main__":
    main()
