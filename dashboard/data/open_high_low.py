"""Open High Low data for the dashboard (read-only, except the settings form).

Folder: data/open_high_low (KQ_OHOL_DIR lets tests point elsewhere): settings.json, status.json (live
program), journal/<day>.json, backtest_*.csv (scripts/open_high_low_backtest.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .live import PROJECT_ROOT                   # also puts the project folder on sys.path
from strategies.open_high_low import OpenHighLowStore

COMMANDS = {
    "live": r"python scripts\run_open_high_low.py",
    "scan": r"python scripts\run_open_high_low.py --scan-only",
    "backtest": r"python scripts\open_high_low_backtest.py",
}


def ohol_dir() -> Path:
    return Path(os.environ.get("KQ_OHOL_DIR") or PROJECT_ROOT / "data" / "open_high_low")


def store() -> OpenHighLowStore:
    return OpenHighLowStore(ohol_dir())


def status() -> dict | None:
    path = ohol_dir() / "status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (ValueError, OSError):
        return None


def _tag(interval: str) -> str:
    return "" if interval == "1m" else "_" + interval


def backtest_intervals() -> list[str]:
    return [i for i in ("1m", "5m") if (ohol_dir() / f"backtest_summary{_tag(i)}.csv").exists()]


def backtest(name: str, interval: str = "1m") -> pd.DataFrame | None:
    path = ohol_dir() / f"backtest_{name}{_tag(interval)}.csv"
    if not path.exists() or path.stat().st_size == 0:
        return None
    return pd.read_csv(path)


def backtest_meta(interval: str = "1m") -> dict | None:
    path = ohol_dir() / f"backtest_meta{_tag(interval)}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


__all__ = ["COMMANDS", "backtest", "backtest_intervals", "backtest_meta", "ohol_dir", "status", "store"]
