"""Trade-mechanics audit for the Opening Breakout V2 historical runner.

Reporting-only. It does not alter strategy, execution, sizing, or cost rules.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from pathlib import Path
import sqlite3
import sys
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_multi_session import run_multi_session_backtest
from backtest.broker_cost_model import calculate_options_trade_costs, fyers_options_profile
from config.settings import DATABASE_PATH
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=IST).timestamp())


def load_nifty_candles(start_ts: int, end_ts: int) -> list[Candle]:
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker = 'FYERS'
              AND i.symbol = 'NSE:NIFTY50-INDEX'
              AND c.resolution = '1'
              AND c.timestamp BETWEEN ? AND ?
            ORDER BY c.timestamp
            """,
            (start_ts, end_ts),
        ).fetchall()
    return [Candle(int(ts), float(o), float(h), float(l), float(c)) for ts, o, h, l, c in rows]


def empty_indicator_provider(timestamp: int, candle: Candle) -> IndicatorSnapshot:
    return IndicatorSnapshot()


def summarize_trades(trades):
    closed = [t for t in trades if t.status == "CLOSED"]
    exit_reasons = Counter(t.exit.reason for t in closed)
    pnl_buckets = Counter()
    for trade in closed:
        if trade.gross_pnl > 0:
            pnl_buckets["WIN"] += 1
        elif trade.gross_pnl < 0:
            pnl_buckets["LOSS"] += 1
        else:
            pnl_buckets["FLAT"] += 1

    return {
        "closed": len(closed),
        "exit_reasons": dict(sorted(exit_reasons.items())),
        "pnl_buckets": dict(sorted(pnl_buckets.items())),
        "quantities": Counter(t.quantity for t in closed),
        "lots": Counter(t.lots for t in closed),
        "gross_pnl": sum(t.gross_pnl for t in closed),
        "total_costs": sum(
            calculate_options_trade_costs(
                entry_price=t.entry.price,
                exit_price=t.exit.price,
                quantity=t.quantity,
                profile=fyers_options_profile(
                    datetime.fromtimestamp(
                        t.event.trigger_timestamp, tz=IST
                    ).date()
                ),
                gross_pnl=t.gross_pnl,
            ).total_cost
            for t in closed
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--risk", type=float, default=2000.0)
    args = parser.parse_args()

    candles = load_nifty_candles(
        epoch_seconds(args.start),
        epoch_seconds(args.end),
    )
    config = V2Config(
        trade_instrument="CALL",
        market_bias="NEUTRAL",
        selected_timeframes=("1M",),
        selected_triggers=("CANDLE_HIGH",),
        filter_open_high=False,
        filter_open_low=False,
        custom_sl_points=20.0,
        tp_mode="RR_RATIO",
        rr_multiplier=2.0,
        risk_per_trade_value=args.risk,
        capital_allocation_percent=100.0,
    )
    result = run_multi_session_backtest(
        candles=candles,
        config=config,
        resolver=OptionContractResolver(DATABASE_PATH),
        option_loader=FyersOptionCandleLoader(DATABASE_PATH),
        execution_policy=V2ExecutionPolicy(
            entry_buffer_points=1.0,
            max_slippage_points=2.0,
            fill_timeout_seconds=60,
        ),
        capital=args.capital,
        indicator_provider=empty_indicator_provider,
    )

    summary = summarize_trades(result.trades)
    print("=" * 90)
    print("KUNAL QUANT — OPENING BREAKOUT V2 TRADE MECHANICS AUDIT")
    print("=" * 90)
    print(f"Signals        : {result.signals}")
    print(f"Closed trades  : {summary['closed']}")
    print(f"Gross P&L      : {summary['gross_pnl']:.2f}")
    print(f"Total costs    : {summary['total_costs']:.2f}")
    print(f"Net P&L        : {summary['gross_pnl'] - summary['total_costs']:.2f}")
    print()
    print("EXIT REASONS")
    for reason, count in summary["exit_reasons"].items():
        print(f"  {count:4d}  {reason}")
    print()
    print("P&L CLASS")
    for kind, count in summary["pnl_buckets"].items():
        print(f"  {count:4d}  {kind}")
    print()
    print("QUANTITY DISTRIBUTION")
    for quantity, count in sorted(summary["quantities"].items()):
        print(f"  qty={quantity:4d}  trades={count:4d}")
    print()
    print("LOT DISTRIBUTION")
    for lots, count in sorted(summary["lots"].items()):
        print(f"  lots={lots:3d}  trades={count:4d}")
    print()
    print("TRADE-LEVEL MECHANICS")
    print(
        "  columns: signal_ts, symbol, qty, entry, stop, target, exit, "
        "exit_reason, gross_pnl, actual_R"
    )
    for trade in result.trades:
        if trade.status != "CLOSED":
            continue
        risk = (
            abs(trade.entry.price - trade.stop_price)
            if trade.stop_price is not None
            else 0.0
        )
        actual_r = (
            trade.gross_pnl / (risk * trade.quantity)
            if risk > 0 and trade.quantity > 0
            else 0.0
        )
        print(
            f"  {trade.event.trigger_timestamp} "
            f"{trade.contract.symbol} "
            f"qty={trade.quantity} "
            f"entry={trade.entry.price:.2f} "
            f"stop={trade.stop_price:.2f} "
            f"target={(trade.target_price if trade.target_price is not None else 0.0):.2f} "
            f"exit={trade.exit.price:.2f} "
            f"exit_reason={trade.exit.reason} "
            f"gross={trade.gross_pnl:.2f} "
            f"actual_R={actual_r:.3f}"
        )


if __name__ == "__main__":
    main()
