"""
Read-only V2 lifecycle rejection audit.

Uses the exact V2 reference runner and wraps only its imported
evaluate_signal function to capture the lifecycle decision metadata that
the runner currently discards.

No database changes.
No canonical KunalQuant changes.
No trading behavior changes.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CANONICAL = HERE.parents[1]

for p in (ROOT, CANONICAL):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import proposals.generate_reference_backtest_v2 as v2
from backtest.position_lifecycle import SignalAction


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=20)
    ap.add_argument(
        "--report",
        type=Path,
        default=Path.home() / "Desktop" / "reference_v2_lifecycle_audit.json",
    )
    args = ap.parse_args()

    bars = v2.load_all_complete_3m_bars()
    sample = v2.select_last_days(bars, args.days)

    cfg = v2.build_trigger_config(
        argparse.Namespace(
            disable_speed_sources=False,
            disable_momentum=False,
            long_speed_ce_trigger=0.50,
            short_speed_pe_trigger=0.50,
            momentum_ce_trigger=0.50,
            momentum_pe_trigger=-0.50,
        )
    )

    # Capture the exact lifecycle decisions made by V2 without modifying
    # evaluate_signal or the canonical lifecycle implementation.
    original_evaluate_signal = v2.evaluate_signal
    decisions: list[dict] = []

    def capture_evaluate_signal(**kwargs):
        decision = original_evaluate_signal(**kwargs)
        decisions.append(
            {
                "strategy_id": kwargs["strategy_id"],
                "direction": kwargs["direction"],
                "symbol": kwargs["symbol"],
                "active_positions": [
                    {
                        "strategy_id": position.strategy_id,
                        "direction": position.direction,
                        "symbol": position.symbol,
                    }
                    for position in kwargs.get("active_positions", [])
                ],
                "action": decision.action.value,
                "reason": decision.reason,
            }
        )
        return decision

    v2.evaluate_signal = capture_evaluate_signal
    try:
        result = v2.run_reference(
            all_bars=bars,
            sample_bars=sample,
            trigger_config=cfg,
        )
    finally:
        v2.evaluate_signal = original_evaluate_signal

    rejected = [
        item
        for item in decisions
        if item["action"] != SignalAction.ENTER.value
    ]
    accepted = [
        item
        for item in decisions
        if item["action"] == SignalAction.ENTER.value
    ]

    reason_counts = Counter(item["reason"] for item in rejected)
    strategy_reason_counts = Counter(
        (item["strategy_id"], item["reason"])
        for item in rejected
    )
    direction_reason_counts = Counter(
        (item["direction"], item["reason"])
        for item in rejected
    )
    strategy_counts = Counter(item["strategy_id"] for item in rejected)
    direction_counts = Counter(item["direction"] for item in rejected)

    active_shape_counts = Counter(
        (
            item["strategy_id"],
            item["direction"],
            tuple(
                (p["strategy_id"], p["direction"], p["symbol"])
                for p in item["active_positions"]
            ),
        )
        for item in rejected
    )

    report = {
        "sample_start": str(sample[0].timestamp),
        "sample_end": str(sample[-1].timestamp),
        "selected_events": len(result["selected_events"]),
        "runner_counts": result["counts"],
        "lifecycle_decision_count": len(decisions),
        "lifecycle_accepted": len(accepted),
        "lifecycle_rejected": len(rejected),
        "rejection_reasons": dict(reason_counts),
        "rejections_by_strategy": {
            strategy: count
            for strategy, count in sorted(strategy_counts.items())
        },
        "rejections_by_direction": dict(sorted(direction_counts.items())),
        "rejections_by_strategy_and_reason": {
            f"{strategy} | {reason}": count
            for (strategy, reason), count
            in sorted(strategy_reason_counts.items())
        },
        "rejections_by_direction_and_reason": {
            f"{direction} | {reason}": count
            for (direction, reason), count
            in sorted(direction_reason_counts.items())
        },
        "active_position_shapes": [
            {
                "strategy_id": strategy,
                "direction": direction,
                "active_positions": [
                    {
                        "strategy_id": p[0],
                        "direction": p[1],
                        "symbol": p[2],
                    }
                    for p in active
                ],
                "count": count,
            }
            for (strategy, direction, active), count
            in sorted(
                active_shape_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "decision_samples": decisions[:25],
        "notes": [
            "Exact V2 run_reference() was used.",
            "evaluate_signal was wrapped only to capture its returned action/reason.",
            "No database changes were made.",
            "No canonical KunalQuant code was changed.",
            "This audit does not alter lifecycle behavior.",
        ],
    }

    args.report.write_text(
        json.dumps(report, indent=2, default=str),
        encoding="utf-8",
    )

    print("=" * 100)
    print("KUNAL QUANT — V2 LIFECYCLE REJECTION REASON AUDIT")
    print("=" * 100)
    print(f"Events in window          : {report['selected_events']}")
    print(f"Lifecycle decisions       : {report['lifecycle_decision_count']}")
    print(f"Lifecycle accepted        : {report['lifecycle_accepted']}")
    print(f"Lifecycle rejected        : {report['lifecycle_rejected']}")
    print()

    print("REJECTION REASONS")
    for reason, count in reason_counts.most_common():
        print(f"{count:6d} | {reason}")
    print()

    print("REJECTIONS BY STRATEGY")
    for strategy, count in strategy_counts.most_common():
        print(f"{count:6d} | {strategy}")
    print()

    print("REJECTIONS BY DIRECTION")
    for direction, count in direction_counts.most_common():
        print(f"{count:6d} | {direction}")
    print()

    print("REJECTIONS BY STRATEGY + REASON")
    for (strategy, reason), count in strategy_reason_counts.most_common():
        print(f"{count:6d} | {strategy} | {reason}")
    print()

    print(f"Report: {args.report}")
    print("NO DATABASE CHANGES WERE MADE.")
    print("NO CANONICAL CODE WAS CHANGED.")


if __name__ == "__main__":
    main()
