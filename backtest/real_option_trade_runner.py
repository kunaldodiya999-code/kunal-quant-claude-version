"""Real-data option trade runner.

Orchestrates existing project layers over stored FYERS data. It does not
change KTMI, Strategy A/B, Resolver V2, Position Lifecycle V1, Option
Trade Lifecycle V1, or KAMA.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionEntry, resolve_option_entries
from backtest.option_trade_lifecycle import OptionTradeLifecycle, OptionTradeResult
from indicators.kama_trend_follower.config import DEFAULT_KAMA_CONFIG
from indicators.kama_trend_follower.universal import KAMABar, calculate_kama_trend
from strategies.option_contract_resolver import OptionContractResolver
from strategies.ktmi_trigger_strategy import KTMITriggerEvent

TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class RealOptionTrade:
    entry: OptionEntry
    result: OptionTradeResult


@dataclass(frozen=True)
class RealOptionRunResult:
    trades: tuple[RealOptionTrade, ...]
    unresolved_events: int
    no_entry_candle_events: int
    open_trades: int


def calculate_nifty_kama(
    bars: Sequence[BacktestBar],
):
    """Calculate KAMA using the existing project implementation."""
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


def load_trade_candles(
    loader: FyersOptionCandleLoader,
    entry: OptionEntry,
    *,
    end_timestamp: int,
):
    """Load real option candles from entry through the requested end."""
    return loader.load(
        entry.contract.instrument_id,
        entry.entry_timestamp,
        end_timestamp,
    )


def run_real_option_trades(
    *,
    bars: Sequence[BacktestBar],
    events: Sequence[KTMITriggerEvent],
    resolver: OptionContractResolver,
    option_loader: FyersOptionCandleLoader,
    end_timestamp: int | None = None,
) -> RealOptionRunResult:
    """Run resolved events against real stored FYERS option candles.

    Events are processed chronologically. A position is removed from the
    lifecycle boundary only after its V1 trade has actually closed, allowing
    the existing re-entry rules to operate on completed trades.
    """

    if not bars:
        raise ValueError("bars cannot be empty")

    ordered_events = sorted(events, key=lambda event: (event.index, event.timestamp))
    kama_results = calculate_nifty_kama(bars)

    active_positions = []
    trades: list[RealOptionTrade] = []
    unresolved_events = 0
    no_entry_candle_events = 0

    final_timestamp = (
        end_timestamp
        if end_timestamp is not None
        else bars[-1].timestamp
    )

    for event in ordered_events:
        index = event.index
        if index < 0 or index >= len(bars):
            raise ValueError(f"event index {index} is outside supplied bars")

        try:
            entry_candidates = resolve_option_entries(
                bars=bars,
                events=[event],
                resolver=resolver,
                option_candle_loader=option_loader,
                active_positions=active_positions,
            )
        except LookupError:
            # Resolver V2 is intentionally strict. A missing exact contract
            # is a historical-data coverage miss, not a fatal backtest error.
            unresolved_events += 1
            continue

        if not entry_candidates:
            # No accepted entry means either lifecycle rejection or no
            # strictly-later option candle. Keep this as a separate metric.
            no_entry_candle_events += 1
            continue

        entry = entry_candidates[0]
        candles = load_trade_candles(
            option_loader,
            entry,
            end_timestamp=final_timestamp,
        )

        lifecycle = OptionTradeLifecycle()

        from backtest.option_trade_management import run_option_trade_management

        managed = run_option_trade_management(
            entry=entry,
            option_candles=candles,
            underlying_bars=bars,
            kama_results=kama_results,
            lifecycle=lifecycle,
        )

        trades.append(
            RealOptionTrade(
                entry=entry,
                result=managed.result,
            )
        )

        if managed.result.closed:
            active_positions[:] = [
                position
                for position in active_positions
                if not (
                    position.strategy_id == entry.event.strategy_id.value
                    and position.direction == entry.event.direction.value
                    and position.symbol == entry.contract.symbol
                )
            ]

    open_trades = sum(
        1 for trade in trades if not trade.result.closed
    )

    return RealOptionRunResult(
        trades=tuple(trades),
        unresolved_events=unresolved_events,
        no_entry_candle_events=no_entry_candle_events,
        open_trades=open_trades,
    )
