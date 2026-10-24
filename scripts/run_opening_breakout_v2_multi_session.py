"""Run Opening Breakout V2 across real stored NIFTY sessions."""

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

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_multi_session import run_multi_session_backtest
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--risk", type=float, default=2000.0)
    args = parser.parse_args()

    candles = load_nifty_candles(epoch_seconds(args.start), epoch_seconds(args.end))
    if len(candles) < 2:
        raise RuntimeError("not enough NIFTY candles in requested window")

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

    print("=" * 90)
    print("KUNAL QUANT — OPENING BREAKOUT V2 MULTI-SESSION REAL BACKTEST")
    print("=" * 90)
    print(f"NIFTY candles : {len(candles)}")
    print(f"Sessions      : {result.sessions}")
    print(f"Signals       : {result.signals}")
    print(f"Closed trades : {result.closed}")
    print(f"Rejected      : {result.rejected}")
    if result.rejection_reasons:
        print("Rejection reasons:")
        for reason, count in result.rejection_reasons:
            print(f"  {count:4d}  {reason}")
    print(f"Initial equity: {result.initial_capital:.2f}")
    print(f"Ending equity : {result.ending_equity:.2f}")
    print(f"Peak equity   : {result.peak_equity:.2f}")
    print(f"Max drawdown  : {result.max_drawdown:.2f} ({result.max_drawdown_pct:.2f}%)")
    print(f"Wins / Losses : {result.wins} / {result.losses}")
    print(f"Win rate      : {result.win_rate_pct:.2f}%")
    print(f"Gross P&L     : {result.gross_pnl:.2f}")
    print(f"Total costs   : {result.total_costs:.2f}")
    print(f"Net P&L       : {result.net_pnl:.2f}")
    print("-" * 90)

    for trade in result.trades:
        if trade.status == "CLOSED":
            print(
                f"[CLOSED] {trade.contract.symbol} "
                f"signal={trade.event.trigger_timestamp} "
                f"entry={trade.entry.price:.2f} "
                f"exit={trade.exit.price:.2f} "
                f"qty={trade.quantity} "
                f"pnl={trade.gross_pnl:.2f}"
            )
        else:
            print(
                f"[REJECTED] {trade.contract.symbol} "
                f"signal={trade.event.trigger_timestamp} "
                f"reason={trade.status}"
            )

    print("=" * 90)


if __name__ == "__main__":
    main()
