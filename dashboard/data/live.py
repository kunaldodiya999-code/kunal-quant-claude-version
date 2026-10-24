"""Real data for the Live Paper Trading page.

Reads what ``scripts/run_paper_session.py`` writes (live_status.json and the
CSV journals) and saves the owner's settings through the same
StrategySettingsStore the runner uses. No trading logic, no orders.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_trading.live_support import STATUS_FILE  # noqa: E402
from paper_trading.strategy_settings import StrategySettings, StrategySettingsStore  # noqa: E402
from strategies.index_profiles import INDEX_PROFILES  # noqa: E402
from strategies.strike_ladder import STRIKE_CHOICES  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
DEFAULT_PAPER_DIR = PROJECT_ROOT / "data" / "paper_trading"


INDEX_KEYS = tuple(INDEX_PROFILES)


def paper_root() -> Path:
    """data/paper_trading. KQ_PAPER_DIR lets tests point the page at a temporary folder."""
    return Path(os.environ.get("KQ_PAPER_DIR") or DEFAULT_PAPER_DIR)


def paper_dir(index: str = "NIFTY") -> Path:
    """One folder per index: data/paper_trading/NIFTY, .../BANKNIFTY, .../SENSEX."""
    return paper_root() / index


def live_dir(index: str = "NIFTY") -> Path:
    """Broker-order journals: data/live_trading/<INDEX>."""
    return paper_root().parent / "live_trading" / index


STALE_AFTER_SECONDS = 15


def settings_store(index: str = "NIFTY") -> StrategySettingsStore:
    return StrategySettingsStore(StrategySettings(), paper_dir(index))


def load_status(index: str = "NIFTY") -> dict | None:
    path = paper_dir(index) / STATUS_FILE
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def status_age_seconds(status: dict | None, now: float | None = None) -> float | None:
    if not status or "updated_epoch" not in status:
        return None
    return (time.time() if now is None else now) - float(status["updated_epoch"])


def strike_options(status: dict | None, side: str) -> list[tuple[str, str]]:
    """(choice, label) for a dropdown, e.g. ('OTM1', 'OTM1 - 22050 CE')."""
    suffix = "CE" if side == "call" else "PE"
    ladder = {row["choice"]: row["strike"] for row in ((status or {}).get("ladders") or {}).get(side, [])}
    return [
        (choice, f"{choice} - {ladder[choice]} {suffix}" if choice in ladder else f"{choice} (waiting for live price)")
        for choice in STRIKE_CHOICES
    ]


def summary_rows(now: float | None = None) -> list[dict]:
    """One line per index for the overview table."""
    rows = []
    for key in INDEX_KEYS:
        status = load_status(key)
        age = status_age_seconds(status, now)
        fresh = age is not None and age <= STALE_AFTER_SECONDS
        account = (status or {}).get("account") or {}
        rows.append({
            "Index": INDEX_PROFILES[key].label,
            "Running": "Yes" if fresh else "No",
            "Spot": (status or {}).get("spot"),
            "ATM": ((status or {}).get("ladders") or {}).get("atm"),
            "Open trades": len((status or {}).get("positions") or []),
            "Day P&L": account.get("day_pnl"),
            "Orders": (status or {}).get("orders_mode", "-"),
            "Updated": (status or {}).get("updated_at", "-"),
        })
    return rows


def journal(name: str, folder: Path, today_only: bool = True, limit: int = 50) -> pd.DataFrame:
    path = folder / name
    if not path.exists():
        return pd.DataFrame()
    try:
        frame = pd.read_csv(path)
    except (ValueError, OSError):
        return pd.DataFrame()
    if today_only and "recorded_at" in frame.columns:
        today = datetime.now(IST).date().isoformat()
        frame = frame[frame["recorded_at"].astype(str).str.startswith(today)]
    return frame.tail(limit).iloc[::-1].reset_index(drop=True)


__all__ = [
    "INDEX_KEYS", "STALE_AFTER_SECONDS", "journal", "live_dir", "load_status", "paper_dir", "paper_root",
    "settings_store", "status_age_seconds", "strike_options", "summary_rows",
]
