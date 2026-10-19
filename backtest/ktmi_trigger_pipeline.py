from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from backtest.models import BacktestBar
from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from strategies.ktmi_trigger_strategy import (
    DEFAULT_KTMI_TRIGGER_CONFIG,
    KTMITriggerEvent,
    KTMITriggerStrategyConfig,
    evaluate_ktmi_trigger_strategies,
)


@dataclass(frozen=True)
class KTMITiggerPipelineResult:
    """KTMI calculation and locked Strategy A/B events for eligible bars."""

    bars: tuple[BacktestBar, ...]
    ktmi_results: tuple[object, ...]
    events: tuple[KTMITriggerEvent, ...]


def run_ktmi_trigger_pipeline(
    bars: Sequence[BacktestBar],
    ktmi_config: KTMIConfig,
    trigger_config: KTMITriggerStrategyConfig = DEFAULT_KTMI_TRIGGER_CONFIG,
) -> KTMITiggerPipelineResult:
    """Run existing KTMI Universal calculation then locked Strategy A/B.

    This is an orchestration boundary only. It does not alter indicator
    calculations or trigger definitions.
    """
    if not bars:
        raise ValueError("Bars cannot be empty.")

    ohlc = [
        OHLCData(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]

    results = calculate_ktmi(ohlc, ktmi_config)

    events: list[KTMITriggerEvent] = []

    for index in range(1, len(results)):
        previous = results[index - 1]
        current = results[index]

        events.extend(
            evaluate_ktmi_trigger_strategies(
                previous_momentum_speed=previous.momentum.speed,
                current_momentum_speed=current.momentum.speed,
                previous_long_speed=previous.long_momentum.speed,
                current_long_speed=current.long_momentum.speed,
                previous_short_speed=previous.short_momentum.speed,
                current_short_speed=current.short_momentum.speed,
                config=trigger_config,
                index=index,
                timestamp=bars[index].timestamp,
            )
        )

    return KTMITiggerPipelineResult(
        bars=tuple(bars),
        ktmi_results=tuple(results),
        events=tuple(events),
    )
