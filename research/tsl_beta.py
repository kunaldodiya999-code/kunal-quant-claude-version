"""BETA trailing stops for the TSL Lab (research only, owner 25 Oct 2026: "test phase, must not interrupt the
original TSL"). Nothing here is used by the live engine, the paper desks or the dashboard forms.

R: one unit of risk in index points = the live rule's initial stop (30% of the option premium) turned into an
index move: premium ~ ``premium_pct`` of spot, ATM delta ``delta``  ->  1R = 0.30 x premium / delta.
(0.6% and 0.5: 1R ~ 0.36% of NIFTY, about 90 points at 25,000.)

  BETA_TIGHT_CHANDELIER  Chandelier (everget maths, highest/lowest close) with a wide multiplier at first (3.0 x ATR 9)
                         that tightens (1.5 x) once the trade has been +1.5R in favour; exit on a candle CLOSE beyond
                         it; the stop only tightens.
  BETA_R_LADDER          a hard stop at -1R; at +1R in favour it moves to breakeven, at +2R it locks +1R, at +3R +2R
                         ... (lock = best whole R reached - 1); exit when a 1-minute candle TOUCHES it.
  BETA_TWO_KEY           key 1: the trend trail on the index (Chandelier 9 x 1.5, candle CLOSE beyond it);
                         key 2: a lock on the option premium (estimated: ATM delta 0.5, no time decay): the R-ladder
                         plus, after +1R, at most ``giveback_pct`` of the peak premium profit given back (TOUCH).
                         Whichever key comes first closes the trade.
No look-ahead: a stop known at a candle (or minute) close protects only the following ones.
"""

from __future__ import annotations

import bisect
from datetime import datetime, time
from typing import Optional

from market_data.day_quality import group_by_day  # noqa: F401  (re-exported for callers)
from paper_trading.trade_management import bar_end, session_bars
from paper_trading.tsl_methods import chandelier

BETA_METHODS = ("BETA_TWO_KEY", "BETA_TIGHT_CHANDELIER", "BETA_R_LADDER")
BETA_LABELS = {
    "BETA_TWO_KEY": "BETA Two-key (index Chandelier 9x1.5 close + premium lock)",
    "BETA_TIGHT_CHANDELIER": "BETA Tightening Chandelier (3x ATR 9 -> 1.5x after +1.5R)",
    "BETA_R_LADDER": "BETA R-ladder (BE at 1R, lock 1R at 2R, 2R at 3R ...)",
}
DEFAULTS = {"premium_pct": 0.6, "delta": 0.5, "initial_sl_pct": 30.0, "length": 9, "start_mult": 3.0,
            "tight_mult": 1.5, "tighten_after_r": 1.5, "base_mult": 1.5, "giveback_pct": 35.0, "giveback_after_r": 1.0}


def r_points(spot: float, p: dict) -> float:
    """1R in index points (the live 30% premium stop as an index move)."""
    premium = spot * p["premium_pct"] / 100
    return premium * p["initial_sl_pct"] / 100 / p["delta"]


def _ladder_lock(best_r: float) -> float:
    """Stop in R for the best move in favour so far: -1 until +1R, then breakeven, then best whole R - 1."""
    if best_r < 1:
        return -1.0
    return float(int(best_r) - 1)


