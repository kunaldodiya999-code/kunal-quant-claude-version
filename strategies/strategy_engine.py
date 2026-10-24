"""
Kunal Quant Strategy Engine.

This module orchestrates:

    KTMI calculation
        ↓
    KTMI signals
        ↓
    KTMI strategy
        ↓
    Direction filter
        ↓
    Final entry decision

Risk management, position sizing, execution, and exits are
intentionally outside this first version.
"""

from __future__ import annotations

from dataclasses import dataclass

from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.signals import (
    KTMISignalResult,
    calculate_signals,
)
from indicators.ktmi.universal import (
    OHLCData,
    KTMIResult,
    calculate_ktmi,
)
from strategies.direction_filter import DirectionMode
from strategies.ktmi_strategy import (
    KTMIEntryConfig,
    KTMIEntryDecision,
    evaluate_ktmi_entry,
)


@dataclass(frozen=True)
class StrategyEngineConfig:
    """Complete configuration for the current strategy engine."""

    ktmi_config: KTMIConfig = KTMIConfig()

    entry_config: KTMIEntryConfig = KTMIEntryConfig()

    direction_mode: DirectionMode = DirectionMode.BOTH

    def __post_init__(self) -> None:
        if (
            self.entry_config.direction_mode
            != self.direction_mode
        ):
            object.__setattr__(
                self,
                "entry_config",
                KTMIEntryConfig(
                    require_bullish_confluence=(
                        self.entry_config
                        .require_bullish_confluence
                    ),
                    require_bearish_confluence=(
                        self.entry_config
                        .require_bearish_confluence
                    ),
                    allow_module_signals=(
                        self.entry_config
                        .allow_module_signals
                    ),
                    allow_confluence_signals=(
                        self.entry_config
                        .allow_confluence_signals
                    ),
                    direction_mode=self.direction_mode,
                ),
            )


@dataclass(frozen=True)
class StrategyEngineResult:
    """Complete result for one input bar."""

    ktmi: KTMIResult

    signals: KTMISignalResult

    decision: KTMIEntryDecision


def evaluate_bar(
    bars: list[OHLCData],
    config: StrategyEngineConfig,
) -> StrategyEngineResult:
    """
    Evaluate the latest bar in a historical OHLC sequence.

    The complete sequence is supplied because indicators such as
    TRIX and their moving averages require historical context.
    """

    if not bars:
        raise ValueError(
            "At least one OHLC bar is required."
        )

    ktmi_results = calculate_ktmi(
        bars,
        config.ktmi_config,
    )

    if not ktmi_results:
        raise RuntimeError(
            "KTMI calculation returned no results."
        )

    signal_results = calculate_signals(
        ktmi_results,
        config.ktmi_config,
    )

    if not signal_results:
        raise RuntimeError(
            "KTMI signal calculation returned no results."
        )

    latest_ktmi = ktmi_results[-1]

    latest_signals = signal_results[-1]

    decision = evaluate_ktmi_entry(
        latest_signals,
        config.entry_config,
        config.ktmi_config,
    )

    return StrategyEngineResult(
        ktmi=latest_ktmi,
        signals=latest_signals,
        decision=decision,
    )


def evaluate_series(
    bars: list[OHLCData],
    config: StrategyEngineConfig,
) -> list[StrategyEngineResult]:
    """
    Evaluate the complete OHLC sequence.

    Each result corresponds to one input bar.

    This is the interface that will later be used by
    the backtesting engine.
    """

    if not bars:
        return []

    ktmi_results = calculate_ktmi(
        bars,
        config.ktmi_config,
    )

    signal_results = calculate_signals(
        ktmi_results,
        config.ktmi_config,
    )

    results: list[StrategyEngineResult] = []

    for ktmi_result, signal_result in zip(
        ktmi_results,
        signal_results,
    ):

        decision = evaluate_ktmi_entry(
            signal_result,
            config.entry_config,
            config.ktmi_config,
        )

        results.append(
            StrategyEngineResult(
                ktmi=ktmi_result,
                signals=signal_result,
                decision=decision,
            )
        )

    return results


__all__ = [
    "StrategyEngineConfig",
    "StrategyEngineResult",
    "evaluate_bar",
    "evaluate_series",
]