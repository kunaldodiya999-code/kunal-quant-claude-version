"""Opening Breakout V2 -> real historical option integration.

Research-only orchestration layer.

It connects the V2 signal boundary to the existing Resolver V2, stored FYERS
option candles, historical fill engine, and V2 risk/SL/TP helpers.

Resolver V2 is not modified. Lot size is read separately from the canonical
instruments table because Resolver V2 intentionally exposes contract identity
rather than execution metadata.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from backtest.opening_breakout_v2_fill_engine import (
    FillResult,
    HistoricalBar,
    simulate_exit,
    simulate_limit_fill,
)
from backtest.opening_breakout_v2_signal_engine import OpeningBreakoutEvent
from config.settings import DATABASE_PATH
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import (
    Candle,
    V2Config,
    calculate_position_size,
    stop_loss_price,
    target_price,
)
from strategies.option_contract_resolver import (
    OptionContractResolver,
    ResolvedOptionContract,
)

TIMEZONE = ZoneInfo("Asia/Kolkata")
OptionCandleLoader = Callable[[int, int, int], Sequence[object]]
LotSizeLoader = Callable[[int], int]


@dataclass(frozen=True)
class ResolvedOpeningBreakoutTrade:
    event: OpeningBreakoutEvent
    contract: ResolvedOptionContract
    signal_underlying_price: float
    option_signal_price: float
    quantity: int
    lots: int
    entry: FillResult
    exit: FillResult
    stop_price: float | None
    target_price: float | None
    final_stop_price: float | None
    gross_pnl: float
    status: str


def database_lot_size(
    instrument_id: int,
    database_path: Path | str = DATABASE_PATH,
) -> int:
    """Read lot size from the canonical instruments table."""
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT lot_size FROM instruments WHERE id = ?",
            (instrument_id,),
        ).fetchone()

    if row is None or row[0] is None:
        raise LookupError(
            f"lot size missing for instrument_id={instrument_id}"
        )

    lot_size = int(row[0])
    if lot_size <= 0:
        raise ValueError(
            f"invalid lot size {lot_size} for instrument_id={instrument_id}"
        )
    return lot_size


def _entry_date(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, tz=TIMEZONE).date()


def _to_historical_bar(candle: object) -> HistoricalBar:
    return HistoricalBar(
        timestamp=int(candle.timestamp),
        open=float(candle.open),
        high=float(candle.high),
        low=float(candle.low),
        close=float(candle.close),
    )


def _find_underlying_price(
    candles: Sequence[Candle],
    timestamp: int,
) -> float:
    candidates = [c for c in candles if c.timestamp <= timestamp]
    if not candidates:
        raise LookupError(
            "no underlying candle available at signal timestamp"
        )
    return float(
        max(candidates, key=lambda c: c.timestamp).close
    )


def _find_option_signal_price(
    bars: Sequence[HistoricalBar],
    timestamp: int,
) -> float:
    candidates = [bar for bar in bars if bar.timestamp <= timestamp]
    if not candidates:
        raise LookupError(
            "no option quote available at signal timestamp"
        )
    return float(
        max(candidates, key=lambda bar: bar.timestamp).close
    )


def _setup_option_candle(
    bars: Sequence[HistoricalBar],
    setup_timestamp: int,
) -> HistoricalBar:
    """Return the latest option candle available at the V2 setup timestamp.

    The integration must not use the earliest candle in the loaded history:
    that can belong to a different session and silently change the stop level.
    Selecting only timestamps <= setup_timestamp also prevents a future option
    candle from leaking into stop construction.
    """
    candidates = [bar for bar in bars if bar.timestamp <= setup_timestamp]
    if not candidates:
        raise LookupError(
            "no option candle available at or before the setup timestamp"
        )
    return max(candidates, key=lambda bar: bar.timestamp)


def run_opening_breakout_trade(
    *,
    event: OpeningBreakoutEvent,
    underlying_candles: Sequence[Candle],
    resolver: OptionContractResolver,
    option_loader: OptionCandleLoader,
    config: V2Config,
    execution_policy: V2ExecutionPolicy,
    capital: float,
    lot_size_loader: LotSizeLoader = database_lot_size,
    force_exit_timestamp: int | None = None,
) -> ResolvedOpeningBreakoutTrade:
    """Resolve and simulate one V2 signal against stored historical option data."""
    if event.instrument not in {"CALL", "PUT"}:
        raise ValueError(
            "this bridge currently targets CALL/PUT option events"
        )

    underlying_price = _find_underlying_price(
        underlying_candles,
        event.trigger_timestamp,
    )

    contract = resolver.resolve(
        underlying_price=underlying_price,
        entry_date=_entry_date(event.trigger_timestamp),
        direction=event.direction,
    )

    raw_candles = list(
        option_loader(
            contract.instrument_id,
            event.setup_timestamp,
            force_exit_timestamp or event.trigger_timestamp + 86400,
        )
    )
    invalid_candles = []
    for candle in raw_candles:
        open_price = float(candle.open)
        high_price = float(candle.high)
        low_price = float(candle.low)
        close_price = float(candle.close)
        if high_price < max(open_price, close_price) or low_price > min(open_price, close_price):
            invalid_candles.append(
                (int(candle.timestamp), open_price, high_price, low_price, close_price)
            )

    if invalid_candles:
        timestamp, open_price, high_price, low_price, close_price = invalid_candles[0]
        return ResolvedOpeningBreakoutTrade(
            event=event,
            contract=contract,
            signal_underlying_price=underlying_price,
            option_signal_price=0.0,
            quantity=0,
            lots=0,
            entry=FillResult(False, None, None, "INVALID_DATA"),
            exit=FillResult(False, None, None, "NO_EXIT"),
            stop_price=None,
            target_price=None,
            final_stop_price=None,
            gross_pnl=0.0,
            status=(
                "INVALID_DATA"
                f"|symbol={contract.symbol}"
                f"|timestamp={timestamp}"
                f"|ohlc={open_price},{high_price},{low_price},{close_price}"
            ),
        )

    option_bars = sorted(
        (_to_historical_bar(candle) for candle in raw_candles),
        key=lambda bar: bar.timestamp,
    )
    if not option_bars:
        raise LookupError(
            f"no option candles for {contract.symbol}"
        )

    signal_price = _find_option_signal_price(
        option_bars,
        event.trigger_timestamp,
    )

    entry = simulate_limit_fill(
        option_bars,
        start_after_timestamp=event.trigger_timestamp,
        side="BUY",
        limit_price=signal_price + execution_policy.entry_buffer_points,
        timeout_seconds=execution_policy.fill_timeout_seconds,
    )

    if entry.filled:
        adverse_slippage = (
            entry.price - signal_price
            if event.direction == "LONG"
            else signal_price - entry.price
        )
        if adverse_slippage > execution_policy.max_slippage_points:
            return ResolvedOpeningBreakoutTrade(
                event,
                contract,
                underlying_price,
                signal_price,
                0,
                0,
                FillResult(False, entry.timestamp, entry.price, "SLIPPAGE_REJECTED"),
                FillResult(False, None, None, "NO_EXIT"),
                None,
                None,
                None,
                0.0,
                "SLIPPAGE_REJECTED",
            )

    if not entry.filled:
        return ResolvedOpeningBreakoutTrade(
            event,
            contract,
            underlying_price,
            signal_price,
            0,
            0,
            entry,
            FillResult(False, None, None, "NO_EXIT"),
            None,
            None,
            None,
            0.0,
            entry.reason,
        )

    setup = _setup_option_candle(option_bars, event.setup_timestamp)
    stop = stop_loss_price(
        entry.price,
        Candle(
            setup.timestamp,
            setup.open,
            setup.high,
            setup.low,
            setup.close,
        ),
        config.sl_mode,
        event.direction,
        custom_points=config.custom_sl_points,
    )
    if stop is None:
        raise ValueError(
            "historical integration requires an actual stop for sizing"
        )

    if stop <= 0:
        return ResolvedOpeningBreakoutTrade(
            event=event,
            contract=contract,
            signal_underlying_price=underlying_price,
            option_signal_price=signal_price,
            quantity=0,
            lots=0,
            entry=entry,
            exit=FillResult(False, None, None, "NO_EXIT"),
            stop_price=stop,
            target_price=None,
            final_stop_price=stop,
            gross_pnl=0.0,
            status="INVALID_STOP",
        )

    lot_size = lot_size_loader(contract.instrument_id)
    sizing = calculate_position_size(
        capital=capital,
        entry_price=entry.price,
        stop_loss_price_value=stop,
        lot_size=lot_size,
        config=config,
    )

    if sizing.quantity <= 0:
        return ResolvedOpeningBreakoutTrade(
            event,
            contract,
            underlying_price,
            signal_price,
            0,
            0,
            entry,
            FillResult(False, None, None, "NO_EXIT"),
            stop,
            None,
            stop,
            0.0,
            "REJECTED_NO_POSITION_SIZE",
        )

    target = target_price(
        entry.price,
        stop,
        config.tp_mode,
        event.direction,
        custom_points=config.custom_tp_points,
        value_target=config.tp_value_target,
        rr_multiplier=config.rr_multiplier,
        quantity=sizing.quantity,
    )

    exit_result, final_stop = simulate_exit(
        option_bars,
        entry_timestamp=entry.timestamp,
        direction=event.direction,
        quantity=sizing.quantity,
        stop_price=stop,
        target_price=target,
        policy=execution_policy,
        force_exit_timestamp=force_exit_timestamp,
        trailing_enabled=config.trailing_enabled,
        trailing_mode="RR_STEPS",
        trail_trigger_points=config.trail_trigger_points,
        trail_distance_points=config.trail_distance_points,
        trail_to_cost=config.trail_to_cost,
        trail_rr_steps=config.trail_rr_steps,
        entry_price=entry.price,
    )

    pnl = 0.0
    if exit_result.filled:
        multiplier = 1.0 if event.direction == "LONG" else -1.0
        pnl = (
            exit_result.price - entry.price
        ) * sizing.quantity * multiplier

    return ResolvedOpeningBreakoutTrade(
        event=event,
        contract=contract,
        signal_underlying_price=underlying_price,
        option_signal_price=signal_price,
        quantity=sizing.quantity,
        lots=sizing.lots,
        entry=entry,
        exit=exit_result,
        stop_price=stop,
        target_price=target,
        final_stop_price=final_stop,
        gross_pnl=pnl,
        status="CLOSED" if exit_result.filled else "OPEN",
    )


__all__ = [
    "ResolvedOpeningBreakoutTrade",
    "database_lot_size",
    "run_opening_breakout_trade",
]
