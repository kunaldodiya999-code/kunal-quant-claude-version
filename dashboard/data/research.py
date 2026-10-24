"""Research results for the dashboard (written by the research scripts, read-only here).

Files live in data/research (KQ_RESEARCH_DIR lets tests point elsewhere):
  sweep_report.csv                      scripts/sweep_market_data.py
  results/ktmi_accuracy_*.csv|json      scripts/ktmi_accuracy.py
  results/opening_scalp_*.csv|json      scripts/opening_scalp_backtest.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESEARCH_DIR = PROJECT_ROOT / "data" / "research"

COMMANDS = {
    "sweep": r"python scripts\sweep_market_data.py --source both --days 730",
    "ktmi": r"python scripts\ktmi_accuracy.py",
    "scalp": r"python scripts\opening_scalp_backtest.py",
}


def research_dir() -> Path:
    return Path(os.environ.get("KQ_RESEARCH_DIR") or DEFAULT_RESEARCH_DIR)


def _csv(path: Path) -> pd.DataFrame | None:
    return pd.read_csv(path) if path.exists() else None


def _json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def sweep_report() -> pd.DataFrame | None:
    return _csv(research_dir() / "sweep_report.csv")


def ktmi_summary() -> pd.DataFrame | None:
    return _csv(research_dir() / "results" / "ktmi_accuracy_summary.csv")


def ktmi_signals() -> pd.DataFrame | None:
    return _csv(research_dir() / "results" / "ktmi_accuracy_signals.csv")


def ktmi_meta() -> dict | None:
    return _json(research_dir() / "results" / "ktmi_accuracy_meta.json")


def scalp_summary() -> dict | None:
    return _json(research_dir() / "results" / "opening_scalp_summary.json")


def scalp_trades() -> pd.DataFrame | None:
    return _csv(research_dir() / "results" / "opening_scalp_trades.csv")


def scalp_grid() -> pd.DataFrame | None:
    return _csv(research_dir() / "results" / "opening_scalp_grid.csv")
