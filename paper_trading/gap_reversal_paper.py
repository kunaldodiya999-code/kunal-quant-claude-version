"""Gap Reversal paper desk: marks setups live and paper-trades the stock itself (no orders).

The trading program (scripts/run_gap_reversal.py) gives it the gap list at the open and each
gap symbol's finished 1-minute candles. Each minute it re-runs the SAME scan and trade logic as
the backtest (strategies/gap_reversal.py) on the data so far, so paper and backtest agree.
One trade per symbol per day: the qualifying setup that ENTERS first, never before ``entry_from`` (09:40). Daily trade cap (settings): new trades are
admitted in the order they enter (stronger first at the same minute) until the cap is full; setups past
the cap are still marked and listed as "skipped (daily cap)". Short setups are paper intraday
short sells of the stock (owner: scanner + paper first, intraday cash later, options last).
Quantity = allocation % of capital / entry price (whole shares). Settings snapshot per trade.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from paper_trading.trade_management import session_bars
from strategies.gap_reversal import (
    GapReversalSettings, bars_from, daily_cap, first_entry, gap_side, scan_bars, simulate,
)

IST = ZoneInfo("Asia/Kolkata")
STATUS_FILE = "status.json"


def _clock(ts) -> str:
    return "" if ts is None else datetime.fromtimestamp(int(ts), IST).strftime("%H:%M")


class GapReversalDesk:
    def __init__(self, folder: str | Path, settings: GapReversalSettings, *, odds_history=None) -> None:
        """``odds_history``: symbol -> earlier sessions' 5-minute candles, for the Time Machine (None = off)."""
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.odds_history = odds_history
        self.odds: dict[str, dict] = {}           # symbol -> Time Machine summary at the entry (once)
        self.gaps: dict[str, dict] = {}          # symbol -> {"prev_close", "open", "gap_pct", "side"}
        self.candidates: dict[str, list] = {}
        self.trades: dict[str, dict] = {}         # symbol -> trade row
        self.proposals: dict[str, dict] = {}      # symbol -> trade row waiting for the daily cap (settle)
        self.skipped: dict[str, dict] = {}        # symbol -> row not taken because the daily cap was full
        self.snapshots: dict[str, GapReversalSettings] = {}
        self.history: dict[str, list] = {}        # symbol -> earlier days' 1-minute candles (TSL warm-up)

    def set_gap(self, symbol: str, prev_close: float, day_open: float) -> str | None:
        side, gap = gap_side(prev_close, day_open, self.settings)
        if side is not None:
            self.gaps[symbol] = {"prev_close": prev_close, "open": day_open, "gap_pct": round(gap, 2), "side": side}
        return side

    def set_history(self, symbol: str, minutes: Sequence) -> None:
        """Earlier days' 1-minute candles of a gap symbol: the TSL warms up on them (like a TradingView chart)."""
        self.history[symbol] = list(minutes)

    def on_minutes(self, symbol: str, minutes: Sequence, now: int) -> None:
        """All of today's FINISHED 1-minute candles of a gap symbol (with volume)."""
        info = self.gaps.get(symbol)
        if info is None or not minutes:
            return
        from paper_trading.chart_feeds import CandleFile
        CandleFile(self.folder / "minutes" / f"{symbol.replace(':', '_')}.csv").write(symbol, minutes)   # for the chart
        s = self.snapshots.get(symbol, self.settings)
        bars = bars_from(session_bars(minutes, s.timeframe, now=now))
        found = scan_bars(symbol, info["prev_close"], bars, s)
        self.candidates[symbol] = found
        # setups are always marked; paper trades only when the strategy is switched ON
        if not any(c.qualifies for c in found) or (not self.settings.enabled and symbol not in self.trades):
            return
        self.snapshots.setdefault(symbol, s)
        snap = self.snapshots[symbol]
        warm = bars_from(session_bars(self.history.get(symbol, []), snap.timeframe)) if self.history.get(symbol) else []
        mins = bars_from(minutes)
        taken = self.trades.get(symbol)
        if taken is not None:            # keep following the setup that was traded
            first = next((c for c in found if c.bar_time == taken["candidate_time"]), None)
            t = None if first is None else simulate(first, bars, mins, snap, live=True, history=warm)
        else:                            # the qualifying setup that enters first (from entry_from on)
            first, t = first_entry(found, bars, mins, snap, live=True, history=warm)
        if t is None:
            return
        qty = int(s.capital * s.allocation_pct / 100 // abs(t.entry)) or 1
        last = minutes[-1].close
        pnl_points = t.points if t.result != "OPEN" else ((t.entry - last) if t.side == "SHORT" else (last - t.entry))
        row = {
            "symbol": symbol, "side": t.side, "action": "PAPER SHORT SELL" if t.side == "SHORT" else "PAPER BUY",
            "setup": first.pattern_names, "strength": first.strength, "entry_time": _clock(t.entry_time),
            "entry": round(t.entry, 2), "stop": round(t.stop, 2), "target": "" if t.target is None else round(t.target, 2),
            "rr": "TSL" if t.rr is None else t.rr, "exit_plan": snap.side(t.side).exit_plan().describe(), "quantity": qty, "status": t.result, "exit_time": "" if t.result == "OPEN" else _clock(t.exit_time),
            "exit": "" if t.result == "OPEN" else round(t.exit, 2), "exit_detail": t.exit_detail,
            "last": round(last, 2),
            "pnl": round(pnl_points * qty, 2), "r": round(pnl_points / t.risk, 2) if t.risk else 0.0,
            "entry_epoch": t.entry_time, "candidate_time": first.bar_time,
            "time_machine": self._odds(symbol, t, snap, minutes),
        }
        if symbol in self.trades:
            self.trades[symbol] = row                 # already taken: keep following it
        elif symbol not in self.skipped:
            self.proposals[symbol] = row              # new: waits for settle() and the daily cap

    def _odds(self, symbol: str, t, snap: GapReversalSettings, minutes: Sequence) -> str:
        """Time Machine at the entry, worked out once per symbol and day (information only, never a filter)."""
        if self.odds_history is None:
            return ""
        if symbol not in self.odds:
            try:
                from strategies.time_machine import summary
                today = [m for m in minutes if m.timestamp <= t.entry_time]
                self.odds[symbol] = summary(symbol=symbol, side=t.side, entry=t.entry, stop=t.stop,
                                            plan=snap.side(t.side).exit_plan(), entry_ts=t.entry_time,
                                            history=self.odds_history(symbol), today=today,
                                            exit_time=snap.exit_time) or {}
            except Exception:                              # odds are extra: never stop the desk
                self.odds[symbol] = {}
        return self.odds[symbol].get("text", "")

    def settle(self) -> None:
        """Admit this scan's new trades under the daily cap (call after every symbol was updated)."""
        if not self.proposals:
            return
        s = self.settings
        proposals = [dict(r, entry_time=r["entry_epoch"]) for r in self.proposals.values()]
        taken = [dict(r, entry_time=r["entry_epoch"]) for r in self.trades.values()]
        admitted, skipped = daily_cap(proposals, s, taken)
        for r in admitted:
            self.trades[r["symbol"]] = self.proposals[r["symbol"]]
        for r in skipped:
            self.skipped[r["symbol"]] = {**self.proposals[r["symbol"]], "status": "SKIPPED (daily cap)"}
        self.proposals.clear()

    def status(self, now: int) -> dict:
        cands = []
        for symbol, found in self.candidates.items():
            for c in found:
                cands.append({"symbol": symbol, "side": c.side, "gap_pct": c.gap_pct, "time": _clock(c.bar_time),
                              "setups": c.pattern_names, "strength": c.strength, "qualifies": c.qualifies,
                              "trigger": round(c.trigger, 2), "confirmed": c.parts.get("confirmed"),
                              "volume_ratio": c.parts.get("volume_ratio"), "bar_time": c.bar_time})
        return {"updated_at": datetime.fromtimestamp(now, IST).strftime("%Y-%m-%d %H:%M:%S"), "updated_epoch": now,
                "strategy_enabled": self.settings.enabled, "gap_pct": self.settings.gap_pct,
                "gaps": [{"symbol": k, **v} for k, v in sorted(self.gaps.items(), key=lambda kv: -abs(kv[1]["gap_pct"]))],
                "candidates": sorted(cands, key=lambda c: -c["strength"]),
                "trades": list(self.trades.values()),
                "skipped": list(self.skipped.values()),
                "time_machine": {k: v for k, v in self.odds.items() if v},
                "daily_cap": {"max_trades": self.settings.max_trades_per_day,
                              "max_short": self.settings.max_short_per_day, "max_long": self.settings.max_long_per_day,
                              "taken": len(self.trades)},
                "day_pnl": round(sum(t["pnl"] for t in self.trades.values()), 2)}

    def write_status(self, now: int) -> dict:
        self.settle()
        data = self.status(now)
        tmp = self.folder / (STATUS_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.folder / STATUS_FILE)
        day = datetime.fromtimestamp(now, IST).date().isoformat()
        (self.folder / "journal").mkdir(exist_ok=True)
        (self.folder / "journal" / f"{day}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data


__all__ = ["GapReversalDesk", "STATUS_FILE"]
