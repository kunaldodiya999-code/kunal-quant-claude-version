"""Causal indicator provider for Opening Breakout V2 historical runs.

Research-only. Supplies the ``IndicatorSnapshot`` that the V2 signal engine
needs for the ABOVE/BELOW_VWAP, CLOSE_ABOVE/BELOW_BB, KTMI and DMI triggers.
Without it every one of those triggers silently evaluates to False.

Causality contract
------------------
Candles are timestamped at bucket start and the V2 engine evaluates a
trigger on a *completed* candle (entry fills strictly after it). The snapshot
returned for timestamp ``T`` therefore uses candles up to and including ``T``
and never any later candle. Every series below is computed with forward-only
recursions, so the value at ``T`` is identical whether or not later candles
are present (see tests).

Warm-up
-------
Recursive indicators (KTMI, DMI/ADX) depend on history. Pass candles that
start well before the backtest window; values before enough history exists
are ``None`` so the trigger fails closed instead of using a guessed value.

VWAP
----
Session-anchored (resets each IST trading date), typical price HLC3, weighted
by volume. NSE:NIFTY50-INDEX has no traded volume; when a session's
cumulative volume is zero VWAP is ``None`` rather than a fabricated
equal-weight average. ``vwap_coverage()`` reports how often that happened.

Locked modules (KTMI calculation) are reused, not modified.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from indicators.ktmi.config import KTMIConfig
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config

IST = ZoneInfo("Asia/Kolkata")

DEFAULT_BB_LENGTH = 20
DEFAULT_BB_MULTIPLIER = 2.0


def _rma(values: Sequence[float | None], length: int) -> list[float | None]:
    """Pine ``ta.rma``: SMA seed over the first ``length`` valid values."""
    out: list[float | None] = []
    seed: list[float] = []
    previous: float | None = None
    for value in values:
        if value is None:
            out.append(previous if previous is not None else None)
            continue
        if previous is None:
            seed.append(value)
            if len(seed) == length:
                previous = sum(seed) / length
            out.append(previous)
            continue
        previous = (previous * (length - 1) + value) / length
        out.append(previous)
    return out


def session_vwap(
    candles: Sequence[Candle],
    volumes: Sequence[float],
) -> list[float | None]:
    """Session-anchored HLC3 VWAP; ``None`` while session volume is zero."""
    if len(candles) != len(volumes):
        raise ValueError("candles and volumes must have equal length")
    out: list[float | None] = []
    current_day = None
    cum_pv = 0.0
    cum_v = 0.0
    for candle, volume in zip(candles, volumes):
        day = datetime.fromtimestamp(candle.timestamp, tz=IST).date()
        if day != current_day:
            current_day = day
            cum_pv = 0.0
            cum_v = 0.0
        volume = max(float(volume or 0.0), 0.0)
        typical = (candle.high + candle.low + candle.close) / 3.0
        cum_pv += typical * volume
        cum_v += volume
        out.append(cum_pv / cum_v if cum_v > 0 else None)
    return out


def bollinger_bands(
    closes: Sequence[float],
    length: int = DEFAULT_BB_LENGTH,
    multiplier: float = DEFAULT_BB_MULTIPLIER,
) -> tuple[list[float | None], list[float | None]]:
    """TradingView ``ta.bb``: SMA basis, population standard deviation."""
    if length < 1:
        raise ValueError("length must be >= 1")
    upper: list[float | None] = []
    lower: list[float | None] = []
    for index in range(len(closes)):
        if index + 1 < length:
            upper.append(None)
            lower.append(None)
            continue
        window = closes[index + 1 - length:index + 1]
        mean = sum(window) / length
        deviation = sqrt(sum((value - mean) ** 2 for value in window) / length)
        upper.append(mean + multiplier * deviation)
        lower.append(mean - multiplier * deviation)
    return upper, lower


def dmi(
    candles: Sequence[Candle],
    di_length: int = 14,
    adx_smoothing: int = 14,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """TradingView ``ta.dmi``: returns (+DI, -DI, ADX), Wilder smoothing."""
    if di_length < 1 or adx_smoothing < 1:
        raise ValueError("DMI lengths must be >= 1")
    true_range: list[float | None] = [None]
    plus_dm: list[float | None] = [None]
    minus_dm: list[float | None] = [None]
    for previous, current in zip(candles, candles[1:]):
        up = current.high - previous.high
        down = previous.low - current.low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_range.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    smoothed_tr = _rma(true_range, di_length)
    smoothed_plus = _rma(plus_dm, di_length)
    smoothed_minus = _rma(minus_dm, di_length)

    plus_di: list[float | None] = []
    minus_di: list[float | None] = []
    dx: list[float | None] = []
    for tr, plus, minus in zip(smoothed_tr, smoothed_plus, smoothed_minus):
        if tr is None or plus is None or minus is None or tr == 0:
            plus_di.append(None)
            minus_di.append(None)
            dx.append(None)
            continue
        p = 100.0 * plus / tr
        m = 100.0 * minus / tr
        plus_di.append(p)
        minus_di.append(m)
        total = p + m
        dx.append(abs(p - m) / (total if total != 0 else 1.0))

    adx = [None if value is None else 100.0 * value for value in _rma(dx, adx_smoothing)]
    return plus_di, minus_di, adx


@dataclass(frozen=True)
class IndicatorCoverage:
    candles: int
    vwap_available: int
    bb_available: int
    dmi_available: int
    ktmi_available: int


class V2IndicatorProvider:
    """Precomputed, timestamp-indexed snapshots for ``scan_series``."""

    def __init__(
        self,
        candles: Sequence[Candle],
        *,
        config: V2Config,
        volumes: Sequence[float] | None = None,
        ktmi_config: KTMIConfig | None = None,
        bb_length: int = DEFAULT_BB_LENGTH,
        bb_multiplier: float = DEFAULT_BB_MULTIPLIER,
    ) -> None:
        ordered = sorted(candles, key=lambda item: item.timestamp)
        if len({c.timestamp for c in ordered}) != len(ordered):
            raise ValueError("duplicate candle timestamps")
        if volumes is None:
            volumes = [0.0] * len(ordered)
        elif len(volumes) != len(candles):
            raise ValueError("candles and volumes must have equal length")
        else:
            by_ts = {c.timestamp: v for c, v in zip(candles, volumes)}
            volumes = [by_ts[c.timestamp] for c in ordered]

        vwap = session_vwap(ordered, volumes)
        upper, lower = bollinger_bands([c.close for c in ordered], bb_length, bb_multiplier)
        plus_di, minus_di, adx = dmi(ordered, config.dmi_length, config.dmi_adx_smoothing)
        ktmi = calculate_ktmi(
            [OHLCData(c.open, c.high, c.low, c.close) for c in ordered],
            ktmi_config or KTMIConfig(),
        )

        self._snapshots: dict[int, IndicatorSnapshot] = {}
        for index, candle in enumerate(ordered):
            result = ktmi[index]
            self._snapshots[candle.timestamp] = IndicatorSnapshot(
                vwap=vwap[index],
                upper_bb=upper[index],
                lower_bb=lower[index],
                ktmi_buying_speed=result.long_momentum.speed,
                ktmi_selling_speed=result.short_momentum.speed,
                ktmi_momentum_speed=result.momentum.speed,
                plus_di=plus_di[index],
                minus_di=minus_di[index],
                adx=adx[index],
            )

    def __call__(self, timestamp: int, candle: Candle) -> IndicatorSnapshot:
        snapshot = self._snapshots.get(int(timestamp))
        if snapshot is None:
            # Unknown bar: fail closed rather than borrowing a neighbour.
            return IndicatorSnapshot()
        return snapshot

    def coverage(self, start_ts: int | None = None, end_ts: int | None = None) -> IndicatorCoverage:
        rows = [
            snap for ts, snap in self._snapshots.items()
            if (start_ts is None or ts >= start_ts) and (end_ts is None or ts <= end_ts)
        ]
        return IndicatorCoverage(
            candles=len(rows),
            vwap_available=sum(s.vwap is not None for s in rows),
            bb_available=sum(s.upper_bb is not None for s in rows),
            dmi_available=sum(s.adx is not None for s in rows),
            ktmi_available=sum(
                s.ktmi_momentum_speed is not None
                and s.ktmi_buying_speed is not None
                and s.ktmi_selling_speed is not None
                for s in rows
            ),
        )


def build_indicator_provider(
    candles: Sequence[Candle],
    *,
    config: V2Config,
    volumes: Sequence[float] | Mapping[int, float] | None = None,
    **kwargs,
) -> Callable[[int, Candle], IndicatorSnapshot]:
    if isinstance(volumes, Mapping):
        volumes = [float(volumes.get(c.timestamp, 0.0)) for c in candles]
    return V2IndicatorProvider(candles, config=config, volumes=volumes, **kwargs)


__all__ = [
    "IndicatorCoverage",
    "V2IndicatorProvider",
    "bollinger_bands",
    "build_indicator_provider",
    "dmi",
    "session_vwap",
]
