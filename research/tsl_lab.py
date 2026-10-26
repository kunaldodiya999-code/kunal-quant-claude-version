"""TSL Lab: which trailing stop captures the most of each KTMI Uni Lite move? (research, index points)

For every KTMI Uni Lite signal on clean days (research/ktmi_accuracy.find_signals):
  entry = open of the minute after the signal candle closes (as in paper trading);
  each TSL method (tsl_methods.PRESETS, owner's numbers) trails on the SPOT chart with the
  same rules as the live engine (paper_trading.trade_management.TslTracker): stop known at a
  candle close protects the next candles, only tightens, CLOSE or TOUCH trigger;
  if no TSL exit happens, the trade closes at 15:10 (forced exit).
Results are index points; "capture %" = total points kept / total best move in favour (MFE).

Option-chart TSL needs historical option candles; it is compared live by the trading
program's TSL comparison (paper_trading/tsl_shadow_lab.py) instead.

``beta=True`` adds the BETA methods (research/tsl_beta.py: two-key, tightening Chandelier, R-ladder), marked
BETA in every table; they are research only and never used by the live engine.
"""

from __future__ import annotations

import bisect
from datetime import datetime, time, timedelta
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from market_data.day_quality import group_by_day
from paper_trading.trade_management import TradeManagementSettings, TslTracker, bar_end, session_bars
from paper_trading.tsl_methods import PRESETS
from research.trade_outcomes import option_points_estimate, stats
from research.tsl_beta import BETA_METHODS, run_signal_beta

IST = ZoneInfo("Asia/Kolkata")
WARMUP_DAYS = 3
_BARS: dict = {}            # (day, timeframe, cutoff) -> TSL candles; the same for every method of that day


def _bars_for(minutes_by_day: dict, days: list, day, timeframe: int, cutoff: int) -> list:
    key = (id(minutes_by_day), day, timeframe, cutoff)
    if key not in _BARS:
        k = days.index(day)
        window = [c for d in days[max(0, k - WARMUP_DAYS):k + 1] for c in minutes_by_day[d]]
        _BARS[key] = [b for b in session_bars([c for c in window if c.timestamp < cutoff], timeframe)
                      if bar_end(b.timestamp, timeframe) <= cutoff]
    return _BARS[key]


def run_signal(signal, minutes_by_day: dict, days: list, *, preset: str, trigger: str, timeframe: int,
               settings: TradeManagementSettings, exit_at: time = time(15, 10)) -> dict | None:
    day = datetime.fromtimestamp(signal.decision_ts, IST).date()
    if day not in minutes_by_day:
        return None
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
    s = TradeManagementSettings(**{**settings.to_dict(), "tsl_method": preset, "tsl_source": "SPOT",
                                   "tsl_trigger": trigger, "tsl_mode": "INDICATOR"})
    tracker = TslTracker(trade_id="lab", settings=s, side=side, entry_timestamp=entry_bar.timestamp,
                         entry_price=entry, timeframe=timeframe)
    bars = _bars_for(minutes_by_day, days, day, timeframe, cutoff)
    hit = tracker.on_bars(bars)
    if hit is not None and hit.timestamp <= cutoff:
        exit_ts, exit_price, reason = hit.timestamp, hit.source_price, hit.reason
    else:
        exit_ts, exit_price, reason = cutoff, today[-1].close, "TIME_15:10"
    held = [c for c in today if entry_bar.timestamp <= c.timestamp < exit_ts] or [entry_bar]
    mfe = max((c.high - entry) if sign > 0 else (entry - c.low) for c in held)
    points = sign * (exit_price - entry)
    return {
        "index": signal.index, "timeframe": signal.timeframe, "tsl_timeframe": timeframe, "method": preset,
        "trigger": trigger, "direction": signal.direction,
        "entry_time": datetime.fromtimestamp(entry_bar.timestamp, IST).strftime("%Y-%m-%d %H:%M"), "entry": entry,
        "exit_time": datetime.fromtimestamp(exit_ts, IST).strftime("%H:%M"), "exit": round(exit_price, 2),
        "reason": reason, "points": round(points, 2), "mfe": round(mfe, 2),
        "capture_pct": round(100 * points / mfe, 1) if mfe > 0 else 0.0,
        "minutes_held": round((exit_ts - entry_bar.timestamp) / 60),
    }


def run(signals: Sequence, minutes: Sequence, *, presets: Iterable[str] = tuple(PRESETS),
        triggers: Iterable[str] = ("CLOSE", "TOUCH"), tsl_timeframes: Iterable[int] | None = None,
        settings: TradeManagementSettings = TradeManagementSettings(), beta: bool = False,
        beta_params: dict | None = None, progress=None) -> tuple[list[dict], list[dict]]:
    """``progress(done, total)`` is called now and then (the PowerShell window shows it is working)."""
    by_day = group_by_day(minutes)
    days = sorted(by_day)
    trades, summary = [], []
    groups: dict[tuple, list[dict]] = {}
    _BARS.clear()
    step = max(1, len(signals) // 10)
    for n, sig in enumerate(signals, 1):
        if progress is not None and (n % step == 0 or n == len(signals)):
            progress(n, len(signals))
        for tf in (tsl_timeframes or [sig.timeframe]):
            for preset in presets:
                for trigger in triggers:
                    row = run_signal(sig, by_day, days, preset=preset, trigger=trigger, timeframe=int(tf),
                                     settings=settings)
                    if row is not None:
                        trades.append(row)
                        groups.setdefault((row["index"], row["timeframe"], row["tsl_timeframe"], preset, trigger),
                                          []).append(row)
            for method in (BETA_METHODS if beta else ()):
                row = run_signal_beta(sig, by_day, days, method=method, timeframe=int(tf), params=beta_params,
                                      warmup_days=WARMUP_DAYS)
                if row is not None:
                    trades.append(row)
                    groups.setdefault((row["index"], row["timeframe"], row["tsl_timeframe"], method, "BETA"),
                                      []).append(row)
    for (index, tf, tsl_tf, preset, trigger), rows in sorted(groups.items()):
        st = stats([r["points"] for r in rows])
        summary.append({
            "index": index, "signal_timeframe": tf, "tsl_timeframe": tsl_tf, "method": preset, "trigger": trigger,
            **st,
            # share of all the favourable movement that was kept (total points / total MFE)
            "capture_pct": round(100 * sum(r["points"] for r in rows) / max(1e-9, sum(r["mfe"] for r in rows)), 1),
            "avg_minutes_held": round(sum(r["minutes_held"] for r in rows) / len(rows), 1),
            "time_exits": sum(r["reason"].startswith("TIME") for r in rows),
            "approx_option_points": round(sum(option_points_estimate(r["points"]) for r in rows) / len(rows), 2),
        })
    _BARS.clear()
    return trades, summary


__all__ = ["WARMUP_DAYS", "run", "run_signal"]
