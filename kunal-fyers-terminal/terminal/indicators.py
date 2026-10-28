"""Indicators of the terminal: BBP_NM (the strategy), VWAP and KTMI Uni Lite (shown on the chart).

BBP_NM = "[RS][NM] Improved Linear Regression Bull and Bear Power v01" (Pine v1, owner's TradingView screenshot,
28 Oct 2026), translated line by line:

    h_value = highest(close, window)          l_value = lowest(close, window)
    h_bar = n - highestbars(close, window)    l_bar = n - lowestbars(close, window)   (n = bar index)
    f_exp_lr(height, length) = height + height / length
    bear = 0 - f_exp_lr(h_value - close, n - h_bar)
    bull = 0 + f_exp_lr(close - l_value, n - l_bar)
    direction = bull * 2 + bear * 2

``n - h_bar`` is ``highestbars`` itself: 0 or negative (bars back to the highest close). When the highest close IS the
current bar, ``height / length`` is 0 / 0 -> na (TradingView leaves that bar empty and its line style joins the
neighbours). Direction above 0 = green (bulls), below 0 = red (bears).
"""

from __future__ import annotations

from typing import Optional, Sequence

from terminal.candles import Candle, local

DEFAULT_WINDOW = 10


def _f_exp_lr(height: float, length: int) -> Optional[float]:
    if length == 0:
        return None                      # Pine: x / 0 -> na
    return height + height / length


def _bars_offset(values: Sequence[float], best) -> int:
    """highestbars / lowestbars: 0 or negative, the MOST RECENT bar holding the extreme (as Pine's loop does)."""
    target = best(values)
    for back, v in enumerate(reversed(values)):
        if v == target:
            return -back
    return 0


def bbp_nm(closes: Sequence[float], window: int = DEFAULT_WINDOW) -> list[tuple[Optional[float], Optional[float],
                                                                                   Optional[float]]]:
    """(bear, bull, direction) for every bar; None = na (not enough bars yet, or 0 / 0)."""
    out = []
    for i in range(len(closes)):
        if i + 1 < window:
            out.append((None, None, None))
            continue
        win = list(closes[i + 1 - window:i + 1])
        c = closes[i]
        bear_f = _f_exp_lr(max(win) - c, _bars_offset(win, max))
        bull_f = _f_exp_lr(c - min(win), _bars_offset(win, min))
        bear = None if bear_f is None else 0 - bear_f
        bull = None if bull_f is None else 0 + bull_f
        direction = None if bear is None or bull is None else bull * 2 + bear * 2
        out.append((bear, bull, direction))
    return out


def vwap(candles: Sequence[Candle], volumes: Sequence[float]) -> list[Optional[float]]:
    """Session VWAP of (high + low + close) / 3, restarting every day. ``volumes``: one per candle (an index has no
    volume of its own: the terminal passes the nearest FUTURES volume of the same minutes, owner rule)."""
    out, day, pv, vol = [], None, 0.0, 0.0
    for c, v in zip(candles, volumes):
        d = local(c.ts).date()
        if d != day:
            day, pv, vol = d, 0.0, 0.0
        if v and v > 0:
            pv += (c.high + c.low + c.close) / 3 * v
            vol += v
        out.append(pv / vol if vol > 0 else None)
    return out


def ktmi(candles: Sequence[Candle]):
    """KTMI Uni Lite (the locked indicator, owner's trigger rule UNI_LITE_CORE) for every candle."""
    from indicators.ktmi.universal import OHLCData
    from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
    return calculate_uni_lite([OHLCData(c.open, c.high, c.low, c.close) for c in candles], UNI_LITE_CORE)


__all__ = ["DEFAULT_WINDOW", "bbp_nm", "ktmi", "vwap"]
