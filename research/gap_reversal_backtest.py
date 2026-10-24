"""Backtest of the Gap Reversal strategy on 1-minute (or 5-minute) history, stocks or indexes.

Per symbol and day: previous close = the previous session's last close; candles of the strategy
timeframe are built from the day's candles (with volume); every setup in the opening window is
marked with its strength; the FIRST qualifying candidate of the day is traded with the stop at the
day's extreme, once for every EXIT PLAN and both entry modes (break / close):

  fixed targets  1:1.5, 1:2, 1:2.5, 1:3 (settings ``rr_choices``), no TSL
  TSL only       the reward box empty, one run per TSL preset (owner's methods and numbers):
                 exit when a strategy candle CLOSES beyond the TSL, computed on the stock chart

The daily trade cap (settings) is applied across ALL symbols of a day (``apply_daily_cap``): trades in the
order they enter, the stronger first at the same minute, exactly like the live desk.

Results in R (multiples of the risk) and in rupees with ``capital_per_trade`` per entry
(quantity = capital // entry price), before and after estimated intraday charges.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Iterable, Sequence
from zoneinfo import ZoneInfo

from backtest.equity_costs import intraday_charges
from market_data.day_quality import group_by_day
from paper_trading.trade_management import session_bars
from paper_trading.tsl_methods import PRESETS, PRESET_LABELS
from strategies.exit_plan import NO_TSL, ExitPlan
from strategies.gap_reversal import (ENTRY_MODES, LONG_NAMES, SHORT_NAMES, GapReversalSettings, bars_from, daily_cap,
                                     first_entry, scan_bars, simulate)

IST = ZoneInfo("Asia/Kolkata")
CAPITAL_PER_TRADE = 50_000.0
WARMUP_DAYS = 2                  # earlier sessions the TSL warms up on (like a TradingView chart)


def _clock(ts: int) -> str:
    return datetime.fromtimestamp(ts, IST).strftime("%H:%M")


def default_exits(s: GapReversalSettings) -> list[tuple[str, ExitPlan]]:
    exits = [(f"1:{rr:g}", ExitPlan(target_rr=rr, tsl_method=NO_TSL)) for rr in s.rr_choices]
    exits += [(f"TSL {key}", ExitPlan(target_rr=None, tsl_method=key)) for key in PRESETS]
    return exits


def exit_label(label: str) -> str:
    """Plain words for a result row."""
    if label.startswith("TSL "):
        return "TSL only: " + PRESET_LABELS.get(label[4:], label[4:])
    return f"Fixed target {label}"


def _session(minutes: Sequence) -> list:
    return [m for m in minutes if (9, 15) <= (datetime.fromtimestamp(m.timestamp, IST).hour,
                                              datetime.fromtimestamp(m.timestamp, IST).minute) <= (15, 29)]


def run_symbol(symbol: str, minutes: Sequence, s: GapReversalSettings, entry_modes: Iterable[str] = ENTRY_MODES,
               exits: list[tuple[str, ExitPlan]] | None = None,
               capital_per_trade: float = CAPITAL_PER_TRADE) -> tuple[list[dict], list[dict]]:
    exits = default_exits(s) if exits is None else exits
    days = group_by_day(_session(minutes))
    order = sorted(days)
    step = 60
    if len(minutes) > 1:
        step = min((b.timestamp - a.timestamp for a, b in zip(minutes, minutes[1:]) if b.timestamp > a.timestamp),
                   default=60)
    day_bars = {d: bars_from(session_bars(days[d], s.timeframe, now=days[d][-1].timestamp + step)) for d in order}
    candidates, trades = [], []
    for n, (prev, day) in enumerate(zip(order, order[1:]), 1):
        prev_close = days[prev][-1].close
        bars, mins = day_bars[day], bars_from(days[day])
        warm = [b for d in order[max(0, n - WARMUP_DAYS):n] for b in day_bars[d]]
        found = scan_bars(symbol, prev_close, bars, s)
        for c in found:
            candidates.append({"symbol": symbol, "day": day.isoformat(), "side": c.side, "gap_pct": c.gap_pct,
                               "time": _clock(c.bar_time), "setups": c.pattern_names, "strength": c.strength,
                               "qualifies": c.qualifies, "trigger": round(c.trigger, 2),
                               **{k: v for k, v in c.parts.items() if k != "strength"}})
        if not any(c.qualifies for c in found):
            continue
        for mode in entry_modes:
            variant = replace(s, short=replace(s.short, entry_mode=mode), long=replace(s.long, entry_mode=mode))
            first, _ = first_entry(found, bars, mins, variant, plan=exits[0][1], history=warm)
            if first is None:
                continue
            for label, plan in exits:
                t = simulate(first, bars, mins, variant, plan=plan, history=warm)
                if t is None:
                    continue
                qty = int(capital_per_trade // abs(t.entry))
                gross = t.points * qty
                charges = intraday_charges(t.entry, t.exit, qty, t.side)
                trades.append({"symbol": symbol, "day": day.isoformat(), "side": t.side, "gap_pct": first.gap_pct,
                               "setups": first.pattern_names, "first_setup": first.patterns[0],
                               "strength": first.strength, "entry_mode": mode, "exit": label,
                               "rr": "" if t.rr is None else t.rr, "tsl": plan.tsl_method,
                               "entry_time": _clock(t.entry_time), "entry": round(t.entry, 2), "stop": round(t.stop, 2),
                               "target": "" if t.target is None else round(t.target, 2),
                               "exit_time": _clock(t.exit_time), "exit_price": round(t.exit, 2), "result": t.result,
                               "exit_detail": t.exit_detail, "risk_pct": round(t.risk / abs(t.entry) * 100, 2),
                               "r": t.r_multiple, "best_r": t.max_favourable_r, "quantity": qty,
                               "gross_pnl": round(gross, 2), "charges": round(charges, 2),
                               "net_pnl": round(gross - charges, 2)})
    return candidates, trades


def apply_daily_cap(trades: list[dict], s: GapReversalSettings) -> list[dict]:
    """Keep, per day and per (entry mode, exit plan), only the trades the daily cap admits."""
    if not (s.max_trades_per_day or s.max_short_per_day or s.max_long_per_day):
        return list(trades)
    groups: dict[tuple, list] = {}
    for t in trades:
        groups.setdefault((t["day"], t["entry_mode"], t["exit"]), []).append(t)
    kept = []
    for rows in groups.values():
        kept += daily_cap(rows, s)[0]
    return sorted(kept, key=lambda r: (r["day"], r["entry_time"], r["symbol"], r["entry_mode"]))


def cap_study(trades: list[dict], s: GapReversalSettings, caps=(0, 1, 2, 3, 5, 10)) -> list[dict]:
    """Net result of every exit plan for several daily caps (long + short together)."""
    out = []
    for cap in caps:
        variant = replace(s, max_trades_per_day=cap, max_short_per_day=0, max_long_per_day=0)
        kept = apply_daily_cap(trades, variant)
        groups: dict[tuple, list] = {}
        for t in kept:
            groups.setdefault((t["entry_mode"], t["exit"]), []).append(t)
        for (mode, ex), rows in groups.items():
            st = _stats(rows)
            out.append({"max_trades_per_day": cap or "no limit", "entry_mode": mode, "exit": ex,
                        "exit_plan": exit_label(ex), "trades": st["trades"], "win_rate_pct": st["win_rate_pct"],
                        "net_pnl": st["net_pnl"], "avg_net_per_trade": st["avg_net_per_trade"],
                        "max_drawdown": st["max_drawdown"]})
    return out


def _max_drawdown(values: list[float]) -> float:
    peak = equity = worst = 0.0
    for v in values:
        equity += v
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 2)


def _stats(rows: list[dict]) -> dict:
    rows = sorted(rows, key=lambda r: (r["day"], r["entry_time"], r["symbol"]))
    rs = [r["r"] for r in rows]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    net = [r["net_pnl"] for r in rows]
    n = len(rs)
    return {"trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate_pct": round(100 * len(wins) / n, 1) if n else 0.0,
            "avg_win_r": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss_r": round(-sum(losses) / len(losses), 2) if losses else 0.0,
            "expectancy_r": round(sum(rs) / n, 3) if n else 0.0,
            "profit_factor": round(sum(wins) / sum(losses), 2) if losses else (float("inf") if wins else 0.0),
            "total_r": round(sum(rs), 2),
            "gross_pnl": round(sum(r["gross_pnl"] for r in rows), 2),
            "charges": round(sum(r["charges"] for r in rows), 2),
            "net_pnl": round(sum(net), 2), "avg_net_per_trade": round(sum(net) / n, 2) if n else 0.0,
            "best_trade": round(max(net), 2) if net else 0.0, "worst_trade": round(min(net), 2) if net else 0.0,
            "max_drawdown": _max_drawdown(net),
            "targets": sum(r["result"] == "TARGET" for r in rows), "stops": sum(r["result"] == "STOP" for r in rows),
            "tsl_exits": sum(r["result"] == "TSL" for r in rows), "time_exits": sum(r["result"] == "TIME" for r in rows),
            "avg_best_r": round(sum(r["best_r"] for r in rows) / n, 2) if n else 0.0}


def summarize(trades: list[dict]) -> list[dict]:
    """Rows: every side (SHORT, LONG and BOTH) x entry mode x exit plan; then, at break entry and 1:2, by setup
    and by strength band."""
    groups: dict[tuple, list] = {}
    for t in trades:
        for side in (t["side"], "BOTH"):
            groups.setdefault(("ALL", side, t["entry_mode"], t["exit"]), []).append(t)
        if t["entry_mode"] == "BREAK" and t["exit"] == "1:2":
            names = SHORT_NAMES if t["side"] == "SHORT" else LONG_NAMES
            groups.setdefault(("SETUP: " + names.get(t["first_setup"], t["first_setup"]), t["side"], "BREAK", "1:2"),
                              []).append(t)
            band = "80+" if t["strength"] >= 80 else ("70-80" if t["strength"] >= 70 else "60-70")
            groups.setdefault(("STRENGTH " + band, t["side"], "BREAK", "1:2"), []).append(t)
    exit_order = {}
    for t in trades:
        exit_order.setdefault(t["exit"], len(exit_order))
    side_order = {"BOTH": 0, "SHORT": 1, "LONG": 2}

    def key(kv):
        (group, side, mode, ex) = kv[0]
        return (group != "ALL", group, side_order.get(side, 3), mode, exit_order.get(ex, 99))

    return [{"group": g, "side": side, "entry_mode": mode, "exit": ex, "exit_plan": exit_label(ex), **_stats(rows)}
            for (g, side, mode, ex), rows in sorted(groups.items(), key=key)]


__all__ = ["CAPITAL_PER_TRADE", "apply_daily_cap", "cap_study", "default_exits", "exit_label", "run_symbol",
           "summarize"]
