"""
KTMI Universal calculation engine.

This module implements the calculation logic of KTMI Universal V1
from the authoritative Pine Script source.

Important:
- Indicator calculations only.
- No strategy rules.
- No risk management.
- No manual directional bias.
- No market-session filtering.
- Short Momentum is inverted only after its core calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor, isnan
from typing import Iterable, Optional, Sequence

from .config import KTMIConfig, MomentumConfig


@dataclass(frozen=True)
class OHLCData:
    """Single OHLC bar."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class KTMIModuleResult:
    """Calculated values for one KTMI momentum module."""

    speed_raw: Optional[float]
    signal_raw: Optional[float]
    speed: Optional[float]
    signal: Optional[float]


@dataclass(frozen=True)
class KTMIResult:
    """Complete KTMI result for one bar."""

    momentum: KTMIModuleResult
    long_momentum: KTMIModuleResult
    short_momentum: KTMIModuleResult


def _is_valid(value: Optional[float]) -> bool:
    """Return True when a value is a usable finite number."""

    return value is not None and not isnan(value)


def _source_value(bar: OHLCData, source: str) -> float:
    """
    Reproduce Pine getSource().

    Supported:
        Close
        Open
        High
        Low
        HL2
        HLC3
        OHLC4
    """

    if source == "Close":
        return bar.close

    if source == "Open":
        return bar.open

    if source == "High":
        return bar.high

    if source == "Low":
        return bar.low

    if source == "HL2":
        return (bar.high + bar.low) / 2.0

    if source == "HLC3":
        return (bar.high + bar.low + bar.close) / 3.0

    if source == "OHLC4":
        return (
            bar.open
            + bar.high
            + bar.low
            + bar.close
        ) / 4.0

    raise ValueError(f"Unsupported source: {source}")


def _sma(values: Sequence[Optional[float]], length: int) -> Optional[float]:
    """Pine-compatible simple moving average for the current bar."""

    if length < 1:
        raise ValueError("length must be >= 1")

    if len(values) < length:
        return None

    window = values[-length:]

    if any(not _is_valid(value) for value in window):
        return None

    return sum(float(value) for value in window) / length


def _wma(values: Sequence[Optional[float]], length: int) -> Optional[float]:
    """Weighted moving average."""

    if length < 1:
        raise ValueError("length must be >= 1")

    if len(values) < length:
        return None

    window = values[-length:]

    if any(not _is_valid(value) for value in window):
        return None

    denominator = length * (length + 1) / 2.0

    return sum(
        float(value) * weight
        for value, weight in zip(window, range(1, length + 1))
    ) / denominator


def _ema_series(
    values: Sequence[Optional[float]],
    length: int,
) -> list[Optional[float]]:
    """
    Calculate an EMA series.

    Pine ta.ema uses an EMA initialized from available valid history.
    For our historical vector calculation, the first valid SMA window
    is used as the seed.
    """

    if length < 1:
        raise ValueError("length must be >= 1")

    result: list[Optional[float]] = [None] * len(values)

    valid_start = None

    for index in range(len(values)):
        if index + 1 >= length:
            window = values[index + 1 - length : index + 1]

            if all(_is_valid(value) for value in window):
                valid_start = index
                result[index] = sum(
                    float(value) for value in window
                ) / length
                break

    if valid_start is None:
        return result

    alpha = 2.0 / (length + 1.0)

    for index in range(valid_start + 1, len(values)):
        current = values[index]

        if not _is_valid(current):
            result[index] = None
            continue

        previous = result[index - 1]

        if previous is None:
            result[index] = None
        else:
            result[index] = (
                alpha * float(current)
                + (1.0 - alpha) * previous
            )

    return result


def _rma_series(
    values: Sequence[Optional[float]],
    length: int,
) -> list[Optional[float]]:
    """
    Wilder's moving average, matching Pine ta.rma behavior.

    RMA alpha = 1 / length.
    """

    if length < 1:
        raise ValueError("length must be >= 1")

    result: list[Optional[float]] = [None] * len(values)

    seed_index = None

    for index in range(len(values)):
        if index + 1 >= length:
            window = values[index + 1 - length : index + 1]

            if all(_is_valid(value) for value in window):
                seed_index = index
                result[index] = sum(
                    float(value) for value in window
                ) / length
                break

    if seed_index is None:
        return result

    alpha = 1.0 / length

    for index in range(seed_index + 1, len(values)):
        current = values[index]

        if not _is_valid(current):
            result[index] = None
            continue

        previous = result[index - 1]

        if previous is None:
            result[index] = None
        else:
            result[index] = (
                alpha * float(current)
                + (1.0 - alpha) * previous
            )

    return result


