"""
KAMA Trend Follower configuration.

Based on the supplied TradingView
"Kama Trend Follower v1.0" source.

This module contains indicator configuration only.
Exit decisions belong to strategies/exits/kama_exit.py.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KAMAConfig:
    """Configuration for KAMA Trend Follower."""

    # ---------------------------------------------------------
    # Trend / KAMA
    # ---------------------------------------------------------

    trend_show: bool = True

    trend_length: int = 8

    trend_source: str = "Close"

    trend_threshold_percentage: float = 0.5

    trend_threshold_length: int = 3

    trend_smooth: bool = True

    trend_gamma: float = 0.03

    # ---------------------------------------------------------
    # EMA 50
    # ---------------------------------------------------------

    ma50_show: bool = False

    ma50_length: int = 50

    ma50_source: str = "Close"

    # ---------------------------------------------------------
    # EMA 100
    # ---------------------------------------------------------

    ma100_show: bool = False

    ma100_length: int = 100

    ma100_source: str = "Close"

    # ---------------------------------------------------------
    # EMA 200
    # ---------------------------------------------------------

    ma200_show: bool = False

    ma200_length: int = 200

    ma200_source: str = "Close"

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    def __post_init__(self) -> None:

        valid_sources = {
            "Close",
            "Open",
            "High",
            "Low",
            "HL2",
            "HLC3",
            "OHLC4",
        }

        if self.trend_source not in valid_sources:
            raise ValueError(
                f"Invalid trend_source '{self.trend_source}'."
            )

        if self.ma50_source not in valid_sources:
            raise ValueError(
                f"Invalid ma50_source '{self.ma50_source}'."
            )

        if self.ma100_source not in valid_sources:
            raise ValueError(
                f"Invalid ma100_source '{self.ma100_source}'."
            )

        if self.ma200_source not in valid_sources:
            raise ValueError(
                f"Invalid ma200_source '{self.ma200_source}'."
            )

        if self.trend_length < 2:
            raise ValueError(
                "trend_length must be >= 2."
            )

        if self.trend_threshold_length < 1:
            raise ValueError(
                "trend_threshold_length must be >= 1."
            )

        if self.trend_threshold_percentage < 0:
            raise ValueError(
                "trend_threshold_percentage must be >= 0."
            )

        if self.trend_gamma < 0:
            raise ValueError(
                "trend_gamma must be >= 0."
            )

        if self.ma50_length < 1:
            raise ValueError(
                "ma50_length must be >= 1."
            )

        if self.ma100_length < 1:
            raise ValueError(
                "ma100_length must be >= 1."
            )

        if self.ma200_length < 1:
            raise ValueError(
                "ma200_length must be >= 1."
            )


DEFAULT_KAMA_CONFIG = KAMAConfig()


__all__ = [
    "KAMAConfig",
    "DEFAULT_KAMA_CONFIG",
]