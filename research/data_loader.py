"""Load index candles for research from any source, keeping CLEAN days only.

Sources:
  research  data/research/market_data.db, Yahoo part (filled by scripts/sweep_market_data.py)
  fyers     data/research/market_data.db, FYERS part (filled by scripts/fetch_data.py)
  kq-db     the original KunalQuant database (5 years of NIFTY 1-minute from FYERS);
            every day is quality-checked here on the fly (market_data/day_quality.py).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from statistics import median

from market_data.day_quality import assess_series, group_by_day
from market_data.research_store import ResearchStore
from market_data.resampling import Candle
from strategies.index_profiles import INDEX_PROFILES

DEFAULT_KQ_DB = Path(r"C:\Users\USER\Desktop\Kunal\KunalQuant\data\database\kunal_quant.db")


def from_kq_db(path: str | Path, index: str) -> list[Candle]:
    symbol = INDEX_PROFILES[index].spot_symbol
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT c.timestamp, c.open, c.high, c.low, c.close FROM candles c JOIN instruments i "
            "ON i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1' "
            "GROUP BY c.timestamp ORDER BY c.timestamp", (symbol,)).fetchall()
    return [Candle(int(t), float(o), float(h), float(l), float(c), 0) for t, o, h, l, c in rows]


def load(source: str, index: str, *, resolution: str = "1m", kq_db: str | Path | None = None,
         research_db: str | Path | None = None, research_source: str = "yahoo") -> tuple[list[Candle], list[Candle]]:
    """(all candles, clean candles). ``all`` keeps indicator history continuous."""
    if source == "kq-db":
        everything = from_kq_db(kq_db or DEFAULT_KQ_DB, index)
        minutes = {"1m": 1, "5m": 5}[resolution]
        _, clean = assess_series(everything, minutes=minutes)
        return everything, clean
    if source == "fyers":                       # scripts/fetch_data.py (FYERS history, grows every day)
        research_source = "fyers"
    store = ResearchStore(research_db or Path("data/research/market_data.db"))
    return (store.load(index, research_source, resolution, clean_only=False),
            store.load(index, research_source, resolution))


def nifty_scales(clean: dict[str, list[Candle]]) -> dict[str, float]:
    """Point scale of each index vs NIFTY (median price ratio); NIFTY = 1."""
    medians = {k: median(c.close for c in v) for k, v in clean.items() if v}
    base = medians.get("NIFTY")
    if base is None:   # NIFTY not loaded: use typical ratios (Oct 2026)
        typical = {"NIFTY": 1.0, "BANKNIFTY": 2.4, "SENSEX": 3.2}
        return {k: typical[k] for k in clean}
    return {k: m / base for k, m in medians.items()}


__all__ = ["DEFAULT_KQ_DB", "from_kq_db", "group_by_day", "load", "nifty_scales"]
