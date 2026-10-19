"""Bounded real-data KTMI -> option trade sample.

Uses the validated derived 3M NIFTY database, complete bars only, then
runs the existing KTMI Strategy A/B -> Resolver V2 -> real FYERS option
candles -> Option Trade Lifecycle V1 chain.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.models import BacktestBar
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.real_option_trade_runner import run_real_option_trades
from config.settings import DATABASE_PATH, PROCESSED_DATA_DIR
from strategies.option_contract_resolver import OptionContractResolver
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from indicators.ktmi.config import KTMIConfig, MomentumConfig

DERIVED_DB = PROCESSED_DATA_DIR / "nifty_derived.db"
SYMBOL = "NSE:NIFTY50-INDEX"
SOURCE = "KQ_DERIVED_FROM_FYERS_1M"
SAMPLE_DAYS = 20


def load_complete_3m_bars(limit_days: int = SAMPLE_DAYS) -> list[BacktestBar]:
    with sqlite3.connect(DERIVED_DB) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume, open_interest
            FROM derived_candles
            WHERE symbol = ?
              AND resolution = '3'
              AND source = ?
              AND complete = 1
            ORDER BY timestamp
            """,
            (SYMBOL, SOURCE),
        ).fetchall()

    bars = [
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=int(row[5] or 0),
            open_interest=None if row[6] is None else int(row[6]),
        )
        for row in rows
    ]

    if not bars:
        raise RuntimeError("No complete 3M derived bars found.")

    selected_dates: list[int] = []
    selected = []
    for bar in bars:
        day = bar.timestamp // 86400
        if day not in selected_dates:
            selected_dates.append(day)
    keep_days = set(selected_dates[-limit_days:])
    for bar in bars:
        if bar.timestamp // 86400 in keep_days:
            selected.append(bar)
    return selected


def build_ktmi_config() -> KTMIConfig:
    return KTMIConfig(
        momentum=MomentumConfig("Close", 5, 9, "EMA", True, "TRIX"),
        long_momentum=MomentumConfig("Close", 5, 9, "EMA", True, "TRIX"),
        short_momentum=MomentumConfig("Low", 5, 9, "EMA", True, "TRIX"),
        momentum_buy_trigger=None,
        momentum_sell_trigger=None,
        long_buy_trigger=None,
        long_sell_trigger=None,
        short_buy_trigger=None,
        short_sell_trigger=None,
    )


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )

    option_loader = FyersOptionCandleLoader(DATABASE_PATH)
    result = run_real_option_trades(
        bars=bars,
        events=pipeline.events,
        resolver=OptionContractResolver(),
        option_loader=option_loader,
        end_timestamp=bars[-1].timestamp + 3600,
    )

    print("=" * 100)
    print("KUNAL QUANT — REAL 3M NIFTY → OPTION TRADE SAMPLE")
    print("=" * 100)
    print(f"3M bars                 : {len(bars):,}")
    print(f"KTMI events             : {len(pipeline.events):,}")
    print(f"Completed option trades : {sum(t.result.closed for t in result.trades):,}")
    print(f"Open option trades      : {result.open_trades:,}")
    print(f"Unresolved contracts    : {result.unresolved_events:,}")
    print(f"No entry candle         : {result.no_entry_candle_events:,}")

    total_pnl = sum(t.result.total_pnl for t in result.trades)
    print(f"Gross option P&L        : {total_pnl:,.2f}")
    print()

    for number, trade in enumerate(result.trades[:20], 1):
        print(
            f"{number:02d} | "
            f"{trade.entry.contract.symbol} | "
            f"{trade.entry.event.strategy_id.value} | "
            f"{trade.entry.event.direction.value} | "
            f"entry={trade.entry.entry_price:.2f} | "
            f"signal={trade.entry.signal_timestamp} | "
            f"entry_ts={trade.entry.entry_timestamp} | "
            f"closed={trade.result.closed} | "
            f"pnl={trade.result.total_pnl:.2f}"
        )


if __name__ == "__main__":
    main()
