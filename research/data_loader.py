"""Load index candles for research, keeping CLEAN days only.

ONE source (owner 26 Oct 2026: FYERS data only, one database for both repos): the KunalQuant database
(market_data/kq_store.py; 5 years of NIFTY + what scripts/fetch_data.py adds). Every day is quality-checked here
on the fly (market_data/day_quality.py). "fyers" and "kq-db" are the same thing (old commands keep working).
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from statistics import median

from market_data.day_quality import assess_series, group_by_day
from market_data.kq_store import KQStore, default_path
from market_data.resampling import Candle

DEFAULT_KQ_DB = default_path()
SOURCES = ("fyers", "kq-db")


def from_kq_db(path: str | Path, index: str, *, since: date | None = None) -> list[Candle]:
    return KQStore(path).load(index, since=since)


def load(source: str, index: str, *, resolution: str = "1m", kq_db: str | Path | None = None,
         days: int | None = None, **_old) -> tuple[list[Candle], list[Candle]]:
    """(all candles, clean candles). ``all`` keeps indicator history continuous. ``days``: only the last N days
    are tested (a few earlier days are kept in ``all`` to warm the indicators up)."""
    if source not in SOURCES:
        raise SystemExit(f"Data source {source!r} is not used any more: FYERS data only (--source fyers).")
    since = None
    if days:
        newest = KQStore(kq_db or default_path()).saved_range(index)[1]
        since = (newest or date.today()) - timedelta(days=days)
    everything = from_kq_db(kq_db or default_path(), index, since=None if since is None else since - timedelta(days=10))
    minutes = {"1m": 1, "5m": 5}[resolution]
    _, clean = assess_series(everything, minutes=minutes)
    if since is not None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ist = ZoneInfo("Asia/Kolkata")
        clean = [c for c in clean if datetime.fromtimestamp(c.timestamp, ist).date() >= since]
    return everything, clean


def nifty_scales(clean: dict[str, list[Candle]]) -> dict[str, float]:
    """Point scale of each index vs NIFTY (median price ratio); NIFTY = 1."""
    medians = {k: median(c.close for c in v) for k, v in clean.items() if v}
    base = medians.get("NIFTY")
    if base is None:   # NIFTY not loaded: use typical ratios (Oct 2026)
        typical = {"NIFTY": 1.0, "BANKNIFTY": 2.4, "SENSEX": 3.2}
        return {k: typical[k] for k in clean}
    return {k: m / base for k, m in medians.items()}


__all__ = ["DEFAULT_KQ_DB", "SOURCES", "from_kq_db", "group_by_day", "load", "nifty_scales"]
