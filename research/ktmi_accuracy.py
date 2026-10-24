"""How accurate are the KTMI Uni Lite arrows? (research, index points)

For each index and timeframe:
  1. KTMI Uni Lite (locked, profile UNI_LITE_CORE) runs on every candle in order.
  2. Each arrow on a CLEAN day, with its candle closing inside the entry window,
     is one signal: Long Speed cross -> LONG (BUY CALL), Short Speed -> SHORT (BUY PUT).
  3. Entry = next minute's open after the candle closes (same as the paper engine).
  4. Outcome on the real 1-minute path (research/trade_outcomes.py), for a grid of
     targets/stops, plus direction accuracy after 5 / 15 / 30 minutes.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from indicators.ktmi.universal import OHLCData
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite
from market_data.day_quality import group_by_day
from market_data.resampling import Candle, aggregate_day
from paper_trading.market_data_pipeline import bar_close_timestamp
from research.trade_outcomes import option_points_estimate, simulate, stats

IST = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class Signal:
    index: str
    timeframe: int
    direction: str
    candle_ts: int
    decision_ts: int


def signal_bars(minutes: Sequence[Candle], timeframe: int) -> list:
    if timeframe == 1:
        return list(minutes)
    return [bar for _, day in sorted(group_by_day(minutes).items())
            for bar in aggregate_day(day, timeframe) if bar.complete]


def find_signals(minutes: Sequence[Candle], *, index: str, timeframe: int, clean_days: Iterable[date],
                 entry_start: time = time(9, 30), entry_end: time = time(15, 0)) -> list[Signal]:
    clean = set(clean_days)
    bars = signal_bars(minutes, timeframe)
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    out = []
    for bar, value in zip(bars, values):
        for fired, direction in ((value.long_buy, "LONG"), (value.short_buy, "SHORT")):
            if not fired:
                continue
            decision = bar_close_timestamp(bar.timestamp, timeframe)
            local = datetime.fromtimestamp(decision, IST)
            if local.date() in clean and entry_start <= local.time() < entry_end:
                out.append(Signal(index, timeframe, direction, bar.timestamp, decision))
    return out


def evaluate(signals: Sequence[Signal], minutes: Sequence[Candle], *, targets: Sequence[float],
             stops: Sequence[float], exit_at: time = time(15, 10), horizons=(5, 15, 30)) -> dict:
    by_day = group_by_day(minutes)
    times = {day: [c.timestamp for c in bars] for day, bars in by_day.items()}
    rows, grid = [], {}
    for sig in signals:
        day = datetime.fromtimestamp(sig.decision_ts, IST).date()
        path, ts = by_day.get(day, []), times.get(day, [])
        exit_by = int(datetime.combine(day, exit_at, tzinfo=IST).timestamp())
        i = bisect.bisect_left(ts, sig.decision_ts)
        if i >= len(path):
            continue
        entry = path[i].open
        sign = 1 if sig.direction == "LONG" else -1
        row = {"index": sig.index, "timeframe": sig.timeframe, "direction": sig.direction,
               "signal_candle": datetime.fromtimestamp(sig.candle_ts, IST).strftime("%Y-%m-%d %H:%M"),
               "entry_time": datetime.fromtimestamp(path[i].timestamp, IST).strftime("%H:%M"), "entry": entry}
        for h in horizons:
            j = bisect.bisect_left(ts, path[i].timestamp + 60 * h) - 1
            row[f"move_{h}m"] = round(sign * (path[j].close - entry), 2) if j >= i and path[j].timestamp < exit_by else ""
        for target in targets:
            for stop in stops:
                out = simulate(path, decision_ts=sig.decision_ts, direction=sig.direction, target=target,
                               stop=stop, exit_by=exit_by, times=ts)
                if out is None:
                    continue
                grid.setdefault((target, stop), []).append(out.points)
                if (target, stop) == (targets[0], stops[0]):
                    row.update(result=out.result, points=round(out.points, 2), mfe=round(out.mfe, 1),
                               mae=round(out.mae, 1))
        rows.append(row)
    summary = []
    for (target, stop), pts in sorted(grid.items()):
        s = stats(pts)
        s.update(target=target, stop=stop,
                 approx_option_points=round(sum(option_points_estimate(p) for p in pts) / len(pts), 2))
        summary.append(s)
    direction = {}
    for h in horizons:
        moves = [r[f"move_{h}m"] for r in rows if r.get(f"move_{h}m") != ""]
        direction[f"{h}m"] = round(100 * sum(m > 0 for m in moves) / len(moves), 1) if moves else None
    return {"signals": rows, "grid": summary, "direction_accuracy_pct": direction}


__all__ = ["Signal", "evaluate", "find_signals", "signal_bars"]
