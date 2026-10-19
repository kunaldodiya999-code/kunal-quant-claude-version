"""
Kunal Quant strategy configuration.

This module defines the configuration contract for a strategy.

It does not calculate indicators, generate signals, manage risk,
or execute trades.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from indicators.ktmi.config import KTMIConfig
from strategies.direction_filter import DirectionMode
from strategies.ktmi_strategy import KTMIEntryConfig


CONFIG_VERSION = "1.0"


@dataclass(frozen=True)
class RiskConfig:
    """
    Risk configuration placeholder.

    Risk management is intentionally not implemented yet.
    """

    enabled: bool = False

    max_daily_loss: Optional[float] = None
    max_trade_loss: Optional[float] = None

    risk_per_trade_percent: Optional[float] = None


@dataclass(frozen=True)
class ExitConfig:
    """
    Exit configuration placeholder.

    Exit logic has deliberately not been locked yet.
    """

    enabled: bool = False

    stop_loss_enabled: bool = False
    target_enabled: bool = False
    trailing_stop_enabled: bool = False

    stop_loss_value: Optional[float] = None
    target_value: Optional[float] = None
    trailing_stop_value: Optional[float] = None


@dataclass(frozen=True)
class StrategyConfig:
    """
    Complete reproducible strategy configuration.

    The same configuration object can eventually be used by:
        Backtest
        Paper Trade
        Live Trade
    """

    strategy_id: str = "KTMI_V1"

    config_version: str = CONFIG_VERSION

    ktmi: KTMIConfig = KTMIConfig()

    entry: KTMIEntryConfig = KTMIEntryConfig()

    direction_mode: DirectionMode = DirectionMode.BOTH

    risk: RiskConfig = RiskConfig()

    exit: ExitConfig = ExitConfig()

    def __post_init__(self) -> None:

        if not self.strategy_id.strip():
            raise ValueError(
                "strategy_id cannot be empty."
            )

        if not self.config_version.strip():
            raise ValueError(
                "config_version cannot be empty."
            )

        # Keep the top-level direction setting synchronized
        # with the entry configuration.
        if self.entry.direction_mode != self.direction_mode:

            object.__setattr__(
                self,
                "entry",
                KTMIEntryConfig(
                    require_bullish_confluence=(
                        self.entry
                        .require_bullish_confluence
                    ),
                    require_bearish_confluence=(
                        self.entry
                        .require_bearish_confluence
                    ),
                    allow_module_signals=(
                        self.entry
                        .allow_module_signals
                    ),
                    allow_confluence_signals=(
                        self.entry
                        .allow_confluence_signals
                    ),
                    direction_mode=self.direction_mode,
                ),
            )


DEFAULT_STRATEGY_CONFIG = StrategyConfig()


__all__ = [
    "CONFIG_VERSION",
    "DEFAULT_STRATEGY_CONFIG",
    "ExitConfig",
    "RiskConfig",
    "StrategyConfig",
]