"""
Kunal Quant - Option Allocation Failure Diagnostic

READ-ONLY diagnostic for the current real KTMI -> option sample.

Purpose:
- reproduce the existing option-entry boundary without running trade
  management
- calculate the locked V1 allocation required for one complete lot
- identify entries whose option premium makes one lot unaffordable

No database writes, no FYERS calls, no strategy/resolver/lifecycle changes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtest.models import BacktestBar
from backtest.option_entry_bridge import resolve_option_entries
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver


ALLOCATION = 15_000.0
LOT_SIZE = 65


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver(DATABASE_PATH)

    active_positions = []
    candidates = []

    # Process one event at a time so the same lifecycle admission boundary
    # used by the real runner is respected.
    for event in sorted(pipeline.events, key=lambda e: (e.index, e.timestamp)):
        try:
            entries = resolve_option_entries(
                bars=bars,
                events=[event],
                resolver=resolver,
                option_candle_loader=loader,
                active_positions=active_positions,
            )
        except LookupError:
            continue

        for entry in entries:
            required_cost = float(entry.entry_price) * LOT_SIZE
            affordable_lots = int(ALLOCATION // required_cost)
            record = {
                "strategy": entry.event.strategy_id.value,
                "direction": entry.event.direction.value,
                "signal_timestamp": int(entry.signal_timestamp),
                "entry_timestamp": int(entry.entry_timestamp),
                "symbol": entry.contract.symbol,
                "entry_price": float(entry.entry_price),
                "lot_size": LOT_SIZE,
                "one_lot_cost": required_cost,
                "allocation": ALLOCATION,
                "affordable_lots": affordable_lots,
                "affordable": affordable_lots >= 1,
            }
            candidates.append(record)

    failures = [item for item in candidates if not item["affordable"]]

    print("=" * 100)
    print("KUNAL QUANT - OPTION ALLOCATION FAILURE DIAGNOSTIC")
    print("=" * 100)
    print("READ-ONLY: no database writes, no FYERS calls, no downloads")
    print()
    print(f"3M bars examined       : {len(bars):,}")
    print(f"KTMI events examined   : {len(pipeline.events):,}")
    print(f"Accepted option entries: {len(candidates):,}")
    print(f"Unaffordable entries   : {len(failures):,}")
    print(f"Allocation             : {ALLOCATION:,.2f}")
    print(f"Lot size               : {LOT_SIZE}")
    print(f"Max premium for 1 lot  : {ALLOCATION / LOT_SIZE:,.4f}")
    print()

    print("UNAFFORDABLE ENTRIES")
    for item in failures[:50]:
        print(
            f"{item['symbol']} | {item['direction']} | "
            f"signal={item['signal_timestamp']} | "
            f"entry_ts={item['entry_timestamp']} | "
            f"entry={item['entry_price']:.2f} | "
            f"1-lot cost={item['one_lot_cost']:.2f} | "
            f"allocation={item['allocation']:.2f}"
        )

    report = {
        "allocation": ALLOCATION,
        "lot_size": LOT_SIZE,
        "max_premium_for_one_lot": ALLOCATION / LOT_SIZE,
        "sample_3m_bars": len(bars),
        "ktmi_events": len(pipeline.events),
        "accepted_option_entries": len(candidates),
        "unaffordable_entries": failures,
        "status": "FAIL" if failures else "PASS",
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print()
        print(f"JSON report written to: {args.json}")

    print()
    print(f"DIAGNOSTIC STATUS       : {'FAIL' if failures else 'PASS'}")


if __name__ == "__main__":
    main()
