"""Backtest the Opening Scalp on clean days (index points; option points estimated).

One trade per index per day. Entry at the open of the first candle after the
decision; exits by research/trade_outcomes.simulate (stop first if a candle
touches both). Includes a walk-forward check: choose on the first half of the
days, then test on the unseen second half.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from itertools import product
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from market_data.day_quality import group_by_day
from market_data.resampling import Candle
from research.trade_outcomes import option_points_estimate, simulate, stats
from strategies.opening_scalp import OpeningScalpConfig, opening_scalp_signal

IST = ZoneInfo("Asia/Kolkata")


def run_days(days: dict, config: OpeningScalpConfig, *, bar_seconds: int = 60, index: str = "") -> list[dict]:
    trades = []
    for day, bars in sorted(days.items()):
        bars = sorted(bars, key=lambda c: c.timestamp)
        signal = opening_scalp_signal(bars, config, bar_seconds=bar_seconds)
        if signal is None:
            continue
        exit_by = int(datetime.combine(day, config.exit_by, tzinfo=IST).timestamp())
        out = simulate(bars, decision_ts=signal.decision_ts, direction=signal.direction,
                       target=signal.target_points, stop=signal.stop_points, exit_by=exit_by,
                       breakeven_after=config.breakeven_after)
        if out is None:
            continue
        trades.append({
            "index": index, "day": day.isoformat(), "direction": signal.direction, "reason": signal.reason,
            "entry_time": datetime.fromtimestamp(out.entry_ts, IST).strftime("%H:%M"), "entry": out.entry,
            "exit_time": datetime.fromtimestamp(out.exit_ts, IST).strftime("%H:%M"), "exit": out.exit,
            "result": out.result, "points": round(out.points, 2), "stop": round(signal.stop_points, 1),
            "target": round(signal.target_points, 1), "mfe": round(out.mfe, 1), "mae": round(out.mae, 1),
            "approx_option_points": round(option_points_estimate(out.points), 2),
        })
    return trades


def summarize(trades: Sequence[dict], scale_by_index: dict | None = None) -> dict:
    """Stats in NIFTY-equivalent points so indexes can be pooled."""
    scale_by_index = scale_by_index or {}
    pts = [t["points"] / scale_by_index.get(t["index"], 1.0) for t in trades]
    s = stats(pts)
    s["approx_option_points_per_trade"] = round(
        sum(option_points_estimate(p) for p in pts) / len(pts), 2) if pts else 0.0
    return s


GRID = {
    "mode": ("ORB_CLOSE", "DRIVE", "FADE"),
    "range_minutes": (3, 5, 10),
    "target_points": (30.0, 40.0, 50.0),
    "max_stop": (15.0, 20.0, 25.0),
    "breakeven_after": (None, 20.0),
}


def grid_search(series: dict[str, dict], scales: dict[str, float], *, bar_seconds: int = 60,
                base: OpeningScalpConfig = OpeningScalpConfig(), grid: dict = GRID) -> list[dict]:
    """Every combination on every index (pooled, NIFTY-equivalent points)."""
    keys = list(grid)
    results = []
    for values in product(*(grid[k] for k in keys)):
        config = replace(base, **dict(zip(keys, values)))
        if config.range_minutes * 60 < bar_seconds:
            continue
        trades = []
        for index, days in series.items():
            trades += run_days(days, config.scaled(scales[index]), bar_seconds=bar_seconds, index=index)
        row = dict(zip(keys, values))
        row.update(summarize(trades, scales))
        results.append(row)
    return sorted(results, key=lambda r: (r["profit_factor"], r["trades"]), reverse=True)


def walk_forward(series: dict[str, dict], scales: dict[str, float], *, bar_seconds: int = 60,
                 min_trades: int = 10) -> dict:
    """Pick the best setting on the first half of the days, report it on the second half."""
    first, second = {}, {}
    for index, days in series.items():
        ordered = sorted(days)
        half = len(ordered) // 2
        first[index] = {d: days[d] for d in ordered[:half]}
        second[index] = {d: days[d] for d in ordered[half:]}
    ranked = [r for r in grid_search(first, scales, bar_seconds=bar_seconds) if r["trades"] >= min_trades]
    if not ranked:
        return {"chosen": None, "train": None, "test": None}
    best = ranked[0]
    config = replace(OpeningScalpConfig(), **{k: best[k] for k in GRID})
    test_trades = []
    for index, days in second.items():
        test_trades += run_days(days, config.scaled(scales[index]), bar_seconds=bar_seconds, index=index)
    return {"chosen": {k: best[k] for k in GRID}, "train": {k: best[k] for k in best if k not in GRID},
            "test": summarize(test_trades, scales)}


def split_days(candles: Iterable[Candle]) -> dict:
    return group_by_day(candles)


__all__ = ["GRID", "grid_search", "run_days", "split_days", "summarize", "walk_forward"]
