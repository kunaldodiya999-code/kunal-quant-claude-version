"""Kunal Quant — HFT Gap-Open Strategy V1.

Pure research logic. No broker order placement.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from config.hft_strategy import (
    GAP_THRESHOLD_POINTS, INITIAL_SL_MAX_POINTS,
    ENTRY_LIMIT_OFFSET_POINTS, CAPITAL_PER_LOT, DEFAULT_LOTS,
    TRAIL_BUFFER_POINTS, TRAIL_MIN_LOCK_POINTS,
)

Side = Literal["CALL", "PUT"]

@dataclass(frozen=True)
class GapSignal:
    side: Side
    gap_points: float

@dataclass(frozen=True)
class SetupCandle:
    open: float
    high: float
    low: float
    close: float

@dataclass(frozen=True)
class EntryDecision:
    triggered: bool
    reference_price: float | None
    limit_price: float | None
    initial_sl: float | None
    risk_points: float | None

def opening_gap(previous_close: float, current_open: float) -> float:
    """Opening gap for the configured HFT underlying.

    Current build supplies NIFTY futures previous close/open values.
    """
    return float(current_open) - float(previous_close)

def gap_signal(previous_close: float, current_open: float) -> GapSignal | None:
    gap = opening_gap(previous_close, current_open)
    if gap >= GAP_THRESHOLD_POINTS:
        return GapSignal("CALL", gap)
    if gap <= -GAP_THRESHOLD_POINTS:
        return GapSignal("PUT", gap)
    return None

def first_candle_open_equals_low(candle: SetupCandle) -> bool:
    return Decimal(str(candle.open)) == Decimal(str(candle.low))

def setup_is_valid(candle: SetupCandle) -> bool:
    return first_candle_open_equals_low(candle)

def entry_limit_price(reference_price: float) -> float:
    return float(reference_price) + ENTRY_LIMIT_OFFSET_POINTS

def calculate_initial_sl(entry_price: float, setup_low: float) -> tuple[float, float]:
    entry, low = float(entry_price), float(setup_low)
    risk_to_low = entry - low
    stop = low if risk_to_low <= INITIAL_SL_MAX_POINTS else entry - INITIAL_SL_MAX_POINTS
    return stop, entry - stop

def next_candle_breaks_high(setup_candle: SetupCandle, next_high: float) -> bool:
    return float(next_high) > float(setup_candle.high)

def evaluate_entry(
    setup_candle: SetupCandle, next_high: float, reference_price: float
) -> EntryDecision:
    if not setup_is_valid(setup_candle):
        return EntryDecision(False, None, None, None, None)
    if not next_candle_breaks_high(setup_candle, next_high):
        return EntryDecision(False, None, None, None, None)

    limit_price = entry_limit_price(reference_price)

    # A historical backtest may only fill this buy limit if the candle
    # actually traded through the requested limit.
    if float(next_high) < limit_price:
        return EntryDecision(False, reference_price, limit_price, None, None)

    stop, risk = calculate_initial_sl(limit_price, setup_candle.low)
    return EntryDecision(True, reference_price, limit_price, stop, risk)

def trailing_stop_price(
    entry_price: float,
    current_price: float,
    buffer_points: float = TRAIL_BUFFER_POINTS,
    min_lock_points: float = TRAIL_MIN_LOCK_POINTS,
) -> float | None:
    profit = float(current_price) - float(entry_price)
    if profit < float(min_lock_points):
        return None
    stop = float(current_price) - float(buffer_points)
    minimum_stop = float(entry_price) + float(min_lock_points)
    return max(stop, minimum_stop)

def capital_allocation(
    capital_per_lot: float = CAPITAL_PER_LOT, lots: int = DEFAULT_LOTS
) -> float:
    if lots < 1:
        raise ValueError("lots must be >= 1")
    if capital_per_lot <= 0:
        raise ValueError("capital_per_lot must be > 0")
    return float(capital_per_lot) * int(lots)
