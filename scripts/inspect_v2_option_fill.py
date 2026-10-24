"""Inspect the real option candles around an Opening Breakout V2 signal."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DATABASE_PATH
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timestamp", type=int, required=True)
    parser.add_argument("--underlying", type=float, required=True)
    parser.add_argument("--direction", default="LONG")
    parser.add_argument("--before", type=int, default=120)
    parser.add_argument("--after", type=int, default=600)
    args = parser.parse_args()

    ts = args.timestamp
    entry_date = datetime.fromtimestamp(ts, tz=IST).date()
    contract = OptionContractResolver(DATABASE_PATH).resolve(
        underlying_price=args.underlying,
        entry_date=entry_date,
        direction=args.direction,
    )

    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT timestamp, open, high, low, close
            FROM candles
            WHERE instrument_id = ?
              AND resolution = '1'
              AND source = 'FYERS_FNO_HISTORY'
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp
            """,
            (contract.instrument_id, ts - args.before, ts + args.after),
        ).fetchall()

    print("=" * 100)
    print("KUNAL QUANT — REAL OPTION FILL DIAGNOSTIC")
    print("=" * 100)
    print(f"Contract      : {contract.symbol}")
    print(f"Instrument ID : {contract.instrument_id}")
    print(f"Signal TS     : {ts}")
    print(f"Signal time   : {datetime.fromtimestamp(ts, tz=IST)}")
    print("BUY limit     : signal option close + 1.00")
    print("-" * 100)
    print("timestamp           time                  O        H        L        C")
    print("-" * 100)

    if not rows:
        print("NO OPTION CANDLES FOUND")
    else:
        for row in rows:
            rts, op, hi, lo, cl = row
            marker = "  <-- SIGNAL" if rts == ts else ""
            print(
                f"{rts:<18} "
                f"{datetime.fromtimestamp(rts, tz=IST).strftime('%H:%M:%S')} "
                f"{op:>8.2f} {hi:>8.2f} {lo:>8.2f} {cl:>8.2f}{marker}"
            )

    print("=" * 100)


if __name__ == "__main__":
    main()
