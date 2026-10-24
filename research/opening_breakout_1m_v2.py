"""Opening Breakout V2 pure strategy logic.

This module is broker-neutral and contains no network calls.  It expands the
experimental V1 into a configurable, multi-filter candidate/confirmation
engine and reuses the same mathematical risk-sizing principles as the
project's risk engine without modifying that locked/reusable module.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Literal, Sequence

MarketBias = Literal["UP", "DOWN", "NEUTRAL"]
TradeInstrument = Literal["CALL", "PUT", "FUTURES", "SPOT"]
Direction = Literal["LONG", "SHORT"]
Trigger = Literal[
    "CANDLE_HIGH",
    "CANDLE_LOW",
    "ABOVE_VWAP",
    "BELOW_VWAP",
    "CLOSE_ABOVE_UPPER_BB",
    "CLOSE_BELOW_LOWER_BB",
    "KTMI",
    "DMI",
]
SLMode = Literal[
    "OFF",
    "CUSTOM_POINTS",
    "CANDLE_1_HIGH",
    "CANDLE_1_LOW",
    "VWAP",
    "VALUE",
]
TPMode = Literal["OFF", "CUSTOM_POINTS", "VALUE", "RR_RATIO"]
StrikeSelectorMode = Literal["LOT_VALUE", "PRICE_RANGE", "ATM_DISTANCE"]


@dataclass(frozen=True)
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class IndicatorSnapshot:
    vwap: float | None = None
    upper_bb: float | None = None
    lower_bb: float | None = None
    ktmi_buying_speed: float | None = None
    ktmi_selling_speed: float | None = None
    ktmi_momentum_speed: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    adx: float | None = None


@dataclass(frozen=True)
class V2Config:
    capital_allocation_percent: float = 100.0
    selected_timeframes: tuple[str, ...] = ("1M",)
    market_bias: MarketBias = "NEUTRAL"
    trade_instrument: TradeInstrument = "CALL"

    filter_open_high: bool = False
    filter_open_low: bool = True
    open_equal_tolerance_points: float = 0.05

    selected_triggers: tuple[Trigger, ...] = ("CANDLE_HIGH",)

    ktmi_buy_call_buying_speed: float = 0.5
    ktmi_buy_put_selling_speed: float = 0.5
    ktmi_buy_call_momentum_speed: float = 0.5
    ktmi_buy_put_momentum_speed: float = -0.5

    dmi_length: int = 14
    dmi_adx_smoothing: int = 14
    dmi_buy_call_plus_di: float = 25.0
    dmi_buy_put_minus_di: float = 25.0
    dmi_adx_threshold: float = 25.0

    strike_selector_mode: StrikeSelectorMode = "LOT_VALUE"
    lot_value_target: float = 10000.0
    option_price_min: float = 80.0
    option_price_max: float = 100.0
    atm_distance_points: float = 0.0

    sl_mode: SLMode = "CUSTOM_POINTS"
    custom_sl_points: float = 20.0
    sl_value_cap: float = 10000.0

    tp_mode: TPMode = "RR_RATIO"
    custom_tp_points: float = 20.0
    tp_value_target: float = 10000.0
    rr_multiplier: float = 2.0

    trailing_enabled: bool = False
    trail_trigger_points: float = 40.0
    trail_distance_points: float = 20.0
    trail_to_cost: bool = False
    trail_rr_steps: tuple[tuple[float, float], ...] = ((2.0, 0.0), (3.0, 1.0))

    entry_buffer_points: float = 1.0
    max_slippage_points: float = 2.0
    fill_timeout_seconds: int = 10

    risk_method: Literal["FIXED_AMOUNT", "PERCENT_OF_CAPITAL"] = "FIXED_AMOUNT"
    risk_per_trade_value: float = 10000.0
    risk_per_trade_percent: float = 1.0

    def __post_init__(self) -> None:
        allowed_tf = {"5S", "10S", "20S", "30S", "1M", "3M", "5M"}
        if not self.selected_timeframes:
            raise ValueError("at least one timeframe is required")
        if any(tf not in allowed_tf for tf in self.selected_timeframes):
            raise ValueError("unsupported timeframe")
        if not 0 <= self.capital_allocation_percent <= 100:
            raise ValueError("capital_allocation_percent must be between 0 and 100")
        if self.market_bias not in {"UP", "DOWN", "NEUTRAL"}:
            raise ValueError("unsupported market_bias")
        if self.trade_instrument not in {"CALL", "PUT", "FUTURES", "SPOT"}:
            raise ValueError("unsupported trade_instrument")
        allowed_triggers = {
            "CANDLE_HIGH", "CANDLE_LOW", "ABOVE_VWAP", "BELOW_VWAP",
            "CLOSE_ABOVE_UPPER_BB", "CLOSE_BELOW_LOWER_BB", "KTMI", "DMI",
        }
        if any(t not in allowed_triggers for t in self.selected_triggers):
            raise ValueError("unsupported breakout trigger")
        if self.open_equal_tolerance_points < 0:
            raise ValueError("open_equal_tolerance_points must be >= 0")
        if self.sl_mode == "CUSTOM_POINTS" and self.custom_sl_points <= 0:
            raise ValueError("custom_sl_points must be > 0")
        if self.sl_mode == "VALUE" and self.sl_value_cap <= 0:
            raise ValueError("sl_value_cap must be > 0")
        if self.tp_mode == "CUSTOM_POINTS" and self.custom_tp_points <= 0:
            raise ValueError("custom_tp_points must be > 0")
        if self.tp_mode == "VALUE" and self.tp_value_target <= 0:
            raise ValueError("tp_value_target must be > 0")
        if self.tp_mode == "RR_RATIO" and self.rr_multiplier <= 0:
            raise ValueError("rr_multiplier must be > 0")
        if self.strike_selector_mode == "LOT_VALUE" and self.lot_value_target <= 0:
            raise ValueError("lot_value_target must be > 0")
        if self.strike_selector_mode == "PRICE_RANGE":
            if self.option_price_min <= 0 or self.option_price_max < self.option_price_min:
                raise ValueError("invalid option price range")
        if self.strike_selector_mode == "ATM_DISTANCE" and self.atm_distance_points < 0:
            raise ValueError("atm_distance_points must be >= 0")
        if self.entry_buffer_points < 0 or self.max_slippage_points < 0:
            raise ValueError("execution points must be >= 0")
        if self.fill_timeout_seconds <= 0:
            raise ValueError("fill_timeout_seconds must be > 0")
        if self.risk_method == "FIXED_AMOUNT" and self.risk_per_trade_value <= 0:
            raise ValueError("risk_per_trade_value must be > 0")
        if self.risk_method == "PERCENT_OF_CAPITAL" and not 0 < self.risk_per_trade_percent <= 100:
            raise ValueError("risk_per_trade_percent must be in (0, 100]")
        if "KTMI" in self.selected_triggers:
            if self.ktmi_buy_call_buying_speed is None or self.ktmi_buy_put_selling_speed is None:
                raise ValueError("KTMI thresholds are required")
        if "DMI" in self.selected_triggers:
            if self.dmi_length <= 0 or self.dmi_adx_smoothing <= 0:
                raise ValueError("DMI lengths must be > 0")
            if self.dmi_buy_call_plus_di <= 0 or self.dmi_buy_put_minus_di <= 0 or self.dmi_adx_threshold <= 0:
                raise ValueError("DMI thresholds must be > 0")


@dataclass(frozen=True)
class Signal:
    direction: Direction
    instrument: TradeInstrument
    breakout_reason: str
    setup_timestamp: int


@dataclass(frozen=True)
class OpeningAlert:
    symbol: str
    strike: float | None
    option_type: str | None
    condition: Literal["OPEN_LOW", "OPEN_HIGH"]
    timestamp: int


@dataclass(frozen=True)
class OptionOpeningCandle:
    symbol: str
    strike: float | None
    option_type: str | None
    candle: Candle


@dataclass(frozen=True)
class ContractQuote:
    symbol: str
    option_type: str | None
    strike: float | None
    ltp: float
    lot_size: int
    expiry: str | None = None


@dataclass(frozen=True)
class PositionSize:
    risk_budget: float
    capital_allocation_budget: float
    risk_per_unit: float
    theoretical_quantity: float
    quantity: int
    lots: int
    actual_risk: float
    notional: float
    unused_risk: float
    unused_allocation: float


def build_opening_alerts(
    option_candles: Sequence[OptionOpeningCandle],
    config: V2Config,
) -> tuple[OpeningAlert, ...]:
    """Return display-only alerts for OPEN=LOW/HIGH option candles."""
    alerts: list[OpeningAlert] = []
    for item in option_candles:
        if config.filter_open_low and _within(
            item.candle.open, item.candle.low, config.open_equal_tolerance_points
        ):
            alerts.append(
                OpeningAlert(
                    symbol=item.symbol,
                    strike=item.strike,
                    option_type=item.option_type,
                    condition="OPEN_LOW",
                    timestamp=item.candle.timestamp,
                )
            )
        if config.filter_open_high and _within(
            item.candle.open, item.candle.high, config.open_equal_tolerance_points
        ):
            alerts.append(
                OpeningAlert(
                    symbol=item.symbol,
                    strike=item.strike,
                    option_type=item.option_type,
                    condition="OPEN_HIGH",
                    timestamp=item.candle.timestamp,
                )
            )
    return tuple(alerts)


def calculation_timeframe(selected_timeframes: Sequence[str]) -> str:
    """Return the common calculation timeframe.

    The requested rule is explicit: a multi-timeframe selection uses 1-minute
    candles for candle high/low/VWAP/BB calculations.
    """
    if not selected_timeframes:
        raise ValueError("at least one timeframe is required")
    return "1M" if len(set(selected_timeframes)) > 1 else selected_timeframes[0]


def _within(a: float, b: float, tolerance: float) -> bool:
    return abs(float(a) - float(b)) <= float(tolerance)


def opening_candidate_directions(candle: Candle, config: V2Config) -> tuple[Direction, ...]:
    """Return bullish/bearish candidates generated by the opening filters.

    OPEN=LOW produces a bullish/call-side candidate.
    OPEN=HIGH produces a bearish/put-side candidate.
    If both are enabled they are independent OR candidates, not an impossible
    AND requirement on the same candle.
    """
    if not config.filter_open_high and not config.filter_open_low:
        return ("LONG", "SHORT")

    directions: list[Direction] = []
    if config.filter_open_low and _within(candle.open, candle.low, config.open_equal_tolerance_points):
        directions.append("LONG")
    if config.filter_open_high and _within(candle.open, candle.high, config.open_equal_tolerance_points):
        directions.append("SHORT")
    return tuple(directions)


def _trigger_passes(
    trigger: Trigger,
    candle: Candle,
    indicators: IndicatorSnapshot,
    direction: Direction,
    config: V2Config,
    current_ltp: float | None = None,
) -> bool:
    if trigger == "CANDLE_HIGH":
        return current_ltp is not None and direction == "LONG" and current_ltp >= candle.high
    if trigger == "CANDLE_LOW":
        return current_ltp is not None and direction == "SHORT" and current_ltp <= candle.low
    if trigger == "ABOVE_VWAP":
        return indicators.vwap is not None and direction == "LONG" and candle.close > indicators.vwap
    if trigger == "BELOW_VWAP":
        return indicators.vwap is not None and direction == "SHORT" and candle.close < indicators.vwap
    if trigger == "CLOSE_ABOVE_UPPER_BB":
        return indicators.upper_bb is not None and direction == "LONG" and candle.close > indicators.upper_bb
    if trigger == "CLOSE_BELOW_LOWER_BB":
        return indicators.lower_bb is not None and direction == "SHORT" and candle.close < indicators.lower_bb
    if trigger == "KTMI":
        if direction == "LONG":
            return (
                indicators.ktmi_buying_speed is not None
                and indicators.ktmi_momentum_speed is not None
                and indicators.ktmi_buying_speed >= config.ktmi_buy_call_buying_speed
                and indicators.ktmi_momentum_speed >= config.ktmi_buy_call_momentum_speed
            )
        return (
            indicators.ktmi_selling_speed is not None
            and indicators.ktmi_momentum_speed is not None
            and indicators.ktmi_selling_speed >= config.ktmi_buy_put_selling_speed
            and indicators.ktmi_momentum_speed <= config.ktmi_buy_put_momentum_speed
        )
    if trigger == "DMI":
        if direction == "LONG":
            return (
                indicators.plus_di is not None
                and indicators.adx is not None
                and indicators.plus_di >= config.dmi_buy_call_plus_di
                and indicators.adx >= config.dmi_adx_threshold
            )
        return (
            indicators.minus_di is not None
            and indicators.adx is not None
            and indicators.minus_di >= config.dmi_buy_put_minus_di
            and indicators.adx >= config.dmi_adx_threshold
        )
    raise ValueError(f"unsupported trigger: {trigger}")


def _bias_allows(direction: Direction, config: V2Config) -> bool:
    if config.market_bias == "NEUTRAL":
        return True
    return (config.market_bias == "UP" and direction == "LONG") or (
        config.market_bias == "DOWN" and direction == "SHORT"
    )


def _instrument_allows(direction: Direction, config: V2Config) -> bool:
    if config.trade_instrument == "CALL":
        return direction == "LONG"
    if config.trade_instrument == "PUT":
        return direction == "SHORT"
    return True


def build_signals(
    candle: Candle,
    indicators: IndicatorSnapshot,
    config: V2Config,
    current_ltp: float | None = None,
) -> tuple[Signal, ...]:
    """Evaluate opening candidates and all selected confirmations.

    Selected confirmation triggers are AND conditions. Direction is determined
    from the opening candidate and/or directional trigger family. For options,
    LONG maps to CALL and SHORT maps to PUT; option entries are BUY-side.
    FUTURES/SPOT retain LONG/SHORT execution direction.
    """
    candidates = opening_candidate_directions(candle, config)

    if not candidates:
        return ()

    results: list[Signal] = []
    for direction in candidates:
        if not _bias_allows(direction, config):
            continue
        if not _instrument_allows(direction, config):
            continue
        if config.selected_triggers and not all(
            _trigger_passes(t, candle, indicators, direction, config, current_ltp)
            for t in config.selected_triggers
        ):
            continue

        if config.trade_instrument == "CALL":
            instrument: TradeInstrument = "CALL"
        elif config.trade_instrument == "PUT":
            instrument = "PUT"
        else:
            instrument = config.trade_instrument

        results.append(
            Signal(
                direction=direction,
                instrument=instrument,
                breakout_reason="+".join(config.selected_triggers) or "OPENING_FILTER",
                setup_timestamp=candle.timestamp,
            )
        )
    return tuple(results)


def stop_loss_price(
    fill_price: float,
    candle: Candle,
    mode: SLMode,
    direction: Direction,
    custom_points: float = 20.0,
    vwap: float | None = None,
) -> float | None:
    if mode == "OFF":
        return None
    if mode == "CUSTOM_POINTS":
        return fill_price - custom_points if direction == "LONG" else fill_price + custom_points
    if mode == "CANDLE_1_LOW":
        return candle.low
    if mode == "CANDLE_1_HIGH":
        return candle.high
    if mode == "VWAP":
        if vwap is None:
            raise ValueError("VWAP is required for VWAP stop")
        return float(vwap)
    if mode == "VALUE":
        raise ValueError("VALUE SL is a risk-budget mode; derive the price from quantity")
    raise ValueError(f"unsupported SL mode: {mode}")


def target_price(
    fill_price: float,
    stop_price: float | None,
    mode: TPMode,
    direction: Direction,
    custom_points: float = 20.0,
    value_target: float = 10000.0,
    rr_multiplier: float = 2.0,
    quantity: int = 0,
) -> float | None:
    if mode == "OFF":
        return None
    if mode == "CUSTOM_POINTS":
        return fill_price + custom_points if direction == "LONG" else fill_price - custom_points
    if mode == "RR_RATIO":
        if stop_price is None:
            raise ValueError("RR target requires a stop")
        risk = abs(fill_price - stop_price)
        if risk <= 0:
            raise ValueError("RR target requires positive risk")
        return fill_price + risk * rr_multiplier if direction == "LONG" else fill_price - risk * rr_multiplier
    if mode == "VALUE":
        if quantity <= 0:
            raise ValueError("quantity is required for VALUE target")
        points = value_target / quantity
        return fill_price + points if direction == "LONG" else fill_price - points
    raise ValueError(f"unsupported TP mode: {mode}")


def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss_price_value: float,
    lot_size: int,
    config: V2Config,
) -> PositionSize:
    """Size in complete lots under both risk and capital-allocation caps.

    Effective risk budget is the smaller of the configured per-trade risk and
    the optional whole-position VALUE stop cap.  Capital allocation limits
    notional exposure independently.
    """
    if capital <= 0 or entry_price <= 0 or stop_loss_price_value <= 0:
        raise ValueError("capital and prices must be > 0")
    if lot_size < 1:
        raise ValueError("lot_size must be >= 1")

    if config.risk_method == "FIXED_AMOUNT":
        risk_budget = config.risk_per_trade_value
    else:
        risk_budget = capital * config.risk_per_trade_percent / 100.0

    if config.sl_mode == "VALUE":
        risk_budget = min(risk_budget, config.sl_value_cap)

    allocation_budget = capital * config.capital_allocation_percent / 100.0
    risk_per_unit = abs(entry_price - stop_loss_price_value)
    if risk_per_unit <= 0:
        raise ValueError("entry and stop-loss prices must differ")

    by_risk_qty = floor(risk_budget / risk_per_unit)
    by_capital_qty = floor(allocation_budget / entry_price)
    quantity = min(by_risk_qty, by_capital_qty)
    lots = quantity // lot_size
    quantity = lots * lot_size

    actual_risk = quantity * risk_per_unit
    notional = quantity * entry_price

    return PositionSize(
        risk_budget=risk_budget,
        capital_allocation_budget=allocation_budget,
        risk_per_unit=risk_per_unit,
        theoretical_quantity=risk_budget / risk_per_unit,
        quantity=quantity,
        lots=lots,
        actual_risk=actual_risk,
        notional=notional,
        unused_risk=risk_budget - actual_risk,
        unused_allocation=allocation_budget - notional,
    )


def select_option_contract(
    contracts: Sequence[ContractQuote],
    mode: StrikeSelectorMode,
    lot_value_target: float,
    price_min: float,
    price_max: float,
    atm_strike: float | None = None,
    atm_distance_points: float = 0.0,
) -> ContractQuote | None:
    """Select one contract using explicit deterministic rules.

    LOT_VALUE compares LTP * lot_size to the target value.
    PRICE_RANGE restricts LTP to an inclusive range and chooses the nearest
    contract to the midpoint.
    ATM_DISTANCE chooses the closest strike to ATM + requested distance.
    """
    if not contracts:
        return None

    candidates = list(contracts)
    if mode == "PRICE_RANGE":
        candidates = [c for c in candidates if price_min <= c.ltp <= price_max]
        if not candidates:
            return None
        midpoint = (price_min + price_max) / 2.0
        return min(candidates, key=lambda c: abs(c.ltp - midpoint))

    if mode == "ATM_DISTANCE":
        if atm_strike is None:
            raise ValueError("atm_strike is required for ATM_DISTANCE")
        target_strike = atm_strike + atm_distance_points
        return min(
            candidates,
            key=lambda c: abs((c.strike if c.strike is not None else float("inf")) - target_strike),
        )

    return min(candidates, key=lambda c: abs(c.ltp * c.lot_size - lot_value_target))


def entry_allowed(
    ltp: float,
    breakout_price: float,
    direction: Direction,
    max_slippage_points: float,
) -> bool:
    distance = ltp - breakout_price if direction == "LONG" else breakout_price - ltp
    return distance <= max_slippage_points


def entry_limit_price(ltp: float, direction: Direction, buffer_points: float) -> float:
    return ltp + buffer_points if direction == "LONG" else ltp - buffer_points


def sl_trigger_limit_price(stop_price: float, direction: Direction, buffer_points: float) -> float:
    return stop_price - buffer_points if direction == "LONG" else stop_price + buffer_points


def trailing_stop_price(
    entry_price: float,
    planned_stop_price: float,
    current_stop_price: float,
    current_price: float,
    direction: Direction,
    enabled: bool,
    mode: Literal["POINTS", "RR_STEPS"] = "POINTS",
    trigger_points: float = 40.0,
    trail_distance_points: float = 20.0,
    trail_to_cost: bool = False,
    rr_steps: Sequence[tuple[float, float]] = ((2.0, 0.0), (3.0, 1.0)),
) -> float:
    """Return a monotonic trailing stop.

    POINTS mode: once profit reaches trigger_points, proposed stop is planned
    stop + trail_distance for LONG (or planned stop - trail_distance for SHORT).
    COST mode moves the stop to entry.

    RR_STEPS mode maps achieved R to a locked R level. The highest applicable
    step is used.
    """
    if not enabled:
        return current_stop_price

    if direction == "LONG":
        profit_points = current_price - entry_price
        risk_points = entry_price - planned_stop_price
    else:
        profit_points = entry_price - current_price
        risk_points = planned_stop_price - entry_price

    if risk_points <= 0:
        return current_stop_price

    proposed = current_stop_price

    if mode == "POINTS":
        if profit_points < trigger_points:
            return current_stop_price
        if trail_to_cost:
            proposed = entry_price
        else:
            proposed = planned_stop_price + trail_distance_points if direction == "LONG" else planned_stop_price - trail_distance_points
    elif mode == "RR_STEPS":
        achieved_rr = profit_points / risk_points
        applicable = [locked_r for trigger_rr, locked_r in rr_steps if achieved_rr >= trigger_rr]
        if not applicable:
            return current_stop_price
        locked_rr = max(applicable)
        proposed = entry_price + risk_points * locked_rr if direction == "LONG" else entry_price - risk_points * locked_rr
    else:
        raise ValueError("unsupported trailing mode")

    # Never loosen an existing stop.
    return max(current_stop_price, proposed) if direction == "LONG" else min(current_stop_price, proposed)
