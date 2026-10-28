"""
KTMI Universal signal engine.

Signal logic is kept separate from the KTMI calculation engine.

The rules in this module mirror the KTMI Universal Pine source:
- Buy requires trigger crossing + Speed > Signal + Speed > 0.
- Sell requires trigger crossing + Speed < Signal + Speed < 0.
- Empty trigger disables the corresponding signal.
- Confluence is based on the direction of ALL enabled modules,
  not on individual Buy/Sell trigger signals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.universal import KTMIResult


@dataclass(frozen=True)
class KTMISignalResult:
    """Signal state for one KTMI bar."""

    momentum_buy: bool = False
    momentum_sell: bool = False

    long_buy: bool = False
    long_sell: bool = False

    short_buy: bool = False
    short_sell: bool = False

    bullish_confluence: bool = False
    bearish_confluence: bool = False

    enabled_count: int = 0
    bullish_count: int = 0
    bearish_count: int = 0


def _is_valid(value: Optional[float]) -> bool:
    """Return True when a numeric value is available."""

    return value is not None


def _crossover(
    current: Optional[float],
    previous: Optional[float],
    level: Optional[float],
    previous_level: Optional[float] = None,
) -> bool:
    """
    Pine-style crossover approximation.

    Current value must be above the level and the previous
    value must not have been above the previous level.

    When the level is constant, previous_level == level.
    """

    if current is None or previous is None or level is None:
        return False

    if previous_level is None:
        previous_level = level

    if previous_level is None:
        return False

    return (
        current > level
        and previous <= previous_level
    )


def _crossunder(
    current: Optional[float],
    previous: Optional[float],
    level: Optional[float],
    previous_level: Optional[float] = None,
) -> bool:
    """
    Pine-style crossunder approximation.

    Current value must be below the level and the previous
    value must not have been below the previous level.
    """

    if current is None or previous is None or level is None:
        return False

    if previous_level is None:
        previous_level = level

    return (
        current < level
        and previous >= previous_level
    )


def _module_buy(
    current_speed: Optional[float],
    previous_speed: Optional[float],
    current_signal: Optional[float],
    trigger: Optional[float],
) -> bool:
    """Apply the Pine KTMI Buy conditions."""

    if (
        not _is_valid(current_speed)
        or not _is_valid(previous_speed)
        or not _is_valid(current_signal)
        or trigger is None
    ):
        return False

    return (
        _crossover(
            current_speed,
            previous_speed,
            trigger,
        )
        and current_speed > current_signal
        and current_speed > 0
    )


def _module_sell(
    current_speed: Optional[float],
    previous_speed: Optional[float],
    current_signal: Optional[float],
    trigger: Optional[float],
) -> bool:
    """Apply the Pine KTMI Sell conditions."""

    if (
        not _is_valid(current_speed)
        or not _is_valid(previous_speed)
        or not _is_valid(current_signal)
        or trigger is None
    ):
        return False

    return (
        _crossunder(
            current_speed,
            previous_speed,
            trigger,
        )
        and current_speed < current_signal
        and current_speed < 0
    )


def _direction_state(
    speed: Optional[float],
    signal: Optional[float],
) -> Optional[str]:
    """
    Return the Pine confluence direction.

    Returns:
        'bullish'
        'bearish'
        None when equal/unavailable.
    """

    if speed is None or signal is None:
        return None

    if speed > signal:
        return "bullish"

    if speed < signal:
        return "bearish"

    return None


def calculate_signals(
    results: Sequence[KTMIResult],
    config: KTMIConfig,
) -> list[KTMISignalResult]:
    """
    Calculate KTMI signals for a sequence of KTMI results.

    The function intentionally preserves previous-bar information
    so trigger crossings can be detected.
    """

    output: list[KTMISignalResult] = []

    for index, result in enumerate(results):

        previous = (
            results[index - 1]
            if index > 0
            else None
        )

        # --------------------------------------------------------------
        # MOMENTUM SIGNALS
        # --------------------------------------------------------------

        momentum_buy = False
        momentum_sell = False

        if config.momentum.enabled:

            previous_speed = (
                previous.momentum.speed
                if previous is not None
                else None
            )

            momentum_buy = _module_buy(
                result.momentum.speed,
                previous_speed,
                result.momentum.signal,
                config.momentum_buy_trigger,
            )

            momentum_sell = _module_sell(
                result.momentum.speed,
                previous_speed,
                result.momentum.signal,
                config.momentum_sell_trigger,
            )

        # --------------------------------------------------------------
        # LONG SIGNALS
        # --------------------------------------------------------------

        long_buy = False
        long_sell = False

        if config.long_momentum.enabled:

            previous_speed = (
                previous.long_momentum.speed
                if previous is not None
                else None
            )

            long_buy = _module_buy(
                result.long_momentum.speed,
                previous_speed,
                result.long_momentum.signal,
                config.long_buy_trigger,
            )

            long_sell = _module_sell(
                result.long_momentum.speed,
                previous_speed,
                result.long_momentum.signal,
                config.long_sell_trigger,
            )

        # --------------------------------------------------------------
        # SHORT SIGNALS
        # --------------------------------------------------------------

        short_buy = False
        short_sell = False

        if config.short_momentum.enabled:

            previous_speed = (
                previous.short_momentum.speed
                if previous is not None
                else None
            )

            short_buy = _module_buy(
                result.short_momentum.speed,
                previous_speed,
                result.short_momentum.signal,
                config.short_buy_trigger,
            )

            short_sell = _module_sell(
                result.short_momentum.speed,
                previous_speed,
                result.short_momentum.signal,
                config.short_sell_trigger,
            )

        # --------------------------------------------------------------
        # PINE-EXACT CONFLUENCE
        # --------------------------------------------------------------
        #
        # Pine:
        #
        # enabledCount = number of enabled modules
        #
        # bullishCount = enabled modules where
        #                speed > signal
        #
        # bearishCount = enabled modules where
        #                speed < signal
        #
        # bullishConfluence =
        #     showConfluence
        #     and enabledCount > 1
        #     and bullishCount == enabledCount
        #
        # bearishConfluence =
        #     showConfluence
        #     and enabledCount > 1
        #     and bearishCount == enabledCount
        #
        # --------------------------------------------------------------

        enabled_count = 0
        bullish_count = 0
        bearish_count = 0

        modules = (
            (
                config.momentum.enabled,
                result.momentum.speed,
                result.momentum.signal,
            ),
            (
                config.long_momentum.enabled,
                result.long_momentum.speed,
                result.long_momentum.signal,
            ),
            (
                config.short_momentum.enabled,
                result.short_momentum.speed,
                result.short_momentum.signal,
            ),
        )

        for enabled, speed, signal in modules:

            if not enabled:
                continue

            enabled_count += 1

            direction = _direction_state(
                speed,
                signal,
            )

            if direction == "bullish":
                bullish_count += 1

            elif direction == "bearish":
                bearish_count += 1

        # The Python engine does not have a visual-only
        # showConfluence setting. Confluence represents the
        # underlying Pine condition itself.
        bullish_confluence = (
            enabled_count > 1
            and bullish_count == enabled_count
        )

        bearish_confluence = (
            enabled_count > 1
            and bearish_count == enabled_count
        )

        output.append(
            KTMISignalResult(
                momentum_buy=momentum_buy,
                momentum_sell=momentum_sell,
                long_buy=long_buy,
                long_sell=long_sell,
                short_buy=short_buy,
                short_sell=short_sell,
                bullish_confluence=bullish_confluence,
                bearish_confluence=bearish_confluence,
                enabled_count=enabled_count,
                bullish_count=bullish_count,
                bearish_count=bearish_count,
            )
        )

    return output


__all__ = [
    "KTMISignalResult",
    "calculate_signals",
]