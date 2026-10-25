"""Time Machine: the honest odds of a trade before it is taken (idea from the MIT "day-trader-skill", rebuilt for NSE).

For one trade (side, entry, stop, the exit plan) it replays the rest of the session many times. Every
5-minute candle of a replay is drawn whole from the SAME stock's own 5-minute candles at the same time
of day (+- ``window`` candles) over its last sessions, as a move relative to the previous candle's
close, and chained from the entry price. Each replay is then run through the shared trade engine
(strategies/trade_sim.py) with the trade's real exit plan: hard stop, Reward 1:[box] or the TSL, flat
by the exit time. Result: how often the trade ended in profit, hit the target, the stop, the TSL or
the time exit, and the average result in R.

It is a simulation from the stock's recent behaviour, not a prediction: news, results and gaps can do
things those sessions never did. Same symbol + day = same seed = the same numbers.

What our check showed (research/time_machine_check.py, 25 Oct 2026, ~480 past Gap Reversal / Open High Low
trades, odds made only from the data before each trade):
* the chance of REACHING a target ranks trades correctly (higher predicted = hit more often), but is
  cautious: the real rate was about 6-15 points higher;
* the WIN chance did NOT pick winners (the "GOOD" trades did worst on Gap Reversal).
So it is shown as information (which target is realistic today), never as a trade filter.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass
from datetime import datetime, time
from statistics import median
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from strategies.exit_plan import ExitPlan
from strategies.trade_sim import manage_trade

IST = ZoneInfo("Asia/Kolkata")
OPEN = time(9, 15)
SLOT = 300                       # 5-minute candles
SLOTS = 75                       # 09:15 .. 15:25 starts


@dataclass(frozen=True)
class _Bar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Odds:
    replays: int
    sessions: int                # history sessions used
    win_pct: float               # ended in profit
    target_pct: float
    stop_pct: float
    tsl_pct: float
    time_pct: float              # still open at the exit time (closed there)
    avg_r: float
    median_r: float
    verdict: str                 # GOOD / COIN FLIP / POOR

    def text(self) -> str:
        return f"{self.win_pct:.0f}% · {self.avg_r:+.2f}R"

    def to_dict(self) -> dict:
        return {**asdict(self), "text": self.text()}


def verdict(win_pct: float, avg_r: float) -> str:
    if avg_r >= 0.15 and win_pct >= 50:
        return "GOOD"
    if avg_r <= -0.10:
        return "POOR"
    return "COIN FLIP"


def _slot(ts: int) -> int:
    t = datetime.fromtimestamp(int(ts), IST)
    return ((t.hour * 60 + t.minute) - (9 * 60 + 15)) // 5


def _five_minute(candles: Sequence) -> dict:
    """{day: {slot: bar}} of 5-minute bars (1-minute input is grouped; 5-minute input is used as it is)."""
    days: dict = {}
    for c in sorted(candles, key=lambda c: c.timestamp):
        t = datetime.fromtimestamp(int(c.timestamp), IST)
        k = _slot(c.timestamp)
        if not 0 <= k < SLOTS:
            continue
        slots = days.setdefault(t.date(), {})
        b = slots.get(k)
        if b is None:
            slots[k] = [c.open, c.high, c.low, c.close]
        else:
            b[1], b[2], b[3] = max(b[1], c.high), min(b[2], c.low), c.close
    return days


def relative_moves(history: Sequence) -> tuple[dict, int]:
    """{slot: [(open, high, low, close) / previous close, ...]} from earlier sessions, and the session count.
    The first candle of a day is measured from the previous day's last close (the opening gap)."""
    days = _five_minute(history)
    moves: dict[int, list] = {}
    prev_close = None
    used = 0
    for day in sorted(days):
        slots = days[day]
        if len(slots) < SLOTS * 0.8:                 # a broken day (missing data) is skipped
            prev_close = slots[max(slots)][3] if slots else prev_close
            continue
        used += 1
        for k in sorted(slots):
            o, h, l, c = slots[k]
            if prev_close and prev_close > 0:
                moves.setdefault(k, []).append((o / prev_close, h / prev_close, l / prev_close, c / prev_close))
            prev_close = c
    return moves, used


