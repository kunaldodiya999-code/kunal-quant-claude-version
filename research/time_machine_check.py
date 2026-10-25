"""Is the Time Machine right? Compare its odds (made with only the data before each trade) with what happened.

For every backtest trade (Gap Reversal or Open High Low trades CSV) the Time Machine is run at the trade's entry
with the stock's earlier sessions (no look-ahead) and the trade's own exit plan. Trades are then grouped by the
predicted win chance and by verdict, and each group's ACTUAL win rate, average R and net rupees are shown. If the
groups with higher predicted odds really did better, the odds are useful as a filter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from paper_trading.tsl_methods import PRESETS
from strategies.exit_plan import NO_TSL, ExitPlan
from strategies.time_machine import run_odds

IST = ZoneInfo("Asia/Kolkata")
BANDS = ((0, 40, "below 40%"), (40, 50, "40-50%"), (50, 60, "50-60%"), (60, 101, "60% or more"))


def plan_of(label: str) -> ExitPlan:
    """Backtest exit label ("1:2", "TSL PSAR_0.04_0.04_0.10") -> the exit plan."""
    if label.startswith("TSL "):
        key = label[4:]
        if key not in PRESETS:
            raise ValueError(label)
        return ExitPlan(target_rr=None, tsl_method=key)
    return ExitPlan(target_rr=float(label.split(":")[1]), tsl_method=NO_TSL)


def check(trades: Sequence[dict], candles_of: Callable[[str], Sequence], *, replays: int = 1000,
          exit_time: str = "15:10", progress: Callable[[int, int], None] | None = None) -> list[dict]:
    """Each trade dict: symbol, day, side, entry, stop, entry_time (HH:MM), exit, r, net_pnl. Returns the trades
    with the predicted odds added (trades without enough earlier history are left out)."""
    cache: dict = {}
    out = []
    for n, t in enumerate(trades, 1):
        if progress:
            progress(n, len(trades))
        sym = t["symbol"]
        if sym not in cache:
            cache[sym] = sorted(candles_of(sym), key=lambda c: c.timestamp)
        candles = cache[sym]
        day = datetime.fromisoformat(str(t["day"])).date()
        entry_ts = int(datetime.combine(day, datetime.strptime(t["entry_time"], "%H:%M").time(), tzinfo=IST)
                       .timestamp())
        start_of_day = int(datetime.combine(day, datetime.min.time(), tzinfo=IST).timestamp())
        history = [c for c in candles if c.timestamp < start_of_day]
        today = [c for c in candles if start_of_day <= c.timestamp <= entry_ts]
        odds = run_odds(symbol=sym, side=t["side"], entry=float(t["entry"]), stop=float(t["stop"]),
                        plan=plan_of(t["exit"]), entry_ts=entry_ts, history=history[-60 * 80:], today=today,
                        exit_time=exit_time, replays=replays)
        if odds is None:
            continue
        out.append({**t, "odds_win_pct": odds.win_pct, "odds_avg_r": odds.avg_r, "odds_verdict": odds.verdict,
                    "odds_sessions": odds.sessions})
    return out


def _group(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"trades": 0, "actual_win_pct": 0.0, "actual_avg_r": 0.0, "net_pnl": 0.0, "predicted_win_pct": 0.0}
    return {"trades": n, "predicted_win_pct": round(sum(r["odds_win_pct"] for r in rows) / n, 1),
            "actual_win_pct": round(100 * sum(float(r["r"]) > 0 for r in rows) / n, 1),
            "actual_avg_r": round(sum(float(r["r"]) for r in rows) / n, 3),
            "net_pnl": round(sum(float(r["net_pnl"]) for r in rows), 2)}


def calibration(rows: list[dict]) -> list[dict]:
    """Per exit plan: the trades grouped by predicted win chance, by verdict, and all together."""
    out = []
    for ex in dict.fromkeys(r["exit"] for r in rows):
        mine = [r for r in rows if r["exit"] == ex]
        out.append({"exit": ex, "group": "ALL", **_group(mine)})
        for lo, hi, name in BANDS:
            out.append({"exit": ex, "group": "predicted " + name,
                        **_group([r for r in mine if lo <= r["odds_win_pct"] < hi])})
        for v in ("GOOD", "COIN FLIP", "POOR"):
            out.append({"exit": ex, "group": "verdict " + v, **_group([r for r in mine if r["odds_verdict"] == v])})
    return out


__all__ = ["BANDS", "calibration", "check", "plan_of"]
