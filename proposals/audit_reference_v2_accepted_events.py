"""
Kunal Quant — Reference V2 accepted-event forensic ledger.

Proposal-only. Reads the local database and writes no market/trade data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from proposals.generate_reference_backtest_v2 import (
    build_trigger_config,
    load_all_complete_3m_bars,
    run_reference,
    select_last_days,
)
from strategies.ktmi_trigger_strategy import KTMITriggerStrategyConfig


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    all_bars = load_all_complete_3m_bars()
    sample_bars = select_last_days(all_bars, args.days)
    config = KTMITriggerStrategyConfig()
    result = run_reference(
        all_bars=all_bars,
        sample_bars=sample_bars,
        trigger_config=config,
    )
    records = list(result["event_audit"])

    accepted = [r for r in records if r.get("lifecycle_action") == "ENTER"]
    rejected = [r for r in records if r["outcome"] == "lifecycle_rejected"]

    print("=" * 120)
    print("KUNAL QUANT — V2 ACCEPTED EVENT FORENSIC LEDGER")
    print("=" * 120)
    print(f"Events in window       : {len(records):,}")
    print(f"Lifecycle accepted     : {len(accepted):,}")
    print(f"Lifecycle rejected     : {len(rejected):,}")
    print()
    print("ACCEPTED EVENTS")
    print("-" * 120)

    for i, r in enumerate(accepted, 1):
        contract = r.get("contract") or {}
        print(
            f"{i:02d} | {r['event_timestamp_local']} | "
            f"{r['strategy_id']} | {r['direction']} | "
            f"{contract.get('symbol', 'N/A')} | "
            f"entry={r.get('entry_timestamp_local', 'N/A')} "
            f"@ {r.get('entry_price', 'N/A')} | "
            f"outcome={r['outcome']} | "
            f"P&L={r.get('total_pnl', 'N/A')}"
        )
        if r.get("exits"):
            for x in r["exits"]:
                print(
                    f"     EXIT | {x['timestamp_local']} | "
                    f"{x['reason']} | price={x['price']} | "
                    f"qty={x['quantity']} | pnl={x['pnl']}"
                )

    summary = {
        "events": len(records),
        "lifecycle_accepted": len(accepted),
        "lifecycle_rejected": len(rejected),
        "outcomes": {},
    }
    for r in records:
        summary["outcomes"][r["outcome"]] = (
            summary["outcomes"].get(r["outcome"], 0) + 1
        )

    print()
    print("OUTCOME CHECK")
    for outcome, count in sorted(summary["outcomes"].items()):
        print(f"{outcome:24s}: {count:,}")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"summary": summary, "records": records}, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"JSON written to: {args.json}")


if __name__ == "__main__":
    main()