def run_odds(*, symbol: str, side: str, entry: float, stop: float, plan: ExitPlan, entry_ts: int,
             history: Sequence, today: Sequence = (), exit_time: str = "15:10", replays: int = 2000,
             window: int = 2, min_sessions: int = 20, seed: Optional[int] = None) -> Optional[Odds]:
    """``history`` = earlier sessions' candles (1- or 5-minute), ``today`` = today's candles up to the entry
    (only for the TSL warm-up). None when there is not enough history or the risk is zero."""
    moves, sessions = relative_moves(history)
    if sessions < min_sessions or entry <= 0 or (stop - entry) * (1 if side.upper() == "SHORT" else -1) <= 0:
        return None
    day = datetime.fromtimestamp(int(entry_ts), IST).date()
    open_ts = int(datetime.combine(day, OPEN, tzinfo=IST).timestamp())
    end_slot = min(SLOTS, _slot(int(datetime.combine(day, time.fromisoformat(exit_time), tzinfo=IST).timestamp())) + 1)
    first = max(0, (int(entry_ts) - open_ts) // SLOT + 1)            # the first candle that starts after the entry
    if first >= end_slot:
        return None
    pools = {k: [m for j in range(k - window, k + window + 1) for m in moves.get(j, [])]
             for k in range(first, end_slot)}
    if any(not p for p in pools.values()):
        return None
    before = [_Bar(int(b[0]), *b[1:]) for b in
              ((open_ts + k * SLOT, *v) for k, v in sorted(_five_minute(today).get(day, {}).items()) if k < first)]
    if seed is None:
        seed = int(hashlib.sha256(f"{symbol}|{day}|{side}".encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    results, rs = [], []
    for _ in range(replays):
        price, path = entry, []
        for k in range(first, end_slot):
            o, h, l, c = rng.choice(pools[k])
            bar = _Bar(open_ts + k * SLOT, price * o, price * max(h, o, c), price * min(l, o, c), price * c)
            path.append(bar)
            price = bar.close
        out = manage_trade(side=side, entry=entry, entry_ts=open_ts + first * SLOT - 1, stop=stop, plan=plan,
                           bars=before + path, minutes=before + path, exit_time=exit_time)
        if out is None:
            return None
        results.append(out.result)
        rs.append(out.r_multiple)
    n = len(rs)
    pct = lambda k: round(100 * results.count(k) / n, 1)            # noqa: E731
    win = round(100 * sum(r > 0 for r in rs) / n, 1)
    avg = round(sum(rs) / n, 3)
    return Odds(n, sessions, win, pct("TARGET"), pct("STOP"), pct("TSL"), pct("TIME"), avg, round(median(rs), 3),
                verdict(win, avg))


LADDER = (1.5, 2.0, 2.5, 3.0)


def summary(*, symbol: str, side: str, entry: float, stop: float, plan: ExitPlan, entry_ts: int, history: Sequence,
            today: Sequence = (), exit_time: str = "15:10", replays: int = 1000) -> Optional[dict]:
    """The compact result shown in the tables: the trade's own plan + the chance of reaching each target."""
    common = dict(symbol=symbol, side=side, entry=entry, stop=stop, entry_ts=entry_ts, history=history, today=today,
                  exit_time=exit_time, replays=replays)
    own = run_odds(plan=plan, **common)
    if own is None:
        return None
    ladder = {}
    for rr in LADDER:
        o = own if plan.target_rr == rr and not plan.uses_tsl else run_odds(
            plan=ExitPlan(target_rr=rr, tsl_method="NONE"), **common)
        ladder[f"1:{rr:g}"] = {"target_pct": o.target_pct, "stop_pct": o.stop_pct, "time_pct": o.time_pct}
    target = f"target {own.target_pct:.0f}%" if plan.target_rr else "TSL exit"
    return {"text": f"win {own.win_pct:.0f}% · {target}", "win_pct": own.win_pct, "target_pct": own.target_pct,
            "stop_pct": own.stop_pct, "avg_r": own.avg_r, "sessions": own.sessions, "replays": own.replays,
            "ladder": ladder}


__all__ = ["LADDER", "Odds", "relative_moves", "run_odds", "summary", "verdict"]
