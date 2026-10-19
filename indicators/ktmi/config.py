"""KTMI Universal configuration.

This module contains indicator configuration only.
Strategy rules, risk rules, and directional filters do not belong here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


DISPLAY_MULTIPLIER = 100.0

SOURCE_OPTIONS = (
    "Close",
    "Open",
    "High",
    "Low",
    "HL2",
    "HLC3",
    "OHLC4",
)

SMOOTHING_OPTIONS = (
    "EMA",
    "SMA",
    "WMA",
    "RMA",
    "HMA",
)

CALCULATION_OPTIONS = (
    "ROC",
    "TRIX",
    "MACD",
)


@dataclass(frozen=True)
class MomentumConfig:
    """Configuration for one KTMI momentum module."""

    source: str = "Close"
    speed_length: int = 5
    signal_length: int = 9
    smoothing: str = "EMA"
    enabled: bool = False
    calculation: str = "TRIX"

    def __post_init__(self) -> None:
        if self.source not in SOURCE_OPTIONS:
            raise ValueError(
                f"Invalid source '{self.source}'. "
                f"Expected one of {SOURCE_OPTIONS}."
            )

        if self.smoothing not in SMOOTHING_OPTIONS:
            raise ValueError(
                f"Invalid smoothing '{self.smoothing}'. "
                f"Expected one of {SMOOTHING_OPTIONS}."
            )

        if self.calculation not in CALCULATION_OPTIONS:
            raise ValueError(
                f"Invalid calculation '{self.calculation}'. "
                f"Expected one of {CALCULATION_OPTIONS}."
            )

        if self.speed_length < 1:
            raise ValueError("speed_length must be >= 1.")

        if self.signal_length < 1:
            raise ValueError("signal_length must be >= 1.")


@dataclass(frozen=True)
class KTMIConfig:
    """Complete configuration for KTMI Universal."""

    momentum: MomentumConfig = MomentumConfig()

    long_momentum: MomentumConfig = MomentumConfig(
        enabled=False
    )

    short_momentum: MomentumConfig = MomentumConfig(
        source="Low",
        enabled=True
    )

    # None reproduces the Pine trigger-box behavior:
    # empty = trigger disabled.
    momentum_buy_trigger: Optional[float] = None
    momentum_sell_trigger: Optional[float] = None

    long_buy_trigger: Optional[float] = None
    long_sell_trigger: Optional[float] = None

    short_buy_trigger: Optional[float] = None
    short_sell_trigger: Optional[float] = None

    display_multiplier: float = DISPLAY_MULTIPLIER

    def __post_init__(self) -> None:
        if self.display_multiplier <= 0:
            raise ValueError("display_multiplier must be > 0.")


DEFAULT_KTMI_CONFIG = KTMIConfig()


__all__ = [
    "CALCULATION_OPTIONS",
    "DEFAULT_KTMI_CONFIG",
    "DISPLAY_MULTIPLIER",
    "KTMIConfig",
    "MomentumConfig",
    "SMOOTHING_OPTIONS",
    "SOURCE_OPTIONS",
]