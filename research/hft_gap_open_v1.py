"""Kunal Quant — HFT Gap-Open Strategy V1.

Pure research logic. No broker order placement. Disabled by default.

Rules (owner's requirements brief, 24 Oct 2026; every number is in ``HftGapOpenConfig``):
* Opening gap of the configured underlying (NIFTY futures in the current research build):
  gap >= +50 points -> CALL setup; gap <= -50 points -> PUT setup; otherwise no signal.
* CALL: the first 10-second candle has Open = Low; the next candle breaks its HIGH.
  PUT (mirror, owner decision 2026-10-25): Open = High; the next candle breaks its LOW.
* Entry is an aggressive LIMIT (trigger level +/- 2 points) that fills only when a later
  price trades through it. Initial stop: the setup candle's low (CALL) / high (PUT), but never
  more than 20 points away. Targets 2R / 3R / 4R. Manual point trail: buffer 10, lock 15.
* Ladder: CALL strikes ATM .. ATM+250, PUT strikes ATM .. ATM-250 (both out of the money).
* Sizing: 10,000 per lot x 4 lots (lot size always from contract metadata).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from config.hft_strategy import (
    CAPITAL_PER_LOT, DEFAULT_LOTS, ENTRY_LIMIT_OFFSET_POINTS, EXIT_LIMIT_OFFSET_POINTS, GAP_THRESHOLD_POINTS,
    HFT_GAP_OPEN_ENABLED_DEFAULT, INITIAL_SL_MAX_POINTS, MANUAL_TRAILING_ENABLED_DEFAULT, TARGET_R_MULTIPLES,
    TARGET_SYSTEM_ENABLED_DEFAULT, TRAIL_BUFFER_POINTS, TRAIL_MIN_LOCK_POINTS,
)
from config.hft_data import HFT_PE_STRIKE_OFFSETS, HFT_STRIKE_OFFSETS

Side = Literal["CALL", "PUT"]


@dataclass(frozen=True)
class HftGapOpenConfig:
    """Every HFT Gap-Open number in one place (defaults = config/hft_strategy.py)."""
    enabled: bool = HFT_GAP_OPEN_ENABLED_DEFAULT
    gap_threshold: float = GAP_THRESHOLD_POINTS
    entry_limit_offset: float = ENTRY_LIMIT_OFFSET_POINTS
    exit_limit_offset: float = EXIT_LIMIT_OFFSET_POINTS
    initial_sl_max_points: float = INITIAL_SL_MAX_POINTS
    targets_enabled: bool = TARGET_SYSTEM_ENABLED_DEFAULT
    target_r_multiples: tuple = TARGET_R_MULTIPLES
    manual_trailing_enabled: bool = MANUAL_TRAILING_ENABLED_DEFAULT
    trail_buffer: float = TRAIL_BUFFER_POINTS
    trail_min_lock: float = TRAIL_MIN_LOCK_POINTS
    capital_per_lot: float = CAPITAL_PER_LOT
    lots: int = DEFAULT_LOTS
    strike_step: int = 50
    call_offsets: tuple = HFT_STRIKE_OFFSETS
    put_offsets: tuple = HFT_PE_STRIKE_OFFSETS


DEFAULT_CONFIG = HftGapOpenConfig()


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
    side: Side = "CALL"


def _side(side: str) -> Side:
    side = str(side).upper()
    if side not in ("CALL", "PUT"):
        raise ValueError("side must be CALL or PUT")
    return side  # type: ignore[return-value]


def opening_gap(previous_close: float, current_open: float) -> float:
    """Opening gap of the configured HFT underlying (NIFTY futures in the current build)."""
    return float(current_open) - float(previous_close)


def gap_signal(previous_close: float, current_open: float, config: HftGapOpenConfig = DEFAULT_CONFIG) -> GapSignal | None:
    gap = opening_gap(previous_close, current_open)
    if gap >= config.gap_threshold:
        return GapSignal("CALL", gap)
    if gap <= -config.gap_threshold:
        return GapSignal("PUT", gap)
    return None


def first_candle_open_equals_low(candle: SetupCandle) -> bool:
    return Decimal(str(candle.open)) == Decimal(str(candle.low))


def first_candle_open_equals_high(candle: SetupCandle) -> bool:
    return Decimal(str(candle.open)) == Decimal(str(candle.high))


def setup_is_valid(candle: SetupCandle, side: Side = "CALL") -> bool:
    """CALL: Open = Low. PUT (mirror): Open = High."""
    return first_candle_open_equals_low(candle) if _side(side) == "CALL" else first_candle_open_equals_high(candle)


def entry_limit_price(reference_price: float, side: Side = "CALL",
                      config: HftGapOpenConfig = DEFAULT_CONFIG) -> float:
    """Aggressive trigger level: above the break for a CALL, below it for a PUT."""
    sign = 1 if _side(side) == "CALL" else -1
    return float(reference_price) + sign * config.entry_limit_offset


def exit_limit_price(option_price: float, config: HftGapOpenConfig = DEFAULT_CONFIG) -> float:
    """Selling the bought option (CE or PE): a limit a few points below its price, never a market order."""
    return max(0.05, float(option_price) - config.exit_limit_offset)


def calculate_initial_sl(entry_price: float, setup_extreme: float, side: Side = "CALL",
                         config: HftGapOpenConfig = DEFAULT_CONFIG) -> tuple[float, float]:
    """CALL: setup low below the entry; PUT: setup high above it. Never more than the cap away."""
    entry, extreme = float(entry_price), float(setup_extreme)
    if _side(side) == "CALL":
        risk = entry - extreme
        stop = extreme if risk <= config.initial_sl_max_points else entry - config.initial_sl_max_points
        return stop, entry - stop
    risk = extreme - entry
    stop = extreme if risk <= config.initial_sl_max_points else entry + config.initial_sl_max_points
    return stop, stop - entry


def next_candle_breaks_high(setup_candle: SetupCandle, next_high: float) -> bool:
    return float(next_high) > float(setup_candle.high)


def next_candle_breaks_low(setup_candle: SetupCandle, next_low: float) -> bool:
    return float(next_low) < float(setup_candle.low)


def evaluate_entry(setup_candle: SetupCandle, next_extreme: float, reference_price: float, side: Side = "CALL",
                   config: HftGapOpenConfig = DEFAULT_CONFIG) -> EntryDecision:
    """``next_extreme``: the next candle's HIGH for a CALL, its LOW for a PUT."""
    side = _side(side)
    if not setup_is_valid(setup_candle, side):
        return EntryDecision(False, None, None, None, None, side)
    broke = next_candle_breaks_high(setup_candle, next_extreme) if side == "CALL" \
        else next_candle_breaks_low(setup_candle, next_extreme)
    if not broke:
        return EntryDecision(False, None, None, None, None, side)
    limit_price = entry_limit_price(reference_price, side, config)
    # A historical backtest may only fill when price actually traded through the limit.
    traded_through = float(next_extreme) >= limit_price if side == "CALL" else float(next_extreme) <= limit_price
    if not traded_through:
        return EntryDecision(False, reference_price, limit_price, None, None, side)
    extreme = setup_candle.low if side == "CALL" else setup_candle.high
    stop, risk = calculate_initial_sl(limit_price, extreme, side, config)
    return EntryDecision(True, reference_price, limit_price, stop, risk, side)


