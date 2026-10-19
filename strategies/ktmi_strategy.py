"""
KTMI strategy layer for Kunal Quant.

This module converts KTMI signals into strategy-level entry decisions.

Important:
- KTMI calculation remains untouched.
- Direction filtering remains separate.
- No fixed Speed threshold is imposed.
- No stop-loss, target, trailing-stop, or position sizing is implemented here.
- Exit logic will be added separately after the strategy rules are finalized.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.signals import KTMISignalResult
from strategies.direction_filter import (
    Direction,
    DirectionDecision,
    DirectionFilterResult,
    DirectionMode,
    apply_direction_filter,
)


class StrategyAction(str, Enum):
    """Strategy-level action."""

    LONG = "LONG"
    SHORT = "SHORT"
    NO_ENTRY = "NO_ENTRY"


class StrategyReason(str, Enum):
    """Explicit reason for the strategy decision."""

    LONG_SIGNAL = "LONG_SIGNAL"
    SHORT_SIGNAL = "SHORT_SIGNAL"

    LONG_SIGNAL_BLOCKED = "LONG_SIGNAL_BLOCKED"
    SHORT_SIGNAL_BLOCKED = "SHORT_SIGNAL_BLOCKED"

    NO_SIGNAL = "NO_SIGNAL"

    MULTIPLE_DIRECTION_SIGNALS = (
        "MULTIPLE_DIRECTION_SIGNALS"
    )


@dataclass(frozen=True)
class KTMIEntryConfig:
    """
    Entry configuration for the KTMI strategy.

    If enabled modules generate a directional signal,
    the strategy can convert it into a LONG or SHORT entry.

    Confluence can optionally be required.

    No numerical KTMI threshold is hardcoded here.
    """

    require_bullish_confluence: bool = False
    require_bearish_confluence: bool = False

    allow_module_signals: bool = True
    allow_confluence_signals: bool = True

    direction_mode: DirectionMode = DirectionMode.BOTH

    def __post_init__(self) -> None:

        if (
            self.require_bullish_confluence
            and self.require_bearish_confluence
        ):
            raise ValueError(
                "Bullish and bearish confluence "
                "cannot both be required."
            )


@dataclass(frozen=True)
class KTMIEntryDecision:
    """Final KTMI strategy entry decision."""

    action: StrategyAction
    direction: Direction | None

    reason: StrategyReason

    direction_filter: DirectionFilterResult | None

    momentum_buy: bool
    long_buy: bool
    short_buy: bool

    momentum_sell: bool
    long_sell: bool
    short_sell: bool

    bullish_confluence: bool
    bearish_confluence: bool

    @property
    def should_enter(self) -> bool:
        """Return True when an entry is allowed."""

        return self.action != StrategyAction.NO_ENTRY


def _has_long_signal(
    signals: KTMISignalResult,
    config: KTMIEntryConfig,
) -> bool:
    """Determine whether a LONG signal exists."""

    module_signal = (
        signals.momentum_buy
        or signals.long_buy
        or signals.short_buy
    )

    confluence_signal = (
        signals.bullish_confluence
        and config.allow_confluence_signals
    )

    if config.require_bullish_confluence:
        return confluence_signal

    return (
        (
            module_signal
            and config.allow_module_signals
        )
        or confluence_signal
    )


def _has_short_signal(
    signals: KTMISignalResult,
    config: KTMIEntryConfig,
) -> bool:
    """Determine whether a SHORT signal exists."""

    module_signal = (
        signals.momentum_sell
        or signals.long_sell
        or signals.short_sell
    )

    confluence_signal = (
        signals.bearish_confluence
        and config.allow_confluence_signals
    )

    if config.require_bearish_confluence:
        return confluence_signal

    return (
        (
            module_signal
            and config.allow_module_signals
        )
        or confluence_signal
    )


def evaluate_ktmi_entry(
    signals: KTMISignalResult,
    strategy_config: KTMIEntryConfig,
    ktmi_config: KTMIConfig | None = None,
) -> KTMIEntryDecision:
    """
    Evaluate one KTMI signal row.

    Parameters
    ----------
    signals:
        KTMI signal result for the current bar.

    strategy_config:
        Entry and directional configuration.

    ktmi_config:
        Optional KTMI configuration retained for future
        strategy metadata/audit integration.

    Returns
    -------
    KTMIEntryDecision
        Strategy-level entry decision.
    """

    del ktmi_config

    long_signal = _has_long_signal(
        signals,
        strategy_config,
    )

    short_signal = _has_short_signal(
        signals,
        strategy_config,
    )

    # Both directions cannot safely become one position decision.
    # Preserve the ambiguity instead of arbitrarily selecting one.
    if long_signal and short_signal:

        return KTMIEntryDecision(
            action=StrategyAction.NO_ENTRY,
            direction=None,
            reason=StrategyReason.MULTIPLE_DIRECTION_SIGNALS,
            direction_filter=None,

            momentum_buy=signals.momentum_buy,
            long_buy=signals.long_buy,
            short_buy=signals.short_buy,

            momentum_sell=signals.momentum_sell,
            long_sell=signals.long_sell,
            short_sell=signals.short_sell,

            bullish_confluence=signals.bullish_confluence,
            bearish_confluence=signals.bearish_confluence,
        )

    if long_signal:

        direction_filter = apply_direction_filter(
            Direction.LONG,
            strategy_config.direction_mode,
        )

        if direction_filter.decision == DirectionDecision.BLOCK:

            return KTMIEntryDecision(
                action=StrategyAction.NO_ENTRY,
                direction=Direction.LONG,
                reason=StrategyReason.LONG_SIGNAL_BLOCKED,
                direction_filter=direction_filter,

                momentum_buy=signals.momentum_buy,
                long_buy=signals.long_buy,
                short_buy=signals.short_buy,

                momentum_sell=signals.momentum_sell,
                long_sell=signals.long_sell,
                short_sell=signals.short_sell,

                bullish_confluence=signals.bullish_confluence,
                bearish_confluence=signals.bearish_confluence,
            )

        return KTMIEntryDecision(
            action=StrategyAction.LONG,
            direction=Direction.LONG,
            reason=StrategyReason.LONG_SIGNAL,
            direction_filter=direction_filter,

            momentum_buy=signals.momentum_buy,
            long_buy=signals.long_buy,
            short_buy=signals.short_buy,

            momentum_sell=signals.momentum_sell,
            long_sell=signals.long_sell,
            short_sell=signals.short_sell,

            bullish_confluence=signals.bullish_confluence,
            bearish_confluence=signals.bearish_confluence,
        )

    if short_signal:

        direction_filter = apply_direction_filter(
            Direction.SHORT,
            strategy_config.direction_mode,
        )

        if direction_filter.decision == DirectionDecision.BLOCK:

            return KTMIEntryDecision(
                action=StrategyAction.NO_ENTRY,
                direction=Direction.SHORT,
                reason=StrategyReason.SHORT_SIGNAL_BLOCKED,
                direction_filter=direction_filter,

                momentum_buy=signals.momentum_buy,
                long_buy=signals.long_buy,
                short_buy=signals.short_buy,

                momentum_sell=signals.momentum_sell,
                long_sell=signals.long_sell,
                short_sell=signals.short_sell,

                bullish_confluence=signals.bullish_confluence,
                bearish_confluence=signals.bearish_confluence,
            )

        return KTMIEntryDecision(
            action=StrategyAction.SHORT,
            direction=Direction.SHORT,
            reason=StrategyReason.SHORT_SIGNAL,
            direction_filter=direction_filter,

            momentum_buy=signals.momentum_buy,
            long_buy=signals.long_buy,
            short_buy=signals.short_buy,

            momentum_sell=signals.momentum_sell,
            long_sell=signals.long_sell,
            short_sell=signals.short_sell,

            bullish_confluence=signals.bullish_confluence,
            bearish_confluence=signals.bearish_confluence,
        )

    return KTMIEntryDecision(
        action=StrategyAction.NO_ENTRY,
        direction=None,
        reason=StrategyReason.NO_SIGNAL,
        direction_filter=None,

        momentum_buy=signals.momentum_buy,
        long_buy=signals.long_buy,
        short_buy=signals.short_buy,

        momentum_sell=signals.momentum_sell,
        long_sell=signals.long_sell,
        short_sell=signals.short_sell,

        bullish_confluence=signals.bullish_confluence,
        bearish_confluence=signals.bearish_confluence,
    )


__all__ = [
    "KTMIEntryConfig",
    "KTMIEntryDecision",
    "StrategyAction",
    "StrategyReason",
    "evaluate_ktmi_entry",
]