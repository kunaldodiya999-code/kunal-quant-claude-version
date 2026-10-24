"""Backtest of the Gap Reversal strategy on 1-minute history (stocks or indexes).

Per symbol and day: previous close = the previous session's last 1-minute close; candles of the
strategy timeframe are built from the day's minutes (with volume); every setup in the opening
window is marked with its strength; the FIRST qualifying candidate of the day is traded with the
stop at the day's extreme, for every reward:risk choice and both entry modes (break / close).
Results are in R (multiples of the risk), so stocks of any price can be pooled.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from market_data.day_quality import group_by_day
from paper_trading.trade_management import session_bars
from strategies.gap_reversal import (ENTRY_MODES, LONG_NAMES, SHORT_NAMES, GapReversalSettings, bars_from, scan_bars,
                                     simulate)

IST = ZoneInfo("Asia/Kolkata")


def _clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%H:%M")


def run_symbol(symbol: str, minutes: Sequence, s: GapReversalSettings,
               entry_modes: Iterable[str] = ENTRY_MODES) -> tuple[list[dict], list[dict]]:
    days = group_by_day([m for m in minutes if (9, 15) <= (datetime.fromtimestamp(m.timestamp, IST).hour,
                                                          datetime.fromtimestamp(m.timestamp, IST).minute) <= (15, 29)])
    order = sorted(days)
    candidates, trades = [], []
    for prev, day in zip(order, order[1:]):
        prev_close = days[prev][-1].close
        today = days[day]
        bars = bars_from(session_bars(today, s.timeframe, now=today[-1].timestamp + 60))
        mins = bars_from(today)
        found = scan_bars(symbol, prev_close, bars, s)
        for c in found:
            candidates.append({"symbol": symbol, "day": day.isoformat(), "side": c.side, "gap_pct": c.gap_pct,
                               "time": _clock(c.bar_time), "setups": c.pattern_names, "strength": c.strength,
                               "qualifies": c.qualifies, "trigger": round(c.trigger, 2),
                               **{k: v for k, v in c.parts.items() if k != "strength"}})
        first = next((c for c in found if c.qualifies), None)
        if first is None:
            continue
        for mode in entry_modes:
            side_cfg = replace(s.side(first.side), entry_mode=mode)
            variant = replace(s, short=side_cfg) if first.side == "SHORT" else replace(s, long=side_cfg)
            for rr in s.rr_choices:
                t = simulate(first, bars, mins, variant, rr=rr)
                if t is None:
                    continue
                trades.append({"symbol": symbol, "day": day.isoformat(), "side": t.side, "gap_pct": first.gap_pct,
                               "setups": first.pattern_names, "first_setup": first.patterns[0],
                               "strength": first.strength, "entry_mode": mode, "rr": rr,
                               "entry_time": _clock(t.entry_time), "entry": round(t.entry, 2), "stop": round(t.stop, 2),
                               "target": round(t.target, 2), "exit_time": _clock(t.exit_time), "exit": round(t.exit, 2),
                               "result": t.result, "risk_pct": round(t.risk / abs(t.entry) * 100, 2),
                               "r": t.r_multiple})
    return candidates, trades


def _stats(rows: list[dict]) -> dict:
    rs = [r["r"] for r in rows]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    return {"trades": len(rs), "win_rate_pct": round(100 * len(wins) / len(rs), 1) if rs else 0.0,
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (float("inf") if wins else 0.0),
            "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0, "total_r": round(sum(rs), 2),
            "targets": sum(r["result"] == "TARGET" for r in rows), "stops": sum(r["result"] == "STOP" for r in rows),
            "time_exits": sum(r["result"] == "TIME" for r in rows)}


def summarize(trades: list[dict]) -> list[dict]:
    """Rows by side x entry mode x RR, then by setup and by strength band (at the owner's default 1:2, break)."""
    out = []
    groups: dict[tuple, list] = {}
    for t in trades:
        groups.setdefault(("ALL", t["side"], t["entry_mode"], t["rr"]), []).append(t)
    for t in trades:
        if t["rr"] == 2.0 and t["entry_mode"] == "BREAK":
            names = SHORT_NAMES if t["side"] == "SHORT" else LONG_NAMES
            groups.setdefault(("SETUP: " + names.get(t["first_setup"], t["first_setup"]), t["side"], "BREAK", 2.0),
                              []).append(t)
            band = "80+" if t["strength"] >= 80 else ("70-80" if t["strength"] >= 70 else "60-70")
            groups.setdefault(("STRENGTH " + band, t["side"], "BREAK", 2.0), []).append(t)
    for (group, side, mode, rr), rows in sorted(groups.items(), key=lambda kv: (kv[0][0] != "ALL", kv[0])):
        out.append({"group": group, "side": side, "entry_mode": mode, "rr": rr, **_stats(rows)})
    return out


__all__ = ["run_symbol", "summarize"]