def target_prices(entry_price: float, risk_points: float, side: Side = "CALL",
                  config: HftGapOpenConfig = DEFAULT_CONFIG) -> list[float]:
    """2R / 3R / 4R targets in the trade's direction (empty when targets are off)."""
    if not config.targets_enabled:
        return []
    sign = 1 if _side(side) == "CALL" else -1
    return [float(entry_price) + sign * r * float(risk_points) for r in config.target_r_multiples]


def trailing_stop_price(entry_price: float, current_price: float, buffer_points: float = TRAIL_BUFFER_POINTS,
                        min_lock_points: float = TRAIL_MIN_LOCK_POINTS, side: Side = "CALL") -> float | None:
    """Manual point trail. CALL: +25 with buffer 10 and lock 15 -> stop at entry + 15. PUT mirrors it."""
    if _side(side) == "CALL":
        profit = float(current_price) - float(entry_price)
        if profit < float(min_lock_points):
            return None
        return max(float(current_price) - float(buffer_points), float(entry_price) + float(min_lock_points))
    profit = float(entry_price) - float(current_price)
    if profit < float(min_lock_points):
        return None
    return min(float(current_price) + float(buffer_points), float(entry_price) - float(min_lock_points))


def option_ladder(atm_strike: int, side: Side, config: HftGapOpenConfig = DEFAULT_CONFIG) -> list[tuple[int, str]]:
    """Strikes to watch: CE at ATM .. ATM+250, PE at ATM .. ATM-250 (out of the money)."""
    if _side(side) == "CALL":
        return [(int(atm_strike) + int(o), "CE") for o in config.call_offsets]
    return [(int(atm_strike) + int(o), "PE") for o in config.put_offsets]


def capital_allocation(capital_per_lot: float = CAPITAL_PER_LOT, lots: int = DEFAULT_LOTS) -> float:
    if lots < 1:
        raise ValueError("lots must be >= 1")
    if capital_per_lot <= 0:
        raise ValueError("capital_per_lot must be > 0")
    return float(capital_per_lot) * int(lots)
