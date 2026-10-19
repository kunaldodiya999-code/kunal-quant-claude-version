"""Pure signal and price-model logic for Opening Breakout V1.

No broker calls and no state mutation. This is an experimental strategy layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

MarketBias = Literal["UP", "DOWN", "NEUTRAL"]
Instrument = Literal["CALL", "PUT"]
BreakoutTrigger = Literal["1_MIN_HIGH", "1_MIN_LOW"]
SLMode = Literal["OFF", "CUSTOM_POINTS", "CANDLE_1_LOW", "CANDLE_1_HIGH", "CANDLE_1_MIDPOINT", "VWAP"]
TPMode = Literal["OFF", "CUSTOM_POINTS", "RR_RATIO"]


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StrategyConfig:
    market_bias: MarketBias = "NEUTRAL"
    trade_instrument: Instrument = "CALL"
    filter_open_high: bool = False
    filter_open_low: bool = True
    open_equal_tolerance_points: float = 0.05
    breakout_trigger: BreakoutTrigger = "1_MIN_HIGH"
    sl_mode: SLMode = "CUSTOM_POINTS"
    custom_sl_points: float = 20.0
    tp_mode: TPMode = "RR_RATIO"
    custom_tp_points: float = 40.0
    rr_multiplier: float = 2.0

    def __post_init__(self) -> None:
        if self.market_bias not in {"UP", "DOWN", "NEUTRAL"}:
            raise ValueError("market_bias must be UP, DOWN, or NEUTRAL")
        if self.trade_instrument not in {"CALL", "PUT"}:
            raise ValueError("trade_instrument must be CALL or PUT")
        if self.breakout_trigger not in {"1_MIN_HIGH", "1_MIN_LOW"}:
            raise ValueError("unsupported breakout_trigger")
        if self.sl_mode not in {"OFF", "CUSTOM_POINTS", "CANDLE_1_LOW", "CANDLE_1_HIGH", "CANDLE_1_MIDPOINT", "VWAP"}:
            raise ValueError("unsupported sl_mode")
        if self.tp_mode not in {"OFF", "CUSTOM_POINTS", "RR_RATIO"}:
            raise ValueError("unsupported tp_mode")
        if self.open_equal_tolerance_points < 0:
            raise ValueError("open_equal_tolerance_points must be >= 0")
        if self.custom_sl_points <= 0 and self.sl_mode == "CUSTOM_POINTS":
            raise ValueError("custom_sl_points must be > 0")
        if self.custom_tp_points <= 0 and self.tp_mode == "CUSTOM_POINTS":
            raise ValueError("custom_tp_points must be > 0")
        if self.rr_multiplier <= 0 and self.tp_mode == "RR_RATIO":
            raise ValueError("rr_multiplier must be > 0")


@dataclass(frozen=True)
class EntrySignal:
    instrument: Instrument
    direction: Literal["LONG", "SHORT"]
    breakout_price: float
    setup_timestamp: int


def _within(value_a: float, value_b: float, tolerance: float) -> bool:
    return abs(float(value_a) - float(value_b)) <= float(tolerance)


def opening_filter_passes(candle: Candle, config: StrategyConfig) -> bool:
    if not config.filter_open_high and not config.filter_open_low:
        return True
    high_ok = (not config.filter_open_high) or _within(candle.open, candle.high, config.open_equal_tolerance_points)
    low_ok = (not config.filter_open_low) or _within(candle.open, candle.low, config.open_equal_tolerance_points)
    return high_ok and low_ok


def bias_allows(config: StrategyConfig, direction: Literal["LONG", "SHORT"]) -> bool:
    if config.market_bias == "NEUTRAL":
        return True
    if config.market_bias == "UP":
        return direction == "LONG"
    return direction == "SHORT"


def build_entry_signal(candle: Candle, config: StrategyConfig) -> EntrySignal | None:
    if not opening_filter_passes(candle, config):
        return None

    direction: Literal["LONG", "SHORT"] = (
        "LONG" if config.breakout_trigger == "1_MIN_HIGH" else "SHORT"
    )
    if not bias_allows(config, direction):
        return None

    breakout_price = candle.high if direction == "LONG" else candle.low
    return EntrySignal(
        instrument=config.trade_instrument,
        direction=direction,
        breakout_price=float(breakout_price),
        setup_timestamp=candle.timestamp,
    )


def stop_loss_price(
    fill_price: float,
    candle: Candle,
    mode: SLMode,
    custom_points: float = 20.0,
    vwap: float | None = None,
    direction: Literal["LONG", "SHORT"] = "LONG",
) -> float | None:
    if mode == "OFF":
        return None
    if mode == "CUSTOM_POINTS":
        return float(fill_price - custom_points if direction == "LONG" else fill_price + custom_points)
    if mode == "CANDLE_1_LOW":
        return float(candle.low)
    if mode == "CANDLE_1_HIGH":
        return float(candle.high)
    if mode == "CANDLE_1_MIDPOINT":
        return float((candle.high + candle.low) / 2.0)
    if mode == "VWAP":
        if vwap is None:
            raise ValueError("vwap is required for VWAP stop")
        return float(vwap)
    raise ValueError(f"Unsupported SL mode: {mode}")


def target_price(
    fill_price: float,
    stop_price: float | None,
    mode: TPMode,
    custom_points: float = 40.0,
    rr_multiplier: float = 2.0,
    direction: Literal["LONG", "SHORT"] = "LONG",
) -> float | None:
    if mode == "OFF":
        return None
    if mode == "CUSTOM_POINTS":
        return float(fill_price + custom_points if direction == "LONG" else fill_price - custom_points)
    if mode == "RR_RATIO":
        if stop_price is None:
            raise ValueError("RR_RATIO target requires a stop price")
        risk = abs(float(fill_price) - float(stop_price))
        if risk <= 0:
            raise ValueError("RR target requires positive stop distance")
        return float(fill_price + risk * rr_multiplier if direction == "LONG" else fill_price - risk * rr_multiplier)
    raise ValueError(f"Unsupported TP mode: {mode}")


def entry_limit_price(
    ltp: float,
    direction: Literal["LONG", "SHORT"],
    buffer_points: float = 2.0,
) -> float:
    return float(ltp + buffer_points if direction == "LONG" else ltp - buffer_points)


def entry_allowed(
    ltp: float,
    breakout_price: float,
    direction: Literal["LONG", "SHORT"],
    max_slippage_points: float,
) -> bool:
    distance = float(ltp) - float(breakout_price) if direction == "LONG" else float(breakout_price) - float(ltp)
    return distance <= float(max_slippage_points)


def sl_trigger_limit_price(
    stop_price: float,
    direction: Literal["LONG", "SHORT"],
    buffer_points: float = 2.0,
) -> float:
    return float(stop_price - buffer_points if direction == "LONG" else stop_price + buffer_points)
