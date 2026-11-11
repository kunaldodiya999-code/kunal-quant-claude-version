"""KTMI Cross over (owner, 11 Nov 2026): the Python twin of KTMI_Cross_Over.pine (same maths as the chart).

  LONG CROSS  = Long Momentum Speed crosses ABOVE Long Momentum Signal   -> BUY CALL
  SHORT CROSS = Short Momentum Speed crosses ABOVE Short Momentum Signal -> BUY PUT

Filter per side: None (the empty box) = every cross; a number = only crosses where the Speed on the crossing candle
is above it (side "Above") or below it (side "Below"). Pine: ``ta.crossover(speed, signal)`` = now above, previous
candle at or below. The KTMI Uni Lite engine itself (indicators/ktmi, KTMI_Uni_Lite_FINAL.pine) is not changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite.config import UNI_LITE_DEFAULTS, UniLiteConfig
from indicators.ktmi_uni_lite.signals import calculate_uni_lite

SIDES = ("Above", "Below")


@dataclass(frozen=True)
class CrossFilter:
    enabled: bool = True
    value: Optional[float] = None          # None = the empty box: every cross
    side: str = "Above"

    def __post_init__(self) -> None:
        if self.side not in SIDES:
            raise ValueError(f"side must be one of {SIDES}")

    def passes(self, speed: float) -> bool:
        if self.value is None:
            return True
        return speed > self.value if self.side == "Above" else speed < self.value


@dataclass(frozen=True)
class CrossBar:
    long_cross: bool
    short_cross: bool


def series_crossover(prev_a, prev_b, a, b) -> bool:
    """``ta.crossover(a, b)``: a above b now, at or below it on the previous candle."""
    return None not in (prev_a, prev_b, a, b) and a > b and prev_a <= prev_b


def calculate_cross_over(bars: Sequence[OHLCData], config: UniLiteConfig = UNI_LITE_DEFAULTS, *,
                         long: CrossFilter = CrossFilter(), short: CrossFilter = CrossFilter()) -> list[CrossBar]:
    lite = calculate_uni_lite(bars, config)
    out: list[CrossBar] = []
    prev = None
    for cur in lite:
        lc = sc = False
        if prev is not None:
            lc = (config.long_momentum.enabled and long.enabled
                  and series_crossover(prev.long_speed, prev.long_signal, cur.long_speed, cur.long_signal)
                  and long.passes(cur.long_speed))
            sc = (config.short_momentum.enabled and short.enabled
                  and series_crossover(prev.short_speed, prev.short_signal, cur.short_speed, cur.short_signal)
                  and short.passes(cur.short_speed))
        out.append(CrossBar(lc, sc))
        prev = cur
    return out


__all__ = ["CrossBar", "CrossFilter", "SIDES", "calculate_cross_over", "series_crossover"]
