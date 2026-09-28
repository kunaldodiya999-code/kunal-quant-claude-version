"""
Kunal Quant - Resilient Real Option Sample (PROPOSAL)

Runs the existing KTMI -> Resolver -> option lifecycle pipeline while treating
an allocation-rejected signal as a normal non-executable event.

Canonical KunalQuant is not modified.

The only special handling is for the existing locked lifecycle exception:
    Allocation cannot purchase one complete lot

Such events are skipped and counted. The temporary ActivePosition created by
the entry bridge is removed because no real position was created.

All other exceptions remain fatal.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from typing import Sequence

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.option_entry_bridge import (
    OptionEntry,
    resolve_option_entries,
)
from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionTradeLifecycle,
    OptionTradeResult,
)
from backtest.option_trade_management import ManagedOptionTrade
from backtest.position_lifecycle import ActivePosition
from indicators.kama_trend_follower.config import DEFAULT_KAMA_CONFIG
from indicators.kama_trend_follower.universal import KAMABar, calculate_kama_trend
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver


ALLOCATION_ERROR = "Allocation cannot purchase one complete lot"


@dataclass(frozen=True)
class ResilientRealOptionRunResult:
    trades: tuple[ManagedOptionTrade, ...]
    unresolved_events: int
    no_entry_candle_events: int
    allocation_rejected_events: int
    open_trades: int


def calculate_nifty_kama(bars: Sequence[BacktestBar]):
    kama_bars = [
        KAMABar(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]
    return calculate_kama_trend(
        bars=kama_bars,
        config=DEFAULT_KAMA_CONFIG,
    )


def load_trade_candles(loader, entry: OptionEntry, end_timestamp: int):
    return loader.load(
        entry.contract.instrument_id,
        entry.entry_timestamp,
        end_timestamp,
    )


def remove_placeholder_position(
    active_positions: list[ActivePosition],
    entry: OptionEntry,
) -> None:
    target = (
        entry.event.strategy_id.value,
        entry.event.direction.value,
        entry.contract.symbol,
    )
    for index in range(len(active_positions) - 1, -1, -1):
        position = active_positions[index]
        if (
            position.strategy_id,
            position.direction,
            position.symbol,
        ) == target:
            active_positions.pop(index)
            return


def run_resilient(
    *,
    bars: Sequence[BacktestBar],
    events,
    resolver,
    option_loader,
    end_timestamp: int,
) -> ResilientRealOptionRunResult:
    ordered_events = sorted(events, key=lambda e: (e.index, e.timestamp))
    kama_results = calculate_nifty_kama(bars)

    active_positions: list[ActivePosition] = []
    trades: list[ManagedOptionTrade] = []
    unresolved_events = 0
    no_entry_candle_events = 0
    allocation_rejected_events = 0

    for event in ordered_events:
        try:
            entry_candidates = resolve_option_entries(
                bars=bars,
                events=[event],
                resolver=resolver,
                option_candle_loader=option_loader,
                active_positions=active_positions,
            )
        except LookupError:
            unresolved_events += 1
            continue

        if not entry_candidates:
            no_entry_candle_events += 1
            continue

        entry = entry_candidates[0]
        candles = load_trade_candles(
            option_loader,
            entry,
            end_timestamp,
        )

        lifecycle = OptionTradeLifecycle()

        from backtest.option_trade_management import run_option_trade_management

        try:
            managed = run_option_trade_management(
                entry=entry,
                option_candles=candles,
                underlying_bars=bars,
                kama_results=kama_results,
                lifecycle=lifecycle,
            )
        except ValueError as exc:
            if str(exc) != ALLOCATION_ERROR:
                raise

            allocation_rejected_events += 1
            remove_placeholder_position(active_positions, entry)
            continue

        trades.append(managed)

        if managed.result.closed:
            active_positions[:] = [
                position
                for position in active_positions
                if not (
                    position.strategy_id
                    == entry.event.strategy_id.value
                    and position.direction
                    == entry.event.direction.value
                    and position.symbol
                    == entry.contract.symbol
                )
            ]

    open_trades = sum(1 for trade in trades if not trade.result.closed)

    return ResilientRealOptionRunResult(
        trades=tuple(trades),
        unresolved_events=unresolved_events,
        no_entry_candle_events=no_entry_candle_events,
        allocation_rejected_events=allocation_rejected_events,
        open_trades=open_trades,
    )


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )

    loader = FyersOptionCandleLoader(DATABASE_PATH)
    result = run_resilient(
        bars=bars,
        events=pipeline.events,
        resolver=OptionContractResolver(),
        option_loader=loader,
        end_timestamp=bars[-1].timestamp + 3600,
    )

    total_pnl = sum(
        trade.result.total_pnl
        for trade in result.trades
    )

    print("=" * 100)
    print("KUNAL QUANT — RESILIENT REAL 3M NIFTY → OPTION SAMPLE")
    print("=" * 100)
    print("PROPOSAL ONLY — canonical KunalQuant unchanged")
    print()
    print(f"3M bars                    : {len(bars):,}")
    print(f"KTMI events                : {len(pipeline.events):,}")
    print(f"Completed option trades   : {sum(t.result.closed for t in result.trades):,}")
    print(f"Open option trades         : {result.open_trades:,}")
    print(f"Unresolved contracts       : {result.unresolved_events:,}")
    print(f"No entry candle            : {result.no_entry_candle_events:,}")
    print(f"Allocation-rejected events: {result.allocation_rejected_events:,}")
    print(f"Gross option P&L           : {total_pnl:,.2f}")
    print()
    print("Allocation rejection is counted as a skipped/non-executable signal.")
    print("All other exceptions remain fatal.")


if __name__ == "__main__":
    main()
