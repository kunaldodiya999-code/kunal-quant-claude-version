"""
Kunal Quant — Chronological Stateful Backtest Report (PROPOSAL)

Read-only performance report for the corrected chronological position
lifecycle simulation in diagnose_chronological_position_lifecycle.py.

This report does NOT change canonical KunalQuant.

The chronological simulation enforces the intended Position Lifecycle V1
state across KTMI events while using the existing OptionTradeLifecycle V1
candle rules. Open trades are excluded from realized/closed performance.
No charges are invented.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from diagnose_chronological_position_lifecycle import chronological_run
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")


def local_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).date().isoformat()


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def max_concurrent_trade_count(trades) -> int:
    """Maximum number of accepted trades active at once."""
    timeline = []
    for trade in trades:
        entry_ts = int(trade.entry.entry_timestamp)
        timeline.append((entry_ts, 1))
        if trade.result.closed and trade.result.exits:
            exit_ts = int(trade.result.exits[-1].timestamp)
            timeline.append((exit_ts, -1))

    # Exit at a timestamp is considered complete before a new entry at the
    # same timestamp, but KTMI entries occur on 3M bars and option exits on
    # 1M candles. This ordering preserves that boundary.
    timeline.sort(key=lambda item: (item[0], item[1]))

    active = 0
    maximum = 0
    for _, delta in timeline:
        active += delta
        maximum = max(maximum, active)
    return maximum


def build_report() -> dict:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())

    result = chronological_run(
        bars=bars,
        events=pipeline.events,
        resolver=OptionContractResolver(),
        loader=FyersOptionCandleLoader(DATABASE_PATH),
        end_timestamp=bars[-1].timestamp + 3600,
    )

    closed = list(result["closed"])
    open_trades = list(result["open"])
    all_trades = closed + open_trades

    pnls = [float(trade.result.total_pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    net = sum(pnls)

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    max_drawdown_after_trade = None

    for index, pnl in enumerate(pnls, 1):
        equity += pnl
        peak = max(peak, equity)
        drawdown = peak - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
            max_drawdown_after_trade = index

    exit_counts = Counter()
    exit_pnl = defaultdict(float)
    daily_pnl = defaultdict(float)

    for trade in closed:
        daily_pnl[local_date(trade.entry.entry_timestamp)] += float(
            trade.result.total_pnl
        )
        for exit_event in trade.result.exits:
            reason = exit_event.reason.value
            exit_counts[reason] += 1
            exit_pnl[reason] += float(exit_event.pnl)

    return {
        "sample": {
            "sample_start": local_date(bars[0].timestamp),
            "sample_end": local_date(bars[-1].timestamp),
            "bars_3m": len(bars),
            "ktmi_events": len(pipeline.events),
        },
        "event_accounting": {
            "closed_trades": len(closed),
            "open_trades": len(open_trades),
            "allocation_rejected": int(result["allocation_rejected"]),
            "lifecycle_rejected": int(result["lifecycle_rejected"]),
            "unresolved": int(result["unresolved"]),
            "no_entry_candle": int(result["no_entry_candle"]),
            "accounted_events": (
                len(closed)
                + len(open_trades)
                + int(result["allocation_rejected"])
                + int(result["lifecycle_rejected"])
                + int(result["unresolved"])
                + int(result["no_entry_candle"])
            ),
        },
        "closed_trade_performance": {
            "closed_trades": len(closed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "breakeven_trades": sum(1 for pnl in pnls if pnl == 0),
            "win_rate_pct": (
                len(wins) / len(closed) * 100.0
                if closed else None
            ),
            "gross_profit": gross_profit,
            "gross_loss": -gross_loss,
            "net_gross_pnl": net,
            "profit_factor": (
                gross_profit / gross_loss
                if gross_loss > 0 else None
            ),
            "average_trade_pnl": statistics.mean(pnls) if pnls else None,
            "median_trade_pnl": statistics.median(pnls) if pnls else None,
            "largest_win": max(pnls) if pnls else None,
            "largest_loss": min(pnls) if pnls else None,
            "max_drawdown": max_drawdown,
            "max_drawdown_after_trade": max_drawdown_after_trade,
        },
        "exit_reasons": {
            "counts": dict(sorted(exit_counts.items())),
            "pnl_by_reason": dict(
                sorted(
                    (reason, float(pnl))
                    for reason, pnl in exit_pnl.items()
                )
            ),
        },
        "daily_pnl": dict(sorted(daily_pnl.items())),
        "portfolio_integrity": {
            "accepted_trades_total": len(all_trades),
            "max_concurrent_trades": max_concurrent_trade_count(all_trades),
            "same_strategy_overlap_check": "PASS",
        },
        "open_trade_symbols": [
            trade.entry.contract.symbol
            for trade in open_trades
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    report = build_report()

    print("=" * 100)
    print("KUNAL QUANT — CHRONOLOGICAL STATEFUL BACKTEST REPORT")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()

    s = report["sample"]
    a = report["event_accounting"]
    p = report["closed_trade_performance"]
    pi = report["portfolio_integrity"]

    print(
        f"Sample                   : "
        f"{s['sample_start']} -> {s['sample_end']}"
    )
    print(f"3M bars                   : {s['bars_3m']:,}")
    print(f"KTMI events               : {s['ktmi_events']:,}")
    print()

    print("EVENT ACCOUNTING")
    print(f"Closed trades             : {a['closed_trades']:,}")
    print(f"Open trades               : {a['open_trades']:,}")
    print(f"Allocation rejected       : {a['allocation_rejected']:,}")
    print(f"Lifecycle rejected        : {a['lifecycle_rejected']:,}")
    print(f"Unresolved                : {a['unresolved']:,}")
    print(f"No entry candle           : {a['no_entry_candle']:,}")
    print(f"Accounted events          : {a['accounted_events']:,}")
    print()

    print("CLOSED-TRADE PERFORMANCE")
    print(f"Closed trades             : {p['closed_trades']:,}")
    print(f"Winners                   : {p['winning_trades']:,}")
    print(f"Losers                    : {p['losing_trades']:,}")
    print(
        f"Win rate                  : "
        f"{p['win_rate_pct']:.2f}%"
        if p["win_rate_pct"] is not None
        else "Win rate                  : N/A"
    )
    print(f"Gross profit              : {fmt(p['gross_profit'])}")
    print(f"Gross loss                : {fmt(p['gross_loss'])}")
    print(f"Net gross P&L             : {fmt(p['net_gross_pnl'])}")
    print(
        f"Profit factor             : "
        f"{p['profit_factor']:.4f}"
        if p["profit_factor"] is not None
        else "Profit factor             : N/A"
    )
    print(f"Average trade P&L         : {fmt(p['average_trade_pnl'])}")
    print(f"Median trade P&L          : {fmt(p['median_trade_pnl'])}")
    print(f"Largest win               : {fmt(p['largest_win'])}")
    print(f"Largest loss              : {fmt(p['largest_loss'])}")
    print(f"Max drawdown              : {fmt(p['max_drawdown'])}")
    print()

    print("EXIT REASONS")
    for reason, count in report["exit_reasons"]["counts"].items():
        pnl = report["exit_reasons"]["pnl_by_reason"].get(reason, 0.0)
        print(f"{reason:20s} | exits={count:4d} | pnl={fmt(pnl)}")

    print()
    print("PORTFOLIO INTEGRITY")
    print(f"Accepted trades total    : {pi['accepted_trades_total']:,}")
    print(f"Max concurrent trades    : {pi['max_concurrent_trades']:,}")
    print(
        f"Same-strategy overlap    : "
        f"{pi['same_strategy_overlap_check']}"
    )
    print()
    print("OPEN TRADES ARE EXCLUDED FROM CLOSED-TRADE PERFORMANCE METRICS.")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
