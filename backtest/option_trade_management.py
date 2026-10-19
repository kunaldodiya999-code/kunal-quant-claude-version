"""
KUNAL QUANT — OPTION TRADE MANAGEMENT RUNNER

Applies the existing locked Option Trade Management V1 to an
already-resolved option entry.

KAMA is calculated by the existing KAMA Trend Follower module and
its values are aligned to the latest completed 3M NIFTY bar available
at each 1M option candle timestamp.

This module contains orchestration only. It does not change:
- KTMI
- Strategy A/B
- Resolver V2
- Position Lifecycle V1
- Option Trade Lifecycle V1
- KAMA calculation or exit rule
"""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_right
from typing import Sequence

from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionCandle, OptionEntry
from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradeLifecycle,
    OptionTradePosition,
    OptionTradeResult,
)
from indicators.kama_trend_follower.universal import KAMAResult


@dataclass(frozen=True)
class ManagedOptionTrade:
    entry: OptionEntry
    position: OptionTradePosition
    result: OptionTradeResult


def run_option_trade_management(
    *,
    entry: OptionEntry,
    option_candles: Sequence[OptionCandle],
    underlying_bars: Sequence[BacktestBar],
    kama_results: Sequence[KAMAResult],
    lifecycle: OptionTradeLifecycle | None = None,
) -> ManagedOptionTrade:
    """Run locked Option Trade Management V1 from one resolved entry."""

    if not underlying_bars:
        raise ValueError("underlying_bars cannot be empty")

    if len(underlying_bars) != len(kama_results):
        raise ValueError(
            "underlying_bars and kama_results must have equal length"
        )

    manager = lifecycle or OptionTradeLifecycle()

    direction = (
        OptionTradeDirection.LONG
        if entry.event.direction.value == "LONG"
        else OptionTradeDirection.SHORT
    )

    position = manager.create_position(
        strategy_id=entry.event.strategy_id.value,
        direction=direction,
        symbol=entry.contract.symbol,
        entry_price=entry.entry_price,
    )

    ordered_options = sorted(
        (
            candle
            for candle in option_candles
            if candle.timestamp > entry.entry_timestamp
        ),
        key=lambda candle: candle.timestamp,
    )

    underlying_timestamps = [
        bar.timestamp for bar in underlying_bars
    ]

    exits: list[OptionTradeExit] = []

    for candle in ordered_options:
        index = bisect_right(
            underlying_timestamps,
            candle.timestamp,
        ) - 1

        if index < 0:
            continue

        underlying = underlying_bars[index]
        kama = kama_results[index]

        candle_exits = manager.process_candle(
            position=position,
            timestamp=candle.timestamp,
            option_high=candle.high,
            option_low=candle.low,
            option_close=candle.close,
            underlying_close=underlying.close,
            kama_value=kama.kama,
        )

        exits.extend(candle_exits)

        if position.closed:
            break

    result = OptionTradeResult(
        position=position,
        exits=tuple(exits),
        total_pnl=position.gross_pnl,
        closed=position.closed,
    )

    return ManagedOptionTrade(
        entry=entry,
        position=position,
        result=result,
    )
