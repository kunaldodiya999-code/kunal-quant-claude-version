"""Gap Reversal paper desk: marks setups live and paper-trades the stock itself (no orders).

The trading program (scripts/run_gap_reversal.py) gives it the gap list at the open and each
gap symbol's finished 1-minute candles. Each minute it re-runs the SAME scan and trade logic as
the backtest (strategies/gap_reversal.py) on the data so far, so paper and backtest agree.
One trade per symbol per day: the first qualifying setup. Short setups are paper intraday
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
from strategies.gap_reversal import GapReversalSettings, bars_from, gap_side, scan_bars, simulate

IST = ZoneInfo("Asia/Kolkata")
STATUS_FILE = "status.json"


def _clock(ts) -> str:
    return "" if ts is None else datetime.fromtimestamp(int(ts), IST).strftime("%H:%M")


class GapReversalDesk:
    def __init__(self, folder: str | Path, settings: GapReversalSettings) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.gaps: dict[str, dict] = {}          # symbol -> {"prev_close", "open", "gap_pct", "side"}
        self.candidates: dict[str, list] = {}
        self.trades: dict[str, dict] = {}         # symbol -> trade row
        self.snapshots: dict[str, GapReversalSettings] = {}

    def set_gap(self, symbol: str, prev_close: float, day_open: float) -> str | None:
        side, gap = gap_side(prev_close, day_open, self.settings)
        if side is not None:
            self.gaps[symbol] = {"prev_close": prev_close, "open": day_open, "gap_pct": round(gap, 2), "side": side}
        return side

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
        first = next((c for c in found if c.qualifies), None)
        # setups are always marked; paper trades only when the strategy is switched ON
        if first is None or (not self.settings.enabled and symbol not in self.trades):
            return
        self.snapshots.setdefault(symbol, s)
        t = simulate(first, bars, bars_from(minutes), self.snapshots[symbol], live=True)
        if t is None:
            return
        qty = int(s.capital * s.allocation_pct / 100 // abs(t.entry)) or 1
        last = minutes[-1].close
        pnl_points = t.points if t.result != "OPEN" else ((t.entry - last) if t.side == "SHORT" else (last - t.entry))
        self.trades[symbol] = {
            "symbol": symbol, "side": t.side, "action": "PAPER SHORT SELL" if t.side == "SHORT" else "PAPER BUY",
            "setup": first.pattern_names, "strength": first.strength, "entry_time": _clock(t.entry_time),
            "entry": round(t.entry, 2), "stop": round(t.stop, 2), "target": round(t.target, 2),
            "rr": t.rr, "quantity": qty, "status": t.result, "exit_time": "" if t.result == "OPEN" else _clock(t.exit_time),
            "exit": "" if t.result == "OPEN" else round(t.exit, 2), "last": round(last, 2),
            "pnl": round(pnl_points * qty, 2), "r": round(pnl_points / t.risk, 2) if t.risk else 0.0,
        }

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
                "day_pnl": round(sum(t["pnl"] for t in self.trades.values()), 2)}

    def write_status(self, now: int) -> dict:
        data = self.status(now)
        tmp = self.folder / (STATUS_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(self.folder / STATUS_FILE)
        day = datetime.fromtimestamp(now, IST).date().isoformat()
        (self.folder / "journal").mkdir(exist_ok=True)
        (self.folder / "journal" / f"{day}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
        return data


__all__ = ["GapReversalDesk", "STATUS_FILE"]