def _hma_series(
    values: Sequence[Optional[float]],
    length: int,
) -> list[Optional[float]]:
    """
    Hull moving average.

    HMA(length) =
        WMA(2 * WMA(source, length/2) - WMA(source, length),
            sqrt(length))
    """

    if length < 1:
        raise ValueError("length must be >= 1")

    half_length = max(1, length // 2)
    sqrt_length = max(1, int(floor(length ** 0.5)))

    wma_half = [
        _wma(values[: index + 1], half_length)
        for index in range(len(values))
    ]

    wma_full = [
        _wma(values[: index + 1], length)
        for index in range(len(values))
    ]

    difference: list[Optional[float]] = []

    for half, full in zip(wma_half, wma_full):
        if half is None or full is None:
            difference.append(None)
        else:
            difference.append(2.0 * half - full)

    return [
        _wma(difference[: index + 1], sqrt_length)
        for index in range(len(values))
    ]


def _ma_series(
    values: Sequence[Optional[float]],
    length: int,
    ma_type: str,
) -> list[Optional[float]]:
    """Reproduce KTMI getMA()."""

    if ma_type == "SMA":
        return [
            _sma(values[: index + 1], length)
            for index in range(len(values))
        ]

    if ma_type == "EMA":
        return _ema_series(values, length)

    if ma_type == "WMA":
        return [
            _wma(values[: index + 1], length)
            for index in range(len(values))
        ]

    if ma_type == "RMA":
        return _rma_series(values, length)

    if ma_type == "HMA":
        return _hma_series(values, length)

    raise ValueError(f"Unsupported smoothing type: {ma_type}")


def _roc_series(
    source: Sequence[Optional[float]],
    length: int,
) -> list[Optional[float]]:
    """KTMI ROC calculation."""

    result: list[Optional[float]] = [None] * len(source)

    for index in range(len(source)):
        previous_index = index - length

        if previous_index < 0:
            continue

        current = source[index]
        previous = source[previous_index]

        if (
            current is None
            or previous is None
            or previous == 0
        ):
            continue

        result[index] = (
            100.0
            * (float(current) - float(previous))
            / float(previous)
        )

    return result


def _trix_series(
    source: Sequence[Optional[float]],
    length: int,
    smoothing: str,
) -> list[Optional[float]]:
    """KTMI TRIX calculation."""

    e1 = _ma_series(source, length, smoothing)
    e2 = _ma_series(e1, length, smoothing)
    e3 = _ma_series(e2, length, smoothing)

    result: list[Optional[float]] = [None] * len(source)

    for index in range(len(source)):
        if index < 1:
            continue

        current = e3[index]
        previous = e3[index - 1]

        if (
            current is None
            or previous is None
            or previous == 0
        ):
            continue

        result[index] = (
            100.0
            * (float(current) - float(previous))
            / float(previous)
        )

    return result


def _macd_series(
    source: Sequence[Optional[float]],
    length: int,
    smoothing: str,
) -> list[Optional[float]]:
    """KTMI percentage MACD calculation."""

    fast_ma = _ma_series(source, length, smoothing)
    slow_ma = _ma_series(source, length * 2, smoothing)

    result: list[Optional[float]] = [None] * len(source)

    for index in range(len(source)):
        fast = fast_ma[index]
        slow = slow_ma[index]

        if (
            fast is None
            or slow is None
            or slow == 0
        ):
            continue

        result[index] = (
            100.0
            * (float(fast) - float(slow))
            / float(slow)
        )

    return result


def _calculate_speed_series(
    source: Sequence[Optional[float]],
    config: MomentumConfig,
) -> list[Optional[float]]:
    """Calculate one module's raw Speed series."""

    if config.calculation == "ROC":
        raw = _roc_series(
            source,
            config.speed_length,
        )

        return _ma_series(
            raw,
            config.speed_length,
            config.smoothing,
        )

    if config.calculation == "TRIX":
        return _trix_series(
            source,
            config.speed_length,
            config.smoothing,
        )

    if config.calculation == "MACD":
        return _macd_series(
            source,
            config.speed_length,
            config.smoothing,
        )

    raise ValueError(
        f"Unsupported calculation method: {config.calculation}"
    )


def _calculate_module(
    source: Sequence[Optional[float]],
    config: MomentumConfig,
    display_multiplier: float,
    invert: bool = False,
) -> list[KTMIModuleResult]:
    """Calculate Speed and Signal for one KTMI module."""

    speed_raw = _calculate_speed_series(
        source,
        config,
    )

    if invert:
        speed_raw = [
            None if value is None else -value
            for value in speed_raw
        ]

    signal_raw = _ma_series(
        speed_raw,
        config.signal_length,
        config.smoothing,
    )

    result: list[KTMIModuleResult] = []

    for speed, signal in zip(speed_raw, signal_raw):
        display_speed = (
            None
            if speed is None
            else speed * display_multiplier
        )

        display_signal = (
            None
            if signal is None
            else signal * display_multiplier
        )

        result.append(
            KTMIModuleResult(
                speed_raw=speed,
                signal_raw=signal,
                speed=display_speed,
                signal=display_signal,
            )
        )

    return result


def calculate_ktmi(
    bars: Sequence[OHLCData],
    config: Optional[KTMIConfig] = None,
) -> list[KTMIResult]:
    """
    Calculate KTMI Universal for an OHLC series.

    The returned list has exactly one result per input bar.
    """

    if config is None:
        config = KTMIConfig()

    if not bars:
        return []

    momentum_source = [
        _source_value(bar, config.momentum.source)
        for bar in bars
    ]

    long_source = [
        _source_value(bar, config.long_momentum.source)
        for bar in bars
    ]

    short_source = [
        _source_value(bar, config.short_momentum.source)
        for bar in bars
    ]

    momentum_results = _calculate_module(
        momentum_source,
        config.momentum,
        config.display_multiplier,
        invert=False,
    )

    long_results = _calculate_module(
        long_source,
        config.long_momentum,
        config.display_multiplier,
        invert=False,
    )

    short_results = _calculate_module(
        short_source,
        config.short_momentum,
        config.display_multiplier,
        invert=True,
    )

    return [
        KTMIResult(
            momentum=momentum,
            long_momentum=long_momentum,
            short_momentum=short,
        )
        for momentum, long_momentum, short in zip(
            momentum_results,
            long_results,
            short_results,
        )
    ]


__all__ = [
    "OHLCData",
    "KTMIModuleResult",
    "KTMIResult",
    "calculate_ktmi",
]