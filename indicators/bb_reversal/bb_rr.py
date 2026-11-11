"""Python twin of BB_Reversal_RR.pine (same rules, so backtests and the chart agree).

Bollinger Bands (SMA basis, population standard deviation like TradingView's ta.stdev), entry setups 1-4,
SHORT at the upper band / LONG at the lower band, stop = signal candle high / low (+ buffer), target 1:R,
stop to breakeven once price reaches beAt R, one trade at a time, exits checked from the candle after the entry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Sequence


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class BBSettings:
    length: int = 20
    mult: float = 2.0
    setups: tuple = (1,)                      # any of 1, 2, 3, 4
    need_colour: bool = False
    trade_short: bool = True
    trade_long: bool = True
    rr: float = 2.0
    breakeven: bool = True
    be_at: float = 1.0
    sl_buffer: float = 0.0
    target_first: bool = False                # stop and target in one candle: False = stop first (safer)


@dataclass
class Trade:
    side: str                                 # LONG / SHORT
    entry_bar: int
    entry: float
    stop: float
    target: float
    risk: float
    exit_bar: Optional[int] = None
    exit: Optional[float] = None
    why: str = ""
    r: Optional[float] = None
    be_bar: Optional[int] = None


def bands(closes: Sequence[float], length: int, mult: float) -> list:
    out = []
    for i in range(len(closes)):
        if i + 1 < length:
            out.append((None, None, None))
            continue
        w = closes[i + 1 - length:i + 1]
        m = sum(w) / length
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / length)
        out.append((m - mult * sd, m, m + mult * sd))
    return out


def signals(bars: Sequence[Bar], s: BBSettings) -> list[tuple[bool, bool]]:
    bb = bands([b.close for b in bars], s.length, s.mult)
    out = []
    for i, b in enumerate(bars):
        lo, _, up = bb[i]
        if up is None:
            out.append((False, False))
            continue
        pup = bb[i - 1][2] if i else None
        plo = bb[i - 1][0] if i else None
        pc = bars[i - 1].close if i else None
        sh = ((1 in s.setups and b.open > up and b.close > up) or (2 in s.setups and b.close > up)
              or (3 in s.setups and pup is not None and pc > pup and b.close <= up)
              or (4 in s.setups and b.high > up and b.close <= up))
        lg = ((1 in s.setups and b.open < lo and b.close < lo) or (2 in s.setups and b.close < lo)
              or (3 in s.setups and plo is not None and pc < plo and b.close >= lo)
              or (4 in s.setups and b.low < lo and b.close >= lo))
        sh = s.trade_short and sh and (not s.need_colour or b.close < b.open)
        lg = s.trade_long and lg and (not s.need_colour or b.close > b.open)
        out.append((sh, lg))
    return out


def run(bars: Sequence[Bar], s: BBSettings = BBSettings()) -> list[Trade]:
    sig = signals(bars, s)
    trades: list[Trade] = []
    t: Optional[Trade] = None
    be = False
    for i, b in enumerate(bars):
        if t is not None and i > t.entry_bar:
            d = 1 if t.side == "LONG" else -1
            hit_stop = b.low <= t.stop if d == 1 else b.high >= t.stop
            hit_tgt = b.high >= t.target if d == 1 else b.low <= t.target
            px, why = None, ""
            stop_px = min(b.open, t.stop) if d == 1 else max(b.open, t.stop)
            if hit_stop and hit_tgt:
                px, why = (t.target, "TARGET") if s.target_first else (stop_px, "BREAKEVEN" if be else "STOP")
            elif hit_stop:
                px, why = stop_px, "BREAKEVEN" if be else "STOP"
            elif hit_tgt:
                px, why = t.target, "TARGET"
            if px is not None:
                t.exit_bar, t.exit, t.why, t.r = i, px, why, (px - t.entry) * d / t.risk
                t = None
            elif s.breakeven and not be:
                level = t.entry + d * s.be_at * t.risk
                if (b.high >= level) if d == 1 else (b.low <= level):
                    be, t.stop, t.be_bar = True, t.entry, i
        if t is None:
            sh, lg = sig[i]
            if sh != lg:
                if sh:
                    stop = b.high + s.sl_buffer
                    risk = stop - b.close
                    if risk > 0:
                        t = Trade("SHORT", i, b.close, stop, b.close - s.rr * risk, risk)
                else:
                    stop = b.low - s.sl_buffer
                    risk = b.close - stop
                    if risk > 0:
                        t = Trade("LONG", i, b.close, stop, b.close + s.rr * risk, risk)
                if t is not None:
                    trades.append(t)
                    be = False
    return trades


__all__ = ["BBSettings", "Bar", "Trade", "bands", "run", "signals"]
