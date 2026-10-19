"""Opening Breakout V2 historical signal/event scanner.

Research-only and broker-neutral.

This module intentionally stops at the *signal boundary*. It does not place
orders or simulate fills/P&L. The next execution milestone consumes these
events.

No-lookahead rule:
- Candle 0 is the completed opening/setup candle.
- No signal can occur on Candle 0.
- Confirmation is evaluated only on a later completed candle.
- Indicator snapshots must represent information available at that candle's
  completion time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from research.opening_breakout_1m_v2 import (
    Candle,
    IndicatorSnapshot,
    Signal,
    V2Config,
    _bias_allows,
    _instrument_allows,
    _within,
    calculation_timeframe,
    opening_candidate_directions,
)


IndicatorProvider = Callable[[int, Candle], IndicatorSnapshot]


@dataclass(frozen=True)
class SignalSeries:
    """One tradable instrument's completed candles for one session."""

    symbol: str
    option_type: str | None
    strike: float | None
    lot_size: int
    candles: tuple[Candle, ...]


@dataclass(frozen=True)
class OpeningAlertEvent:
    symbol: str
    option_type: str | None
    strike: float | None
    condition: str
    timestamp: int


@dataclass(frozen=True)
class OpeningBreakoutEvent:
    symbol: str
    option_type: str | None
    strike: float | None
    lot_size: int
    direction: str
    instrument: str
    setup_timestamp: int
    trigger_timestamp: int
    breakout_price: float
    trigger_reasons: tuple[str, ...]


@dataclass(frozen=True)
class SessionScanResult:
    calculation_timeframe: str
    alerts: tuple[OpeningAlertEvent, ...]
    signals: tuple[OpeningBreakoutEvent, ...]


def _trigger_passes(
    trigger: str,
    *,
    setup: Candle,
    current: Candle,
    indicators: IndicatorSnapshot,
    direction: str,
    config: V2Config,
) -> bool:
    """Evaluate one confirmation on the current completed candle."""
    if trigger == "CANDLE_HIGH":
        return direction == "LONG" and current.high >= setup.high

    if trigger == "CANDLE_LOW":
        return direction == "SHORT" and current.low <= setup.low

    if trigger == "ABOVE_VWAP":
        return (
            direction == "LONG"
            and indicators.vwap is not None
            and current.close > indicators.vwap
        )

    if trigger == "BELOW_VWAP":
        return (
            direction == "SHORT"
            and indicators.vwap is not None
            and current.close < indicators.vwap
        )

    if trigger == "CLOSE_ABOVE_UPPER_BB":
        return (
            direction == "LONG"
            and indicators.upper_bb is not None
            and current.close > indicators.upper_bb
        )

    if trigger == "CLOSE_BELOW_LOWER_BB":
        return (
            direction == "SHORT"
            and indicators.lower_bb is not None
            and current.close < indicators.lower_bb
        )

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


def scan_series(
    series: SignalSeries,
    config: V2Config,
    indicator_provider: IndicatorProvider,
) -> tuple[tuple[OpeningAlertEvent, ...], tuple[OpeningBreakoutEvent, ...]]:
    """Scan one completed-candle series for alerts and at most one signal."""
    if not series.candles:
        return (), ()
    if series.lot_size < 1:
        raise ValueError("lot_size must be >= 1")

    setup = series.candles[0]
    candidates = opening_candidate_directions(setup, config)

    alerts: list[OpeningAlertEvent] = []
    if config.filter_open_low and _within(
        setup.open, setup.low, config.open_equal_tolerance_points
    ):
        alerts.append(
            OpeningAlertEvent(
                symbol=series.symbol,
                option_type=series.option_type,
                strike=series.strike,
                condition="OPEN_LOW",
                timestamp=setup.timestamp,
            )
        )
    if config.filter_open_high and _within(
        setup.open, setup.high, config.open_equal_tolerance_points
    ):
        alerts.append(
            OpeningAlertEvent(
                symbol=series.symbol,
                option_type=series.option_type,
                strike=series.strike,
                condition="OPEN_HIGH",
                timestamp=setup.timestamp,
            )
        )

    if not candidates:
        return tuple(alerts), ()

    # The opening candle is never a trigger candle.
    for current in series.candles[1:]:
        for direction in candidates:
            if not _bias_allows(direction, config):
                continue
            if not _instrument_allows(direction, config):
                continue

            indicators = indicator_provider(
                current.timestamp,
                current,
            )

            if not all(
                _trigger_passes(
                    trigger,
                    setup=setup,
                    current=current,
                    indicators=indicators,
                    direction=direction,
                    config=config,
                )
                for trigger in config.selected_triggers
            ):
                continue

            breakout_price = (
                setup.high if direction == "LONG" else setup.low
            )

            instrument = config.trade_instrument
            event = OpeningBreakoutEvent(
                symbol=series.symbol,
                option_type=series.option_type,
                strike=series.strike,
                lot_size=series.lot_size,
                direction=direction,
                instrument=instrument,
                setup_timestamp=setup.timestamp,
                trigger_timestamp=current.timestamp,
                breakout_price=breakout_price,
                trigger_reasons=tuple(config.selected_triggers),
            )
            return tuple(alerts), (event,)

    return tuple(alerts), ()


def scan_session(
    series: Sequence[SignalSeries],
    config: V2Config,
    indicator_provider: IndicatorProvider,
) -> SessionScanResult:
    """Scan all supplied instruments without modifying their data."""
    timeframe = calculation_timeframe(config.selected_timeframes)
    alerts: list[OpeningAlertEvent] = []
    signals: list[OpeningBreakoutEvent] = []

    for item in series:
        item_alerts, item_signals = scan_series(
            item,
            config,
            indicator_provider,
        )
        alerts.extend(item_alerts)
        signals.extend(item_signals)

    signals.sort(key=lambda item: (item.trigger_timestamp, item.symbol))
    alerts.sort(key=lambda item: (item.timestamp, item.symbol, item.condition))

    return SessionScanResult(
        calculation_timeframe=timeframe,
        alerts=tuple(alerts),
        signals=tuple(signals),
    )


__all__ = [
    "IndicatorProvider",
    "OpeningAlertEvent",
    "OpeningBreakoutEvent",
    "SessionScanResult",
    "SignalSeries",
    "scan_series",
    "scan_session",
]
