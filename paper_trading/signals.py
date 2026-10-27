"""Pure signal adapter for the paper engine.

This module consumes completed OHLC bars and delegates signal calculations
to the existing KTMI Universal, locked Strategy A/B trigger helpers, and
module/confluence strategy engine. It does not resolve contracts, manage
positions, access the network, or submit orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from strategies.ktmi_trigger_strategy import (
    DEFAULT_KTMI_TRIGGER_CONFIG,
    KTMITriggerEvent,
    KTMITriggerStrategyConfig,
    evaluate_ktmi_trigger_strategies,
)
from strategies.strategy_engine import (
    StrategyEngineConfig,
    evaluate_series,
)

from paper_trading.engine import PaperEngineConfig, PaperStrategyId


@dataclass(frozen=True)
class PaperSignal:
    """An entry signal for a single paper strategy on a completed bar."""

    strategy_id: PaperStrategyId
    direction: str
    timestamp: int
    index: int
    reason: str
    # When the signal candle closed (IST epoch seconds). Entries are only
    # allowed at or after this moment. Set by the market-data pipeline.
    close_timestamp: int | None = None
    # Strikes away from ATM, out-of-the-money direction (-1 ITM1, 0 ATM, +1 OTM1...).
    strike_offset: int = 0
    # AUTO strike (owner 27 Oct 2026): ATM or ATM+1 is chosen at the entry by the money (strategies/funds_strike.py).
    strike_auto: bool = False


def _bar_value(bar: object, name: str) -> float:
    try:
        value = float(getattr(bar, name))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Every bar must provide a numeric {name}.") from exc
    return value


def _timestamp(bar: object) -> int:
    try:
        return int(getattr(bar, "timestamp"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Every bar must provide an integer timestamp.") from exc


def _to_ohlc(bars: Sequence[object]) -> list[OHLCData]:
    """Convert Candle/DerivedBar-like objects into the universal OHLC type."""
    converted: list[OHLCData] = []
    previous_timestamp: int | None = None
    for bar in bars:
        timestamp = _timestamp(bar)
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise ValueError("Signal bars must have strictly increasing timestamps.")
        previous_timestamp = timestamp
        converted.append(
            OHLCData(
                open=_bar_value(bar, "open"),
                high=_bar_value(bar, "high"),
                low=_bar_value(bar, "low"),
                close=_bar_value(bar, "close"),
            )
        )
    return converted


def evaluate_latest_paper_signals(
    bars: Sequence[object],
    *,
    paper_config: PaperEngineConfig | None = None,
    ktmi_config: KTMIConfig | None = None,
    trigger_config: KTMITriggerStrategyConfig = DEFAULT_KTMI_TRIGGER_CONFIG,
    module_config: StrategyEngineConfig | None = None,
) -> list[PaperSignal]:
    """Evaluate entry signals on the latest bar only.

    At least two bars are required for crossing strategies. The module/
    confluence strategy evaluates the full supplied history to preserve
    indicator warm-up. Call this only when a bar is complete; the function
    intentionally does not guess whether a feed candle has closed.
    """
    if not bars:
        return []

    paper_config = paper_config or PaperEngineConfig()
    universal_config = ktmi_config or KTMIConfig()
    ohlc_bars = _to_ohlc(bars)
    latest_index = len(bars) - 1
    latest_timestamp = _timestamp(bars[-1])
    signals: list[PaperSignal] = []

    if len(ohlc_bars) >= 2:
        calculated = calculate_ktmi(ohlc_bars, universal_config)
        previous, current = calculated[-2], calculated[-1]
        events: list[KTMITriggerEvent] = evaluate_ktmi_trigger_strategies(
            previous_momentum_speed=previous.momentum.speed,
            current_momentum_speed=current.momentum.speed,
            previous_long_speed=previous.long_momentum.speed,
            current_long_speed=current.long_momentum.speed,
            previous_short_speed=previous.short_momentum.speed,
            current_short_speed=current.short_momentum.speed,
            config=trigger_config,
            index=latest_index,
            timestamp=latest_timestamp,
        )
        for event in events:
            strategy_id = PaperStrategyId(event.strategy_id.value)
            if not paper_config.is_enabled(strategy_id):
                continue
            signals.append(
                PaperSignal(
                    strategy_id=strategy_id,
                    direction=event.direction.value,
                    timestamp=latest_timestamp,
                    index=latest_index,
                    reason=f"CROSS_{event.trigger_value:g}",
                )
            )

    if paper_config.module_confluence_enabled:
        engine_config = module_config or StrategyEngineConfig(ktmi_config=universal_config)
        module_results = evaluate_series(ohlc_bars, engine_config)
        if module_results:
            decision = module_results[-1].decision
            action = getattr(decision.action, "value", str(decision.action))
            direction = getattr(decision.direction, "value", decision.direction)
            if action in ("LONG", "SHORT") and direction in ("LONG", "SHORT"):
                signals.append(
                    PaperSignal(
                        strategy_id=PaperStrategyId.MODULE_CONFLUENCE,
                        direction=str(direction),
                        timestamp=latest_timestamp,
                        index=latest_index,
                        reason=getattr(decision.reason, "value", str(decision.reason)),
                    )
                )

    return signals


__all__ = ["PaperSignal", "evaluate_latest_paper_signals"]
