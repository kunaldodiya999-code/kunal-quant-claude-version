"""Run a small real-data Opening Breakout V2 historical sample.

Research-only. This script deliberately runs a bounded date window and does
not write backtest trades to the database. It uses the existing stored NIFTY
1-minute candles and stored FYERS option candles, and leaves Resolver V2 and
lifecycle modules untouched.
"""

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
from backtest.opening_breakout_v2_option_integration import run_opening_breakout_trade
from backtest.opening_breakout_v2_signal_engine import SignalSeries, scan_series
from config.settings import DATABASE_PATH
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")


def epoch_seconds(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=IST).timestamp())


def load_nifty_candles(database_path: Path, start_ts: int, end_ts: int) -> list[Candle]:
    with sqlite3.connect(database_path) as connection:
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

    return [
        Candle(int(ts), float(op), float(hi), float(lo), float(cl))
        for ts, op, hi, lo, cl in rows
    ]


def empty_indicator_provider(timestamp: int, candle: Candle) -> IndicatorSnapshot:
    """No optional indicator confirmations are enabled in this sample."""
    return IndicatorSnapshot()


def build_option_event_series(candles: list[Candle], *, option_type: str) -> SignalSeries:
    return SignalSeries(
        symbol="NIFTY-V2-CANDIDATE",
        option_type=option_type,
        strike=0,
        lot_size=1,
        candles=candles,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--capital", type=float, default=100000.0)
    parser.add_argument("--risk", type=float, default=2000.0)
    args = parser.parse_args()

    start_ts = epoch_seconds(args.start)
    end_ts = epoch_seconds(args.end)

    underlying = load_nifty_candles(DATABASE_PATH, start_ts, end_ts)
    if len(underlying) < 2:
        raise RuntimeError("not enough NIFTY candles in requested window")

    setup = underlying[0]

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

    alerts, signals = scan_series(
        build_option_event_series(underlying, option_type="CE"),
        config=config,
        indicator_provider=empty_indicator_provider,
    )

    resolver = OptionContractResolver(database_path=DATABASE_PATH)
    loader = FyersOptionCandleLoader(DATABASE_PATH)

    print("=" * 90)
    print("KUNAL QUANT — OPENING BREAKOUT V2 REAL HISTORICAL SAMPLE")
    print("=" * 90)
    print(f"NIFTY candles : {len(underlying)}")
    print(
        f"Setup candle  : {setup.timestamp} "
        f"O={setup.open:.2f} H={setup.high:.2f} "
        f"L={setup.low:.2f} C={setup.close:.2f}"
    )
    print(f"Opening alerts: {len(alerts)}")
    print(f"Signals       : {len(signals)}")

    for event in signals[:10]:
        print(
            f"[SIGNAL] ts={event.trigger_timestamp} "
            f"direction={event.direction} "
            f"breakout={event.breakout_price:.2f}"
        )
    if len(signals) > 10:
        print(f"[SIGNAL] ... {len(signals) - 10} additional signals")

    closed = 0
    rejected = 0
    total_pnl = 0.0

    for event in signals:
        try:
            trade = run_opening_breakout_trade(
                event=event,
                underlying_candles=underlying,
                resolver=resolver,
                option_loader=loader,
                config=config,
                execution_policy=V2ExecutionPolicy(
                    entry_buffer_points=1.0,
                    max_slippage_points=2.0,
                    # Historical data is 1-minute OHLC. The first observable
                    # post-signal bar is therefore 60 seconds later.
                    fill_timeout_seconds=60,
                ),
                capital=args.capital,
                force_exit_timestamp=(
                    datetime.fromtimestamp(event.trigger_timestamp, tz=IST)
                    .replace(hour=15, minute=15, second=0, microsecond=0)
                    .timestamp()
                ),
            )
        except Exception as exc:
            rejected += 1
            print(f"[REJECTED] {event.trigger_timestamp} {type(exc).__name__}: {exc}")
            continue

        if trade.status == "CLOSED":
            closed += 1
            total_pnl += trade.gross_pnl
            print(
                f"[CLOSED] {trade.contract.symbol} "
                f"entry={trade.entry.price:.2f} "
                f"exit={trade.exit.price:.2f} "
                f"qty={trade.quantity} "
                f"pnl={trade.gross_pnl:.2f}"
            )
        else:
            rejected += 1
            print(
                f"[REJECTED] status={trade.status} "
                f"contract={trade.contract.symbol} "
                f"option_signal={trade.option_signal_price:.2f} "
                f"entry_limit={trade.option_signal_price + 1.0:.2f} "
                f"entry_reason={trade.entry.reason} "
                f"entry_ts={trade.entry.timestamp} "
                f"entry_price={trade.entry.price} "
                f"stop={trade.stop_price} "
                f"target={trade.target_price}"
            )
            if trade.entry.reason == "FILL_TIMEOUT":
                print(
                    "[ENTRY_DIAGNOSTIC] timeout=60s; "
                    "signal bar is excluded; "
                    "next option bars must trade at/below entry_limit for BUY fill"
                )

    print("-" * 90)
    print(f"Closed trades : {closed}")
    print(f"Rejected      : {rejected}")
    print(f"Gross P&L     : {total_pnl:.2f}")
    print("=" * 90)


if __name__ == "__main__":
    main()
