"""
KAMA Trend Follower calculation engine.

Based on the supplied TradingView
"Kama Trend Follower v1.0" Pine Script.

The core calculations are kept separate from
trade-entry and trade-exit decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from indicators.kama_trend_follower.config import (
    DEFAULT_KAMA_CONFIG,
    KAMAConfig,
)


# ---------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class KAMABar:
    """One OHLC bar."""

    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class KAMAResult:
    """KAMA Trend Follower result for one bar."""

    kama: Optional[float]

    kama_direction: int

    kama_percentage_change: Optional[float]

    kama_bull: bool

    kama_bear: bool

    kama_sideways: bool

    ma50: Optional[float]

    ma100: Optional[float]

    ma200: Optional[float]


# ---------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------


def _source_value(
    bar: KAMABar,
    source: str,
) -> float:
    """Return the selected OHLC source."""

    if source == "Close":
        return bar.close

    if source == "Open":
        return bar.open

    if source == "High":
        return bar.high

    if source == "Low":
        return bar.low

    if source == "HL2":
        return (
            bar.high + bar.low
        ) / 2.0

    if source == "HLC3":
        return (
            bar.high
            + bar.low
            + bar.close
        ) / 3.0

    if source == "OHLC4":
        return (
            bar.open
            + bar.high
            + bar.low
            + bar.close
        ) / 4.0

    raise ValueError(
        f"Unsupported source '{source}'."
    )


# ---------------------------------------------------------------------
# Pine-style helpers
# ---------------------------------------------------------------------


def _nz(
    value: Optional[float],
    replacement: float = 0.0,
) -> float:
    """Pine-style nz()."""

    if value is None:
        return replacement

    return value


def _pine_sum(
    values: Sequence[Optional[float]],
    length: int,
    index: int,
) -> Optional[float]:
    """
    Pine-style rolling sum.

    Returns None until enough historical observations
    are available.
    """

    if index < length - 1:
        return None

    total = 0.0

    for position in range(
        index - length + 1,
        index + 1,
    ):

        value = values[position]

        if value is None:
            return None

        total += value

    return total


# ---------------------------------------------------------------------
# KAMA
# ---------------------------------------------------------------------


def calculate_kama_series(
    source: Sequence[float],
    length: int,
) -> list[Optional[float]]:
    """
    Calculate KAMA using the supplied Pine formula.

    Pine source:

        kama = 0.0

        kama := nz(kama[1])
            + pow(
                iff(
                    sum(
                        abs(src - src[1]),
                        len
                    ) != 0,
                    abs(src - src[len])
                    /
                    sum(
                        abs(src - src[1]),
                        len
                    ),
                    0
                )
                * (0.666 - 0.0645)
                + 0.0645,
                2
            )
            * (
                src
                - nz(kama[1])
            )
    """

    result: list[Optional[float]] = []

    changes: list[Optional[float]] = []

    for index, value in enumerate(source):

        if index == 0:

            changes.append(None)

        else:

            changes.append(
                abs(
                    value
                    - source[index - 1]
                )
            )

    previous_kama = 0.0

    for index, value in enumerate(source):

        rolling_sum = _pine_sum(
            changes,
            length,
            index,
        )

        if (
            rolling_sum is None
            or index < length
        ):

            efficiency_ratio = 0.0

        elif rolling_sum != 0:

            efficiency_ratio = (
                abs(
                    value
                    - source[index - length]
                )
                / rolling_sum
            )

        else:

            efficiency_ratio = 0.0

        smoothing_constant = (
            efficiency_ratio
            * (
                0.666
                - 0.0645
            )
            + 0.0645
        ) ** 2

        current_kama = (
            previous_kama
            + smoothing_constant
            * (
                value
                - previous_kama
            )
        )

        result.append(
            current_kama
        )

        previous_kama = current_kama

    return result


# ---------------------------------------------------------------------
# Laguerre
# ---------------------------------------------------------------------


def calculate_laguerre_series(
    source: Sequence[Optional[float]],
    gamma: float,
) -> list[Optional[float]]:
    """
    Calculate the Laguerre smoothing used by the Pine source.

    Pine source:

        l0 := (1 - g) * s + g * nz(l0[1])
        l1 := -g * l0 + nz(l0[1]) + g * nz(l1[1])
        l2 := -g * l1 + nz(l1[1]) + g * nz(l2[1])
        l3 := -g * l2 + nz(l2[1]) + g * nz(l3[1])

        (l0 + 2*l1 + 2*l2 + l3) / 6
    """

    result: list[Optional[float]] = []

    previous_l0 = 0.0
    previous_l1 = 0.0
    previous_l2 = 0.0
    previous_l3 = 0.0

    for value in source:

        if value is None:

            result.append(None)

            continue

        l0 = (
            (1.0 - gamma)
            * value
            + gamma
            * previous_l0
        )

        l1 = (
            -gamma * l0
            + previous_l0
            + gamma * previous_l1
        )

        l2 = (
            -gamma * l1
            + previous_l1
            + gamma * previous_l2
        )

        l3 = (
            -gamma * l2
            + previous_l2
            + gamma * previous_l3
        )

        output = (
            l0
            + 2.0 * l1
            + 2.0 * l2
            + l3
        ) / 6.0

        result.append(output)

        previous_l0 = l0
        previous_l1 = l1
        previous_l2 = l2
        previous_l3 = l3

    return result


# ---------------------------------------------------------------------
# Percentage change
# ---------------------------------------------------------------------


def calculate_percentage_change(
    old: Optional[float],
    new: Optional[float],
) -> Optional[float]:
    """Calculate percentage change."""

    if old is None or new is None:
        return None

    if old == 0:
        return None

    return (
        (new - old)
        / old
    ) * 100.0


# ---------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------


def calculate_ema_series(
    source: Sequence[float],
    length: int,
) -> list[float]:

    if not source:
        return []

    alpha = 2.0 / (
        length + 1.0
    )

    result: list[float] = []

    previous = source[0]

    result.append(previous)

    for value in source[1:]:

        current = (
            alpha * value
            + (1.0 - alpha)
            * previous
        )

        result.append(current)

        previous = current

    return result


# ---------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------


def calculate_kama_trend(
    bars: Sequence[KAMABar],
    config: KAMAConfig = DEFAULT_KAMA_CONFIG,
) -> list[KAMAResult]:
    """
    Calculate the complete KAMA Trend Follower series.
    """

    if not bars:
        return []

    trend_source = [
        _source_value(
            bar,
            config.trend_source,
        )
        for bar in bars
    ]

    kama_raw = calculate_kama_series(
        trend_source,
        config.trend_length,
    )

    if config.trend_smooth:

        kama_final = calculate_laguerre_series(
            kama_raw,
            config.trend_gamma,
        )

    else:

        kama_final = kama_raw

    ma50_source = [
        _source_value(
            bar,
            config.ma50_source,
        )
        for bar in bars
    ]

    ma100_source = [
        _source_value(
            bar,
            config.ma100_source,
        )
        for bar in bars
    ]

    ma200_source = [
        _source_value(
            bar,
            config.ma200_source,
        )
        for bar in bars
    ]

    ma50 = calculate_ema_series(
        ma50_source,
        config.ma50_length,
    )

    ma100 = calculate_ema_series(
        ma100_source,
        config.ma100_length,
    )

    ma200 = calculate_ema_series(
        ma200_source,
        config.ma200_length,
    )

    results: list[KAMAResult] = []

    previous_kama = None

    previous_direction = 1

    for index, kama in enumerate(
        kama_final
    ):

        # ---------------------------------------------------------
        # KAMA direction
        #
        # Pine:
        #
        # rising(kama_final, 2) ? 1 :
        # falling(kama_final, 2) ? -1 :
        # nz(kama_dir[1], 1)
        # ---------------------------------------------------------

        direction = previous_direction

        if index >= 2:

            current = kama_final[index]

            previous_two = kama_final[
                index - 2
            ]

            if (
                current is not None
                and previous_two is not None
            ):

                if current > previous_two:

                    direction = 1

                elif current < previous_two:

                    direction = -1

        # ---------------------------------------------------------
        # Percentage change
        #
        # Pine:
        #
        # calc_perc(
        #     kama_final[Trend_thre_len],
        #     kama_final
        # )
        # ---------------------------------------------------------

        percentage_change = None

        threshold_index = (
            index
            - config.trend_threshold_length
        )

        if threshold_index >= 0:

            percentage_change = (
                calculate_percentage_change(
                    kama_final[
                        threshold_index
                    ],
                    kama,
                )
            )

        # ---------------------------------------------------------
        # Trend classification
        # ---------------------------------------------------------

        kama_bull = False
        kama_bear = False
        kama_sideways = False

        if (
            direction > 0
            and percentage_change is not None
            and percentage_change
            >= config.trend_threshold_percentage
        ):

            kama_bull = True

        elif (
            direction < 0
            and percentage_change is not None
            and percentage_change
            <= -config.trend_threshold_percentage
        ):

            kama_bear = True

        else:

            kama_sideways = True

        results.append(
            KAMAResult(
                kama=kama,
                kama_direction=direction,
                kama_percentage_change=percentage_change,
                kama_bull=kama_bull,
                kama_bear=kama_bear,
                kama_sideways=kama_sideways,
                ma50=ma50[index],
                ma100=ma100[index],
                ma200=ma200[index],
            )
        )

        previous_kama = kama
        previous_direction = direction

    return results


__all__ = [
    "KAMABar",
    "KAMAResult",
    "calculate_ema_series",
    "calculate_kama_series",
    "calculate_kama_trend",
    "calculate_laguerre_series",
    "calculate_percentage_change",
]