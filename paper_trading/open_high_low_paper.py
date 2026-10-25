"""Open High Low paper desk: keeps the day's scan and paper-trades the top candidates (no orders).

The program (scripts/run_open_high_low.py) scans once when the first candle closes and gives the desk every
candidate; the desk shortlists the best ``top_n`` (when the strategy is ON) as WAITING, enters each one when the
next candle breaks the first candle's high (LONG) / low (SHORT) and follows each trade with
the shared exit plan (strategies/trade_sim.py) on its chart's 1-minute candles. Instrument:
STOCK (Rs capital_per_trade / price shares), FUTURE (lots x lot size) or OPTION (bought ATM CE for a
LONG, ATM PE for a SHORT; levels on the stock, P&L on the premium). Writes status.json + journal.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from paper_trading.trade_management import session_bars
from strategies.open_high_low import Candidate, OpenHighLowSettings, breakout, select_top
from strategies.trade_sim import manage_trade

IST = ZoneInfo("Asia/Kolkata")
STATUS_FILE = "status.json"


def _clock(ts) -> str:
    return "" if ts in (None, "") else datetime.fromtimestamp(int(ts), IST).strftime("%H:%M")


def _price_at(minutes: Sequence, ts: int) -> Optional[float]:
    before = [m for m in minutes if m.timestamp <= ts]
    return before[-1].close if before else None


class OpenHighLowDesk:
    def __init__(self, folder: str | Path, settings: OpenHighLowSettings) -> None:
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.scan_rows: list[dict] = []
        self.scanned_at: Optional[int] = None
        self.trades: dict[str, dict] = {}

    def scan(self, candidates: Sequence[Candidate], now: int, *, symbols: dict | None = None,
             lot_sizes: dict | None = None) -> list[Candidate]:
        """``symbols``: stock -> {"spot": ..., "future": ...}; ``lot_sizes``: stock -> lot size."""
        s = self.settings
        top = select_top(candidates, s)
        picked = {c.stock for c in top}
        self.scanned_at = now
        self.scan_rows = sorted((dict(c.row(), selected=c.stock in picked) for c in candidates if c.side),
                                key=lambda r: (not r["selected"], not r["passes"], -r["option_score"]))
        if not s.enabled:
            return top
        for c in top:
            if c.stock in self.trades:
                continue
            names = (symbols or {}).get(c.stock, {})
            lot = int((lot_sizes or {}).get(c.stock) or 1)
            if s.instrument == "STOCK":
                traded, qty = names.get("spot", f"NSE:{c.stock}-EQ"), None          # shares: set at the entry
            elif s.instrument == "FUTURE":
                traded, qty = names.get("future", ""), s.lots * lot
            else:
                traded, qty = (c.atm_call if c.side == "LONG" else c.atm_put), s.lots * lot
            if not traded:
                continue
            self.trades[c.stock] = {
                "stock": c.stock, "side": c.side, "instrument": s.instrument, "symbol": traded,
                "action": {"STOCK": "PAPER BUY" if c.side == "LONG" else "PAPER SHORT SELL",
                           "FUTURE": "PAPER BUY FUT" if c.side == "LONG" else "PAPER SELL FUT",
                           "OPTION": "PAPER BUY CE" if c.side == "LONG" else "PAPER BUY PE"}[s.instrument],
                "chart": names.get("future", "") if s.instrument == "FUTURE" else names.get("spot", f"NSE:{c.stock}-EQ"),
                "option_score": c.option_score, "trigger": "", "entry_epoch": None, "entry_time": "",
                "level_entry": "", "stop": "", "entry": "", "quantity": qty or "",
                "target": "", "status": "WAITING", "exit_time": "", "exit": "", "exit_detail": "", "last": "",
                "pnl": 0.0, "r": 0.0, "exit_plan": s.side(c.side).exit_plan().describe(),
            }
        return top

    def on_minutes(self, stock: str, chart_minutes: Sequence, now: int, *, option_minutes: Sequence = (),
                   history: Sequence = ()) -> None:
        """Today's FINISHED 1-minute candles of the trade's chart (and of the option, for OPTION trades).
        WAITING: the breakout of the first candle (strategies.open_high_low.breakout); then the exit plan."""
        t = self.trades.get(stock)
        if t is None or not chart_minutes:
            return
        s = self.settings
        if t["entry_epoch"] is None:
            b = breakout(chart_minutes, t["side"], s)
            if b.get("trigger") is not None:
                t["trigger"] = round(b["trigger"], 2)
            if b["state"] in ("CANCELLED", "NO ENTRY"):
                t["status"] = b["state"]
                t["exit_detail"] = ("price went past the open before the breakout" if b["state"] == "CANCELLED"
                                    else "the next candle did not cross the first candle")
                return
            if b["state"] != "ENTERED":
                return
            price = b["entry"]
            if t["instrument"] == "OPTION":
                price = _price_at(option_minutes, b["entry_ts"])
                if not price:
                    return                                                   # option price not known yet
            elif t["instrument"] == "STOCK":
                t["quantity"] = int(s.capital_per_trade // b["entry"])
            t.update({"entry_epoch": b["entry_ts"], "entry_time": _clock(b["entry_ts"]),
                      "level_entry": round(b["entry"], 2), "stop": round(b["stop"], 2), "entry": round(price, 2),
                      "status": "OPEN"})
        if not t["quantity"]:
            return
        bars = session_bars(chart_minutes, s.timeframe, now=now)
        warm = session_bars(history, s.timeframe) if history else []
        out = manage_trade(side=t["side"], entry=t["level_entry"], entry_ts=t["entry_epoch"], stop=t["stop"],
                           plan=s.side(t["side"]).exit_plan(), bars=bars, minutes=chart_minutes,
                           exit_time=s.exit_time, history=warm, live=True, stop_label="day's low / high")
        if out is None:
            return
        sign = 1 if t["side"] == "LONG" else -1
        if t["instrument"] == "OPTION":
            last = _price_at(option_minutes, now) or t["entry"]
            exit_px = _price_at(option_minutes, out.exit_time) if out.result != "OPEN" else None
            px = last if out.result == "OPEN" else (exit_px or last)
            pnl = (px - t["entry"]) * t["quantity"]                       # bought premium, CE or PE
        else:
            last = chart_minutes[-1].close
            px = last if out.result == "OPEN" else out.exit
            pnl = sign * (px - t["entry"]) * t["quantity"]
        t.update({"target": "" if out.target is None else round(out.target, 2), "status": out.result,
                  "exit_time": "" if out.result == "OPEN" else _clock(out.exit_time),
                  "exit": "" if out.result == "OPEN" else round(px, 2), "exit_detail": out.detail,
                  "last": round(last, 2), "pnl": round(pnl, 2),
                  "r": out.r_multiple if out.result != "OPEN" else round(sign * (chart_minutes[-1].close - out.entry)
                                                                         / out.risk, 2)})

    def status(self, now: int) -> dict:
        s = self.settings
        return {"updated_at": datetime.fromtimestamp(now, IST).strftime("%Y-%m-%d %H:%M:%S"), "updated_epoch": now,
                "strategy_enabled": s.enabled, "scan_at": s.scan_at, "instrument": s.instrument, "top_n": s.top_n,
                "scanned_at": _clock(self.scanned_at), "scan": self.scan_rows,
                "trades": list(self.trades.values()),
                "day_pnl": round(sum(t["pnl"] for t in self.trades.values()), 2)}

    def write_status(self, now: int) -> dict:
        data = self.status(now)
        tmp = self.folder / (STATUS_FILE + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        tmp.replace(self.folder / STATUS_FILE)
        day = datetime.fromtimestamp(now, IST).date().isoformat()
        (self.folder / "journal").mkdir(exist_ok=True)
        (self.folder / "journal" / f"{day}.json").write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
        return data


__all__ = ["OpenHighLowDesk"]
