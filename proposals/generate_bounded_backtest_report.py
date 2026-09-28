"""
Kunal Quant - Bounded Real Option Backtest Report (PROPOSAL)

Re-runs the current resilient 2,500-bar real-data sample and produces a
read-only performance report over CLOSED trades.

It preserves the proposal runner's behavior:
- 300 KTMI events
- strict resolver
- 1M option-entry bridge
- locked Option Trade Lifecycle V1
- allocation rejection as non-executable
- no changes to canonical KunalQuant

Performance metrics are calculated from closed trades only:
- total/winning/losing trades
- win rate
- gross profit / gross loss
- profit factor
- average / median trade P&L
- max drawdown from sequential closed-trade P&L
- largest win / largest loss
- exit reason counts and P&L
- daily P&L
- allocation-rejected events
- open trades

Open positions are reported separately and excluded from realized metrics.
No charges are invented because the current option lifecycle result is gross.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from run_real_option_sample_resilient import run_resilient
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")


def local_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).date().isoformat()


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def build_report():
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    result = run_resilient(
        bars=bars,
        events=pipeline.events,
        resolver=OptionContractResolver(),
        option_loader=FyersOptionCandleLoader(DATABASE_PATH),
        end_timestamp=bars[-1].timestamp + 3600,
    )

    closed = [trade for trade in result.trades if trade.result.closed]
    open_trades = [trade for trade in result.trades if not trade.result.closed]
    pnls = [float(trade.result.total_pnl) for trade in closed]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else None
    )

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

    exit_reason_counts = Counter()
    exit_reason_pnl = defaultdict(float)

    daily_pnl = defaultdict(float)

    for trade in closed:
        total_pnl = float(trade.result.total_pnl)
        exit_reason_counts["TOTAL_TRADE"] += 1
        daily_pnl[local_date(trade.entry.entry_timestamp)] += total_pnl

        for exit_event in trade.result.exits:
            reason = exit_event.reason.value
            exit_reason_counts[reason] += 1
            exit_reason_pnl[reason] += float(exit_event.pnl)

    report = {
        "sample": {
            "bars_3m": len(bars),
            "ktmi_events": len(pipeline.events),
            "sample_start": local_date(bars[0].timestamp),
            "sample_end": local_date(bars[-1].timestamp),
        },
        "event_accounting": {
            "completed_trades": len(closed),
            "open_trades": len(open_trades),
            "allocation_rejected_events": result.allocation_rejected_events,
            "unresolved_contracts": result.unresolved_events,
            "no_entry_candle_events": result.no_entry_candle_events,
            "accounted_events": (
                len(closed)
                + len(open_trades)
                + result.allocation_rejected_events
                + result.unresolved_events
                + result.no_entry_candle_events
            ),
        },
        "closed_trade_performance": {
            "closed_trades": len(closed),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "breakeven_trades": sum(1 for p in pnls if p == 0),
            "win_rate_pct": (
                (len(wins) / len(closed) * 100.0)
                if closed else None
            ),
            "gross_profit": gross_profit,
            "gross_loss": -gross_loss,
            "net_gross_pnl": sum(pnls),
            "profit_factor": profit_factor,
            "average_trade_pnl": statistics.mean(pnls) if pnls else None,
            "median_trade_pnl": statistics.median(pnls) if pnls else None,
            "largest_win": max(pnls) if pnls else None,
            "largest_loss": min(pnls) if pnls else None,
            "max_drawdown": max_drawdown,
            "max_drawdown_after_trade": max_drawdown_after_trade,
        },
        "exit_reasons": {
            "counts": dict(exit_reason_counts),
            "pnl_by_reason": dict(exit_reason_pnl),
        },
        "daily_pnl": dict(sorted(daily_pnl.items())),
        "open_trade_symbols": [
            trade.entry.contract.symbol for trade in open_trades
        ],
    }

    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    report = build_report()

    print("=" * 100)
    print("KUNAL QUANT - BOUNDED REAL OPTION BACKTEST REPORT")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    s = report["sample"]
    a = report["event_accounting"]
    p = report["closed_trade_performance"]

    print(
        f"Sample                   : {s['sample_start']} -> {s['sample_end']}"
    )
    print(f"3M bars                   : {s['bars_3m']:,}")
    print(f"KTMI events               : {s['ktmi_events']:,}")
    print()
    print("EVENT ACCOUNTING")
    print(f"Completed trades          : {a['completed_trades']:,}")
    print(f"Open trades               : {a['open_trades']:,}")
    print(f"Allocation rejected       : {a['allocation_rejected_events']:,}")
    print(f"Unresolved contracts      : {a['unresolved_contracts']:,}")
    print(f"No entry candle           : {a['no_entry_candle_events']:,}")
    print(f"Accounted events          : {a['accounted_events']:,}")
    print()
    print("CLOSED-TRADE PERFORMANCE")
    print(f"Closed trades             : {p['closed_trades']:,}")
    print(f"Winners                   : {p['winning_trades']:,}")
    print(f"Losers                    : {p['losing_trades']:,}")
    print(f"Win rate                  : {p['win_rate_pct']:.2f}%")
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
    for reason, count in sorted(
        report["exit_reasons"]["counts"].items()
    ):
        if reason == "TOTAL_TRADE":
            continue
        pnl = report["exit_reasons"]["pnl_by_reason"].get(reason, 0.0)
        print(f"{reason:20s} | exits={count:4d} | pnl={fmt(pnl)}")

    print()
    print("OPEN TRADES ARE EXCLUDED FROM CLOSED-TRADE PERFORMANCE METRICS.")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print()
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