def run_beta(method: str, *, side: str, entry: float, entry_ts: int, minutes: list, bars_window: list, timeframe: int,
             cutoff: int, params: Optional[dict] = None) -> tuple[int, float, str]:
    """(exit timestamp, exit price, reason) for one trade. ``minutes`` = today's 1-minute candles from the entry minute
    up to the cutoff; ``bars_window`` = 1-minute candles of the warm-up days + today (for the TSL candles)."""
    p = {**DEFAULTS, **(params or {})}
    long = side == "LONG"
    sign = 1 if long else -1
    R = r_points(entry, p)
    bars = [b for b in session_bars([c for c in bars_window if c.timestamp < cutoff], timeframe)
            if bar_end(b.timestamp, timeframe) <= cutoff]
    ends = [bar_end(b.timestamp, timeframe) for b in bars]
    use_chandelier = method in ("BETA_TWO_KEY", "BETA_TIGHT_CHANDELIER")
    if use_chandelier:
        wide = chandelier(bars, p["length"], p["start_mult"] if method == "BETA_TIGHT_CHANDELIER" else p["base_mult"])
        tight = chandelier(bars, p["length"], p["tight_mult"]) if method == "BETA_TIGHT_CHANDELIER" else wide
    trail = None                       # index trail (key 1 / tightening Chandelier), in index points
    lock_r = -1.0                      # premium / ladder lock in R
    best_r = 0.0
    tightened = False
    done_bars = 0
    for m in minutes:
        # 1) touch exits on this minute, with the stops known before it
        if method in ("BETA_R_LADDER", "BETA_TWO_KEY"):
            level = entry + sign * lock_r * R
            if method == "BETA_TWO_KEY" and best_r >= p["giveback_after_r"]:
                give = entry + sign * best_r * R * (1 - p["giveback_pct"] / 100)
                level = max(level, give) if long else min(level, give)
            hit = (m.low <= level) if long else (m.high >= level)
            if hit:
                opened_beyond = (m.open < level) if long else (m.open > level)
                return m.timestamp, (m.open if opened_beyond else level), "PREMIUM_LOCK" \
                    if method == "BETA_TWO_KEY" else "LADDER"
        # 2) the minute is done: update the best move in favour
        best_r = max(best_r, sign * ((m.high if long else m.low) - entry) / R)
        lock_r = max(lock_r, _ladder_lock(best_r))
        # 3) TSL candles that closed with this minute: check the close, then tighten
        while done_bars < len(bars) and ends[done_bars] <= m.timestamp + 60:
            k = done_bars
            done_bars += 1
            if not use_chandelier or ends[k] <= entry_ts:
                continue
            close = bars[k].close
            if trail is not None and ((close < trail) if long else (close > trail)):
                return ends[k], close, "TSL_CLOSE"
            if method == "BETA_TIGHT_CHANDELIER" and best_r >= p["tighten_after_r"]:
                tightened = True
            series = tight if tightened else wide
            value = (series[0] if long else series[1])[k]
            if value is None:
                continue
            protective = (value < close) if long else (value > close)
            if trail is None:
                if protective:
                    trail = value
            else:
                trail = max(trail, value) if long else min(trail, value)
    last = minutes[-1] if minutes else None
    return cutoff, (last.close if last else entry), "TIME_15:10"


def run_signal_beta(signal, minutes_by_day: dict, days: list, *, method: str, timeframe: int,
                    params: Optional[dict] = None, warmup_days: int = 3, exit_at: time = time(15, 10)) -> dict | None:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
    day = datetime.fromtimestamp(signal.decision_ts, IST).date()
    if day not in minutes_by_day:
        return None
    k = days.index(day)
    window = [c for d in days[max(0, k - warmup_days):k + 1] for c in minutes_by_day[d]]
    cutoff = int(datetime.combine(day, exit_at, tzinfo=IST).timestamp())
    today = [c for c in minutes_by_day[day] if c.timestamp < cutoff]
    times = [c.timestamp for c in today]
    i = bisect.bisect_left(times, signal.decision_ts)
    if i >= len(today):
        return None
    entry_bar = today[i]
    entry = entry_bar.open
    side = "LONG" if signal.direction == "LONG" else "SHORT"
    sign = 1 if side == "LONG" else -1
    exit_ts, exit_price, reason = run_beta(method, side=side, entry=entry, entry_ts=entry_bar.timestamp,
                                           minutes=today[i:], bars_window=window, timeframe=timeframe, cutoff=cutoff,
                                           params=params)
    held = [c for c in today if entry_bar.timestamp <= c.timestamp <= exit_ts] or [entry_bar]
    mfe = max((c.high - entry) if sign > 0 else (entry - c.low) for c in held)
    points = sign * (exit_price - entry)
    return {
        "index": signal.index, "timeframe": signal.timeframe, "tsl_timeframe": timeframe, "method": method,
        "trigger": "BETA", "direction": signal.direction,
        "entry_time": datetime.fromtimestamp(entry_bar.timestamp, IST).strftime("%Y-%m-%d %H:%M"), "entry": entry,
        "exit_time": datetime.fromtimestamp(exit_ts, IST).strftime("%H:%M"), "exit": round(exit_price, 2),
        "reason": reason, "points": round(points, 2), "mfe": round(max(mfe, 0.0), 2),
        "capture_pct": round(100 * points / mfe, 1) if mfe > 0 else 0.0,
        "minutes_held": round((exit_ts - entry_bar.timestamp) / 60),
    }


__all__ = ["BETA_LABELS", "BETA_METHODS", "DEFAULTS", "r_points", "run_beta", "run_signal_beta"]
