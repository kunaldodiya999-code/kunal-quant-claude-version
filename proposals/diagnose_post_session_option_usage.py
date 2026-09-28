"""
Kunal Quant - Post-Session Option Usage Diagnostic

READ-ONLY diagnostic for the current resilient real-option sample.

Project configuration expects the final 1M market candle at 15:29:00.
FYERS option history in the database can contain candles through 15:39.

This diagnostic runs the current proposal-only resilient sample and reports:
- entries after 15:29
- exits after 15:29
- open trades
- the maximum option timestamp actually used by a closed trade

No database writes, FYERS calls, downloads, or canonical source changes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import EXPECTED_LAST_1M_CANDLE
from run_real_option_sample_resilient import (
    run_resilient,
)
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from backtest.fyers_option_candles import FyersOptionCandleLoader
from config.settings import DATABASE_PATH
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")


def local_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=TZ)


def minute_is_after_session(ts: int) -> bool:
    dt = local_dt(ts)
    return dt.hour > 15 or (dt.hour == 15 and dt.minute >= 30)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars = load_complete_3m_bars()
    events = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    ).events

    loader = FyersOptionCandleLoader(DATABASE_PATH)
    result = run_resilient(
        bars=bars,
        events=events,
        resolver=OptionContractResolver(),
        option_loader=loader,
        end_timestamp=bars[-1].timestamp + 3600,
    )

    late_entries = []
    late_exits = []
    max_option_timestamp = None

    for trade in result.trades:
        entry = trade.entry
        if minute_is_after_session(entry.entry_timestamp):
            late_entries.append({
                "symbol": entry.contract.symbol,
                "signal_timestamp": int(entry.signal_timestamp),
                "entry_timestamp": int(entry.entry_timestamp),
                "entry_local": local_dt(entry.entry_timestamp).isoformat(),
            })

        for exit_event in trade.result.exits:
            ts = int(exit_event.timestamp)
            if max_option_timestamp is None or ts > max_option_timestamp:
                max_option_timestamp = ts

            if minute_is_after_session(ts):
                late_exits.append({
                    "symbol": entry.contract.symbol,
                    "reason": exit_event.reason.value,
                    "timestamp": ts,
                    "local": local_dt(ts).isoformat(),
                    "price": float(exit_event.price),
                    "quantity": int(exit_event.quantity),
                    "pnl": float(exit_event.pnl),
                })

    print("=" * 100)
    print("KUNAL QUANT - POST-SESSION OPTION USAGE DIAGNOSTIC")
    print("=" * 100)
    print("READ-ONLY: no database writes, no FYERS calls, no downloads")
    print()
    print(f"Configured last 1M candle : {EXPECTED_LAST_1M_CANDLE}")
    print(f"3M sample range           : {local_dt(bars[0].timestamp).date()} -> {local_dt(bars[-1].timestamp).date()}")
    print(f"Completed trades           : {sum(t.result.closed for t in result.trades):,}")
    print(f"Open trades                : {result.open_trades:,}")
    print(f"Allocation rejected        : {result.allocation_rejected_events:,}")
    print(f"Late entries (>=15:30)     : {len(late_entries):,}")
    print(f"Late exits (>=15:30)       : {len(late_exits):,}")

    if max_option_timestamp is not None:
        print(
            f"Latest closed-trade exit    : "
            f"{local_dt(max_option_timestamp).isoformat()}"
        )

    if late_entries:
        print()
        print("LATE ENTRIES")
        for item in late_entries:
            print(
                f"{item['symbol']} | "
                f"{item['entry_local']}"
            )

    if late_exits:
        print()
        print("LATE EXITS")
        for item in late_exits:
            print(
                f"{item['symbol']} | {item['local']} | "
                f"{item['reason']} | price={item['price']:.2f} | "
                f"qty={item['quantity']} | pnl={item['pnl']:.2f}"
            )

    report = {
        "configured_last_1m_candle": EXPECTED_LAST_1M_CANDLE,
        "sample_start": local_dt(bars[0].timestamp).isoformat(),
        "sample_end": local_dt(bars[-1].timestamp).isoformat(),
        "completed_trades": sum(t.result.closed for t in result.trades),
        "open_trades": result.open_trades,
        "allocation_rejected_events": result.allocation_rejected_events,
        "late_entries": late_entries,
        "late_exits": late_exits,
        "latest_closed_trade_exit": (
            local_dt(max_option_timestamp).isoformat()
            if max_option_timestamp is not None
            else None
        ),
        "status": "LATE_USAGE_FOUND" if (late_entries or late_exits) else "NO_LATE_USAGE",
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print()
        print(f"JSON report written to: {args.json}")

    print()
    print(f"DIAGNOSTIC STATUS          : {report['status']}")


if __name__ == "__main__":
    main()
