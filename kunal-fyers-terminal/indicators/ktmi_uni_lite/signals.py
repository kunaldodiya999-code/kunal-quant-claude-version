"""KTMI Uni Lite values and arrows, bar by bar, exactly as the Pine script.

For each bar this returns the six lines (speed/signal x3, display scale x100)
and the six arrow booleans. Each arrow uses the Pine rule, for example
Long Momentum Buy:

    longEnable and not na(longBuyTrigger)
    and ta.crossover(longSpeed, longBuyTrigger)   # prev <= trig and now > trig
    and longSpeed > longSignal and longSpeed > 0

Values are only known when a bar has closed. Callers must pass completed bars.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from indicators.ktmi.universal import OHLCData, calculate_ktmi
from indicators.ktmi_uni_lite.config import UNI_LITE_DEFAULTS, UniLiteConfig, UniLiteModule


@dataclass(frozen=True)
class UniLiteBar:
    momentum_speed: Optional[float]
    momentum_signal: Optional[float]
    long_speed: Optional[float]
    long_signal: Optional[float]
    short_speed: Optional[float]
    short_signal: Optional[float]
    momentum_buy: bool
    momentum_sell: bool
    long_buy: bool
    long_sell: bool
    short_buy: bool
    short_sell: bool


def pine_crossover(previous: Optional[float], current: Optional[float], level: float) -> bool:
    """``ta.crossover(series, constant)``: now above, previously at or below."""
    return previous is not None and current is not None and current > level and previous <= level


def pine_crossunder(previous: Optional[float], current: Optional[float], level: float) -> bool:
    """``ta.crossunder(series, constant)``: now below, previously at or above."""
    return previous is not None and current is not None and current < level and previous >= level


def _buy(module: UniLiteModule, trigger, prev_speed, speed, signal) -> bool:
    return (
        module.enabled
        and trigger is not None
        and pine_crossover(prev_speed, speed, trigger)
        and signal is not None
        and speed > signal
        and speed > 0
    )


def _sell(module: UniLiteModule, trigger, prev_speed, speed, signal) -> bool:
    return (
        module.enabled
        and trigger is not None
        and pine_crossunder(prev_speed, speed, trigger)
        and signal is not None
        and speed < signal
        and speed < 0
    )


def calculate_uni_lite(
    bars: Sequence[OHLCData],
    config: UniLiteConfig = UNI_LITE_DEFAULTS,
) -> list[UniLiteBar]:
    """One ``UniLiteBar`` per input bar, using the full supplied history."""
    results = calculate_ktmi(list(bars), config.to_ktmi_config())
    out: list[UniLiteBar] = []
    previous = None
    for current in results:
        m, l, s = current.momentum, current.long_momentum, current.short_momentum
        pm = previous.momentum.speed if previous else None
        pl = previous.long_momentum.speed if previous else None
        ps = previous.short_momentum.speed if previous else None
        out.append(
            UniLiteBar(
                momentum_speed=m.speed,
                momentum_signal=m.signal,
                long_speed=l.speed,
                long_signal=l.signal,
                short_speed=s.speed,
                short_signal=s.signal,
                momentum_buy=_buy(config.momentum, config.momentum_buy_trigger, pm, m.speed, m.signal),
                momentum_sell=_sell(config.momentum, config.momentum_sell_trigger, pm, m.speed, m.signal),
                long_buy=_buy(config.long_momentum, config.long_buy_trigger, pl, l.speed, l.signal),
                long_sell=_sell(config.long_momentum, config.long_sell_trigger, pl, l.speed, l.signal),
                short_buy=_buy(config.short_momentum, config.short_buy_trigger, ps, s.speed, s.signal),
                short_sell=_sell(config.short_momentum, config.short_sell_trigger, ps, s.speed, s.signal),
            )
        )
        previous = current
    return out


__all__ = ["UniLiteBar", "calculate_uni_lite", "pine_crossover", "pine_crossunder"]
