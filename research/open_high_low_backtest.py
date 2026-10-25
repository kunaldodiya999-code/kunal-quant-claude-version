"""Backtest of the Open High Low rule on stock (spot) candles only.

Honest scope: free history has no stock-futures or stock-option candles (and FYERS keeps no expired
options), so this tests the SPOT part of the rule: at ``scan_at`` the stock's open equals its low (LONG)
or its high (SHORT), within the tolerance. Instead of the option score, the day's candidates are ranked
by liquidity (rupees traded in the stock the previous day) and the best ``top_n`` are traded: entry at the scan price,
stop at the day's low / high plus the buffer, every exit plan (fixed 1:1.5 .. 1:3 and TSL-only per
preset), Rs ``capital_per_trade`` per entry, estimated intraday charges. The live program records the
futures and options checks every day, so the full rule can be judged from the paper journal.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, time
from typing import Sequence
from zoneinfo import ZoneInfo

from backtest.equity_costs import intraday_charges
from market_data.day_quality import group_by_day
from paper_trading.trade_management import session_bars
from research.gap_reversal_backtest import _stats, default_exits, exit_label
from strategies.gap_reversal import GapReversalSettings
from strategies.open_high_low import OpenHighLowSettings, Quote, side_of
from strategies.trade_sim import manage_trade, step_of

IST = ZoneInfo("Asia/Kolkata")
CAPITAL_PER_TRADE = 50_000.0


def _session(minutes: Sequence) -> list:
    out = []
    for m in minutes:
        t = datetime.fromtimestamp(m.timestamp, IST)
        if (9, 15) <= (t.hour, t.minute) <= (15, 29):
            out.append(m)
    return out


def day_candidates(symbol: str, minutes: Sequence, s: OpenHighLowSettings, min_value_cr: float) -> dict:
    """{day: candidate dict} for one stock: the open = low / high check at ``scan_at`` on the finished candles.
    Liquidity = the previous session's traded value in Rs crore (known before the open; Yahoo often has no
    volume on the first candles)."""
    days = group_by_day(_session(minutes))
    step = step_of(minutes)
    scan = time.fromisoformat(s.scan_at)
    out = {}
    order = sorted(days)
    for prev, day in zip(order, order[1:]):
        mins = days[day]
        scan_ts = int(datetime.combine(day, scan, tzinfo=IST).timestamp())
        done = [m for m in mins if m.timestamp + step <= scan_ts]
        if not done:
            continue
        q = Quote(symbol, done[0].open, max(m.high for m in done), min(m.low for m in done), done[-1].close)
        side = side_of(q, s.tolerance_pct)
        value = sum((m.volume or 0) * m.close for m in days[prev]) / 1e7       # yesterday's traded value
        if side is None or value < min_value_cr:
            continue
        out[day] = {"symbol": symbol, "day": day, "side": side, "quote": q, "value_cr": value,
                    "entry_ts": done[-1].timestamp, "minutes": mins}
    return out


def run(series: dict[str, Sequence], s: OpenHighLowSettings, *, min_value_cr: float = 50.0,
        capital_per_trade: float = CAPITAL_PER_TRADE) -> tuple[list[dict], list[dict]]:
    """``series``: stock -> its candles (1-minute or 5-minute). Returns (candidates, trades)."""
    by_day: dict = {}
    for symbol, minutes in series.items():
        for day, c in day_candidates(symbol, minutes, s, min_value_cr).items():
            by_day.setdefault(day, []).append(c)
    exits = default_exits(GapReversalSettings())
    candidates, trades = [], []
    for day in sorted(by_day):
        ranked = sorted(by_day[day], key=lambda c: (-c["value_cr"], c["symbol"]))
        for rank, c in enumerate(ranked, 1):
            if not s.side(c["side"]).enabled:
                continue
            chosen = rank <= s.top_n
            q = c["quote"]
            candidates.append({"symbol": c["symbol"], "day": day.isoformat(), "side": c["side"], "open": q.open,
                               "high": q.high, "low": q.low, "price": q.ltp, "value_cr": round(c["value_cr"], 2),
                               "rank": rank, "traded": chosen})
            if not chosen:
                continue
            mins = c["minutes"]
            bars = session_bars(mins, s.timeframe, now=mins[-1].timestamp + step_of(mins))
            buf = s.side(c["side"]).sl_buffer_pct / 100
            stop = q.low * (1 - buf) if c["side"] == "LONG" else q.high * (1 + buf)
            for label, plan in exits:
                out = manage_trade(side=c["side"], entry=q.ltp, entry_ts=c["entry_ts"], stop=stop, plan=plan,
                                   bars=bars, minutes=mins, exit_time=s.exit_time, stop_label="day's low / high")
                if out is None:
                    continue
                qty = int(capital_per_trade // q.ltp)
                gross = out.points * qty
                charges = intraday_charges(out.entry, out.exit, qty, out.side)
                trades.append({"symbol": c["symbol"], "day": day.isoformat(), "side": out.side, "rank": rank,
                               "value_cr": round(c["value_cr"], 2), "entry_mode": "SCAN", "exit": label,
                               "entry_time": datetime.fromtimestamp(out.entry_time, IST).strftime("%H:%M"),
                               "entry": round(out.entry, 2), "stop": round(out.stop, 2),
                               "target": "" if out.target is None else round(out.target, 2),
                               "exit_time": datetime.fromtimestamp(out.exit_time, IST).strftime("%H:%M"),
                               "exit_price": round(out.exit, 2), "result": out.result, "exit_detail": out.detail,
                               "risk_pct": round(out.risk / abs(out.entry) * 100, 2), "r": out.r_multiple,
                               "best_r": out.max_favourable_r, "quantity": qty, "gross_pnl": round(gross, 2),
                               "charges": round(charges, 2), "net_pnl": round(gross - charges, 2)})
    return candidates, trades


def summarize(trades: list[dict]) -> list[dict]:
    groups: dict[tuple, list] = {}
    for t in trades:
        for side in (t["side"], "BOTH"):
            groups.setdefault((side, t["exit"]), []).append(t)
    order = list(dict.fromkeys(t["exit"] for t in trades))
    rank = {"BOTH": 0, "LONG": 1, "SHORT": 2}
    return [{"side": side, "exit": ex, "exit_plan": exit_label(ex), **_stats(rows)}
            for (side, ex), rows in sorted(groups.items(), key=lambda kv: (rank[kv[0][0]], order.index(kv[0][1])))]


def top_n_study(trades: list[dict], ns=(1, 2, 3, 5, 10)) -> list[dict]:
    """Net result (both sides) for other top-N choices: trades ranked <= N each day."""
    out = []
    for n in ns:
        groups: dict[str, list] = {}
        for t in trades:
            if t["rank"] <= n:
                groups.setdefault(t["exit"], []).append(t)
        for ex, rows in groups.items():
            st = _stats(rows)
            out.append({"top_n": n, "exit": ex, "exit_plan": exit_label(ex), "trades": st["trades"],
                        "win_rate_pct": st["win_rate_pct"], "net_pnl": st["net_pnl"],
                        "max_drawdown": st["max_drawdown"]})
    return out


__all__ = ["CAPITAL_PER_TRADE", "day_candidates", "run", "summarize", "top_n_study"]
