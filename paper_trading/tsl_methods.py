"""Trailing-stop (TSL) calculations, written to match the TradingView scripts the owner uses.

Every method works on a list of COMPLETED candles (anything with open/high/low/close) and
returns one value per candle, known at that candle's close. Nothing here looks ahead.

Methods and their default settings (owner's TSL list, every value can be changed):
  CHANDELIER   Chandelier Exit by everget (TradingView public script):
               ATR length 9, multiplier 1.5, extremums from closes (script default "Use Close").
  SUPERTREND   TradingView built-in ``ta.supertrend``: ATR 5 x 1.0 (A) and ATR 7 x 1.5 (B).
  PSAR         TradingView built-in ``ta.sar``: 0.02 / 0.02 / 0.20 (A) and 0.04 / 0.04 / 0.10 (B).
  POINTS       Manual point trail (HFT document): once price is ``min_lock`` points in profit,
               the stop is ``buffer`` points below price, never below entry + ``min_lock``.

``side``: "LONG" protects a rising price (stop below price): a bought option on its own
chart, or a CALL trade on the spot chart. "SHORT" protects a falling price (stop above
price): a PUT trade on the spot chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

METHODS = ("CHANDELIER", "SUPERTREND", "PSAR", "POINTS")

# Ready-made settings: the owner's five TSL configurations plus the manual point trail.
PRESETS: dict[str, tuple[str, dict]] = {
    "CHANDELIER_9_1.5": ("CHANDELIER", {"length": 9, "mult": 1.5, "use_close": True}),
    "SUPERTREND_5_1.0": ("SUPERTREND", {"atr_length": 5, "factor": 1.0}),
    "SUPERTREND_7_1.5": ("SUPERTREND", {"atr_length": 7, "factor": 1.5}),
    "PSAR_0.02_0.02_0.20": ("PSAR", {"start": 0.02, "increment": 0.02, "maximum": 0.20}),
    "PSAR_0.04_0.04_0.10": ("PSAR", {"start": 0.04, "increment": 0.04, "maximum": 0.10}),
    "POINTS_10_15": ("POINTS", {"buffer": 10.0, "min_lock": 15.0}),
}
PRESET_LABELS = {
    "CHANDELIER_9_1.5": "Chandelier Exit (everget) - ATR 9 x 1.5",
    "SUPERTREND_5_1.0": "Supertrend A - ATR 5 x 1.0",
    "SUPERTREND_7_1.5": "Supertrend B - ATR 7 x 1.5",
    "PSAR_0.02_0.02_0.20": "Parabolic SAR A - 0.02 / 0.02 / 0.20",
    "PSAR_0.04_0.04_0.10": "Parabolic SAR B - 0.04 / 0.04 / 0.10",
    "POINTS_10_15": "Point trail - buffer 10, lock 15",
}


@dataclass(frozen=True)
class StopPoint:
    """A method's stop after one candle. ``against``: Parabolic SAR switched to the other side
    of price on THIS candle (it was protecting the trade on the previous candle). Chandelier and
    Supertrend exits come from price crossing their stop line instead."""
    stop: Optional[float]
    against: bool = False


# ---------------------------------------------------------------- building blocks

def true_range(bars: Sequence) -> list[float]:
    """``ta.tr(true)``: the first candle uses high - low."""
    out = []
    for i, b in enumerate(bars):
        if i == 0:
            out.append(b.high - b.low)
        else:
            pc = bars[i - 1].close
            out.append(max(b.high - b.low, abs(b.high - pc), abs(b.low - pc)))
    return out


def rma(values: Sequence[float], length: int) -> list[Optional[float]]:
    """``ta.rma``: first value = simple average of the first ``length`` values, then Wilder smoothing."""
    out: list[Optional[float]] = [None] * len(values)
    if length < 1:
        raise ValueError("length must be at least 1")
    prev = None
    for i, v in enumerate(values):
        if prev is None:
            if i == length - 1:
                prev = sum(values[:length]) / length
                out[i] = prev
        else:
            prev = (v + (length - 1) * prev) / length
            out[i] = prev
    return out


def atr(bars: Sequence, length: int) -> list[Optional[float]]:
    """``ta.atr(length)`` = rma(true range, length)."""
    return rma(true_range(bars), length)


# ---------------------------------------------------------------- Chandelier (everget)

def chandelier(bars: Sequence, length: int = 9, mult: float = 1.5, use_close: bool = True):
    """everget's "Chandelier Exit" (TradingView), line by line:

        atr = mult * ta.atr(length)
        longStop  = (useClose ? highest(close, length) : highest(high, length)) - atr
        longStopPrev = nz(longStop[1], longStop)
        longStop := close[1] > longStopPrev ? max(longStop, longStopPrev) : longStop
        shortStop = (useClose ? lowest(close, length) : lowest(low, length)) + atr
        shortStopPrev = nz(shortStop[1], shortStop)
        shortStop := close[1] < shortStopPrev ? min(shortStop, shortStopPrev) : shortStop
        dir := close > shortStopPrev ? 1 : close < longStopPrev ? -1 : dir

    Returns lists (long_stop, short_stop, direction), None while ATR warms up.
    """
    a = atr(bars, length)
    longs: list[Optional[float]] = []
    shorts: list[Optional[float]] = []
    dirs: list[int] = []
    direction = 1
    for i, b in enumerate(bars):
        if a[i] is None:
            longs.append(None); shorts.append(None); dirs.append(direction)
            continue
        window = bars[max(0, i - length + 1):i + 1]
        hi = max(x.close for x in window) if use_close else max(x.high for x in window)
        lo = min(x.close for x in window) if use_close else min(x.low for x in window)
        long_stop, short_stop = hi - mult * a[i], lo + mult * a[i]
        long_prev = longs[-1] if longs and longs[-1] is not None else long_stop
        short_prev = shorts[-1] if shorts and shorts[-1] is not None else short_stop
        prev_close = bars[i - 1].close if i else None
        if prev_close is not None and prev_close > long_prev:
            long_stop = max(long_stop, long_prev)
        if prev_close is not None and prev_close < short_prev:
            short_stop = min(short_stop, short_prev)
        if b.close > short_prev:
            direction = 1
        elif b.close < long_prev:
            direction = -1
        longs.append(long_stop); shorts.append(short_stop); dirs.append(direction)
    return longs, shorts, dirs


# ---------------------------------------------------------------- Supertrend (ta.supertrend)

def supertrend(bars: Sequence, atr_length: int = 5, factor: float = 1.0):
    """TradingView ``ta.supertrend(factor, atrPeriod)`` (Pine reference implementation):

        upper/lower = hl2 +/- factor * atr
        lowerBand := lowerBand > prevLower or close[1] < prevLower ? lowerBand : prevLower
        upperBand := upperBand < prevUpper or close[1] > prevUpper ? upperBand : prevUpper
        direction: 1 (down) at the first ATR bar; then if the previous supertrend was the
        upper band: close > upperBand ? -1 : 1, else close < lowerBand ? 1 : -1
        supertrend = direction == -1 ? lowerBand : upperBand      (-1 = up trend)

    Returns lists (supertrend, direction, final lower band, final upper band).
    """
    a = atr(bars, atr_length)
    st, dirs, lowers, uppers = [], [], [], []
    for i, b in enumerate(bars):
        if a[i] is None:
            st.append(None); dirs.append(None); lowers.append(None); uppers.append(None)
            continue
        mid = (b.high + b.low) / 2
        upper, lower = mid + factor * a[i], mid - factor * a[i]
        prev_lower = lowers[-1] if lowers and lowers[-1] is not None else 0.0
        prev_upper = uppers[-1] if uppers and uppers[-1] is not None else 0.0
        prev_close = bars[i - 1].close if i else b.close
        if not (lower > prev_lower or prev_close < prev_lower):
            lower = prev_lower
        if not (upper < prev_upper or prev_close > prev_upper):
            upper = prev_upper
        if i == 0 or a[i - 1] is None:
            direction = 1
        elif st[-1] == prev_upper:
            direction = -1 if b.close > upper else 1
        else:
            direction = 1 if b.close < lower else -1
        st.append(lower if direction == -1 else upper)
        dirs.append(direction); lowers.append(lower); uppers.append(upper)
    return st, dirs, lowers, uppers


# ---------------------------------------------------------------- Parabolic SAR (ta.sar)

def psar(bars: Sequence, start: float = 0.02, increment: float = 0.02, maximum: float = 0.20):
    """TradingView ``ta.sar(start, inc, max)`` (Pine reference implementation ``pine_sar``).

    Returns lists (sar, is_below) where is_below = SAR under price (up trend). Candle 0 has no SAR.
    """
    result = max_min = acceleration = None
    is_below = False
    sars: list[Optional[float]] = []
    below: list[Optional[bool]] = []
    for i, b in enumerate(bars):
        if i == 0:
            sars.append(None); below.append(None)
            continue
        first_trend_bar = False
        if i == 1:
            prev = bars[0]
            if b.close > prev.close:
                is_below, max_min, result = True, b.high, prev.low
            else:
                is_below, max_min, result = False, b.low, prev.high
            first_trend_bar = True
            acceleration = start
        result = result + acceleration * (max_min - result)
        if is_below:
            if result > b.low:
                first_trend_bar, is_below = True, False
                result = max(b.high, max_min)
                max_min, acceleration = b.low, start
        else:
            if result < b.high:
                first_trend_bar, is_below = True, True
                result = min(b.low, max_min)
                max_min, acceleration = b.high, start
        if not first_trend_bar:
            if is_below:
                if b.high > max_min:
                    max_min = b.high
                    acceleration = min(acceleration + increment, maximum)
            else:
                if b.low < max_min:
                    max_min = b.low
                    acceleration = min(acceleration + increment, maximum)
        if is_below:
            result = min(result, bars[i - 1].low)
            if i > 1:
                result = min(result, bars[i - 2].low)
        else:
            result = max(result, bars[i - 1].high)
            if i > 1:
                result = max(result, bars[i - 2].high)
        sars.append(result); below.append(is_below)
    return sars, below


# ---------------------------------------------------------------- one interface for all

def method_stops(method: str, params: dict, bars: Sequence, side: str = "LONG",
                 entry_price: float | None = None) -> list[StopPoint]:
    """The method's stop after every candle, for a trade on ``side`` (no ratchet applied here)."""
    side = side.upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("side must be LONG or SHORT")
    long = side == "LONG"
    m = method.upper()
    if m == "CHANDELIER":
        longs, shorts, dirs = chandelier(bars, int(params.get("length", 9)), float(params.get("mult", 1.5)),
                                         bool(params.get("use_close", True)))
        return [StopPoint(lo if long else sh) for lo, sh in zip(longs, shorts)]
    if m == "SUPERTREND":
        _, dirs, lowers, uppers = supertrend(bars, int(params.get("atr_length", 5)), float(params.get("factor", 1.0)))
        return [StopPoint(lo if long else up) for lo, up in zip(lowers, uppers)]
    if m == "PSAR":
        sars, below = psar(bars, float(params.get("start", 0.02)), float(params.get("increment", 0.02)),
                           float(params.get("maximum", 0.20)))
        out, protecting = [], False
        for s, bl in zip(sars, below):
            if s is None:
                out.append(StopPoint(None))
            elif bl == long:                     # SAR on the protective side: it is the stop
                out.append(StopPoint(s)); protecting = True
            else:                                # SAR on the other side: a flip if it protected before
                out.append(StopPoint(None, protecting)); protecting = False
        return out
    if m == "POINTS":
        if entry_price is None:
            raise ValueError("POINTS needs the entry price")
        buffer, lock = float(params.get("buffer", 10.0)), float(params.get("min_lock", 15.0))
        out = []
        for b in bars:
            profit = (b.close - entry_price) if long else (entry_price - b.close)
            if profit < lock:
                out.append(StopPoint(None))
            elif long:
                out.append(StopPoint(max(b.close - buffer, entry_price + lock)))
            else:
                out.append(StopPoint(min(b.close + buffer, entry_price - lock)))
        return out
    raise ValueError(f"unknown TSL method {method!r}; choose from {METHODS}")


__all__ = ["METHODS", "PRESETS", "PRESET_LABELS", "StopPoint", "atr", "chandelier", "method_stops", "psar",
           "rma", "supertrend", "true_range"]
