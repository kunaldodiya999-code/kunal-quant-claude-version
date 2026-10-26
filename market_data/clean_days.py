"""Which days a stock backtest may trade (owner 26 Oct 2026: "3 months of clean data, not 1 year of broken data").

A stock day is tradable only when it is CLEAN under the stock rules (market_data/day_quality.py STOCK_RULES) AND the
stock has the previous trading day too (the gap and yesterday's traded value come from it). The trading calendar is
every day on which any stock has candles, so a stock missing a whole day is caught.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

from market_data.day_quality import STOCK_RULES, assess_series, group_by_day
from market_data.resampling import Candle


def calendar_from_store(db_path: str | Path, source: str, resolution: str) -> list[date]:
    """Every day (IST) on which any stock has candles in data/research/market_data.db."""
    with sqlite3.connect(db_path) as db:
        rows = db.execute("SELECT DISTINCT date(ts + 19800, 'unixepoch') FROM candles WHERE series LIKE 'STK_%' "
                          "AND source=? AND resolution=?", (source, resolution)).fetchall()
    return sorted(date.fromisoformat(r[0]) for r in rows)


def tradable_days(candles: Sequence[Candle], calendar: Iterable[date], *, minutes: int = 1) -> tuple[set, dict]:
    """(days this stock may trade, counts {"days", "clean", "tradable"})."""
    reports, _ = assess_series(candles, minutes=minutes, fix_closing_artifact=False, rules=STOCK_RULES)
    have = set(group_by_day(candles))
    order = sorted(set(calendar) | have)
    previous = {d: p for p, d in zip(order, order[1:])}
    clean = {r.day for r in reports if r.clean}
    ok = {d for d in clean if previous.get(d) in have}
    return ok, {"days": len(reports), "clean": len(clean), "tradable": len(ok)}


__all__ = ["calendar_from_store", "tradable_days"]
