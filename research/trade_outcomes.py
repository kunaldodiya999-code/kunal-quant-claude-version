"""Shared, look-ahead-free trade outcome rules for research backtests.

Entry: the open of the first 1-minute candle starting at/after the decision time.
Exit: the first 1-minute candle that touches the target or the stop; if one candle
touches both, the STOP is assumed first (conservative); otherwise the time exit
(close of the last candle before ``exit_by``).
All prices are INDEX points. Option P&L is approximated separately and labelled.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Sequence

from market_data.resampling import Candle


@dataclass(frozen=True)
class Outcome:
    direction: str            # LONG / SHORT
    entry_ts: int
    entry: float
    exit_ts: int
    exit: float
    result: str               # TARGET / STOP / TIME
    points: float             # signed, in index points (+ = profit)
    mfe: float                # best move in favour (points)
    mae: float                # worst move against (points, positive number)


def simulate(path: Sequence[Candle], *, decision_ts: int, direction: str, target: float, stop: float,
             exit_by: int, times: list[int] | None = None, breakeven_after: float | None = None) -> Outcome | None:
    """Walk 1-minute candles from the decision time; ``path`` must be sorted (one day is enough).

    ``breakeven_after``: once a candle CLOSES that many points in profit, the stop moves to
    the entry price for the following candles (never on the same candle: no look-ahead).
    """
    times = times if times is not None else [c.timestamp for c in path]
    i = bisect.bisect_left(times, decision_ts)
    if i >= len(path) or path[i].timestamp >= exit_by:
        return None
    entry_bar = path[i]
    entry = entry_bar.open
    sign = 1 if direction == "LONG" else -1
    tgt = entry + sign * target
    stp = entry - sign * stop
    mfe = mae = 0.0
    last = entry_bar
    for bar in path[i:]:
        if bar.timestamp >= exit_by:
            break
        last = bar
        favour = (bar.high - entry) if sign > 0 else (entry - bar.low)
        against = (entry - bar.low) if sign > 0 else (bar.high - entry)
        mfe, mae = max(mfe, favour), max(mae, against)
        hit_stop = bar.low <= stp if sign > 0 else bar.high >= stp
        hit_target = bar.high >= tgt if sign > 0 else bar.low <= tgt
        if hit_stop:                       # same candle as target: stop first (conservative)
            fill = min(stp, bar.open) if sign > 0 else max(stp, bar.open)   # gaps fill worse
            return Outcome(direction, entry_bar.timestamp, entry, bar.timestamp, fill, "STOP",
                           sign * (fill - entry), mfe, mae)
        if hit_target:
            return Outcome(direction, entry_bar.timestamp, entry, bar.timestamp, tgt, "TARGET",
                           sign * (tgt - entry), mfe, mae)
        if breakeven_after is not None and sign * (bar.close - entry) >= breakeven_after:
            stp = entry                    # stop to cost from the next candle on (only ever tighter)
    return Outcome(direction, entry_bar.timestamp, entry, last.timestamp, last.close, "TIME",
                   sign * (last.close - entry), mfe, mae)


def stats(points: Sequence[float]) -> dict:
    wins = [p for p in points if p > 0]
    losses = [-p for p in points if p < 0]
    gross_win, gross_loss = sum(wins), sum(losses)
    n = len(points)
    return {
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 1) if n else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else (float("inf") if gross_win else 0.0),
        "avg_points": round(sum(points) / n, 2) if n else 0.0,
        "total_points": round(sum(points), 1),
        "avg_win": round(gross_win / len(wins), 1) if wins else 0.0,
        "avg_loss": round(gross_loss / len(losses), 1) if losses else 0.0,
    }


# ATM option approximation: premium moves ~0.5 x index points; minus a round-trip
# cost/spread in premium points. Labelled as an ESTIMATE everywhere it is shown.
ATM_DELTA = 0.5
ROUND_TRIP_COST_POINTS = 1.5


def option_points_estimate(index_points: float) -> float:
    return ATM_DELTA * index_points - ROUND_TRIP_COST_POINTS


__all__ = ["ATM_DELTA", "Outcome", "ROUND_TRIP_COST_POINTS", "option_points_estimate", "simulate", "stats"]
