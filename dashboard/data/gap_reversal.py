"""Gap Reversal data for the dashboard (read-only, except the settings form).

Folder: data/gap_reversal (KQ_GAP_DIR lets tests point elsewhere):
  settings.json      strategy settings (dashboard form)
  status.json        live scanner (scripts/run_gap_reversal.py)
  minutes/*.csv      1-minute candles of today's gap symbols (live scanner)
  backtest_*.csv     scripts/gap_reversal_backtest.py
Research candles: data/research/market_data.db, series STK_<STOCK>.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .live import PROJECT_ROOT                   # also puts the project folder on sys.path
from paper_trading.chart_feeds import read_candles
from strategies.gap_reversal import GapReversalStore

IST = ZoneInfo("Asia/Kolkata")
COMMANDS = {
    "live": r"python scripts\run_gap_reversal.py",
    "backtest": r"python scripts\gap_reversal_backtest.py",
}


def gap_dir() -> Path:
    return Path(os.environ.get("KQ_GAP_DIR") or PROJECT_ROOT / "data" / "gap_reversal")


def research_db() -> Path:
    return Path(os.environ.get("KQ_RESEARCH_DIR") or PROJECT_ROOT / "data" / "research") / "market_data.db"


def store() -> GapReversalStore:
    return GapReversalStore(gap_dir())


def status() -> dict | None:
    path = gap_dir() / "status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (ValueError, OSError):
        return None


def _tag(interval: str) -> str:
    return "" if interval == "1m" else "_" + interval


def backtest_intervals() -> list[str]:
    """Backtests saved: '1m' (1-minute data) and / or '5m' (5-minute data, longer history)."""
    return [i for i in ("1m", "5m") if (gap_dir() / f"backtest_summary{_tag(i)}.csv").exists()]


def backtest(name: str, interval: str = "1m") -> pd.DataFrame | None:
    path = gap_dir() / f"backtest_{name}{_tag(interval)}.csv"
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path)


def backtest_meta(interval: str = "1m") -> dict | None:
    path = gap_dir() / f"backtest_meta{_tag(interval)}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def live_minutes(symbol: str) -> list:
    return read_candles(gap_dir() / "minutes" / f"{symbol.replace(':', '_')}.csv")


def research_minutes(stock: str, day: str, warmup_days: int = 6) -> list:
    """The day's 1-minute candles (plus a few earlier days for indicator warm-up) from the research DB."""
    from market_data.research_store import ResearchStore
    path = research_db()
    if not path.exists():
        return []
    db = ResearchStore(path)
    candles = []
    for source in ("fyers", "yahoo"):
        candles = db.load(f"STK_{stock}", source, "1m", clean_only=False)
        if candles:
            break
    end = datetime.fromisoformat(day).replace(tzinfo=IST) + timedelta(days=1)
    start = end - timedelta(days=warmup_days + 1)
    return [c for c in candles if start.timestamp() <= c.timestamp < end.timestamp()]


__all__ = ["COMMANDS", "backtest", "backtest_intervals", "backtest_meta", "gap_dir", "live_minutes", "research_minutes", "status", "store"]
