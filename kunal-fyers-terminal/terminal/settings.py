"""Every choice on the screen, saved in data/settings.json (the engine reads it every few seconds)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from datetime import time
from pathlib import Path
from typing import Optional

from terminal.fyers import INDEXES, data_dir
from terminal.strategy import MODES

TIMEFRAMES = (1, 3, 5)


@dataclass(frozen=True)
class Settings:
    index: str = "NIFTY"
    timeframe: int = 3                     # owner trades 3-minute
    call_on: bool = True
    put_on: bool = True
    strike_mode: str = "RANGE"             # RANGE = premium lo - hi, PER_LOT = per lot amount
    premium_low: float = 0.0
    premium_high: float = 0.0
    per_lot_amount: float = 0.0
    funds_per_entry: float = 0.0           # Rs to use for each new entry
    buffer: float = 2.0                    # limit price buffer, Rs (buy = price + 2, sell = price - 2)
    entry_start: str = "09:30"
    entry_end: str = "15:00"               # no new entries from here
    force_exit: str = "15:10"
    bbp_window: int = 10                   # BBP_NM "Lookback Window"
    real_orders: bool = False              # OFF: paper trades. ON needs the daily arm too (broker.py)

    def __post_init__(self) -> None:
        if self.index not in INDEXES:
            raise ValueError(f"index must be one of {tuple(INDEXES)}")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError("timeframe must be 1, 3 or 5 minutes")
        if self.strike_mode not in MODES:
            raise ValueError(f"strike_mode must be one of {MODES}")
        if min(self.premium_low, self.premium_high, self.per_lot_amount, self.funds_per_entry) < 0:
            raise ValueError("amounts cannot be negative")
        if self.premium_high and self.premium_low > self.premium_high:
            raise ValueError("premium range: the first box must be the lower price")
        if not (0 <= self.buffer <= 10):
            raise ValueError("buffer must be between 0 and 10 rupees")
        if not (time.fromisoformat(self.entry_start) < time.fromisoformat(self.entry_end)
                <= time.fromisoformat(self.force_exit)):
            raise ValueError("times must be: entry start < entry end <= force exit")
        if self.bbp_window < 2:
            raise ValueError("BBP lookback must be at least 2")


class SettingsStore:
    def __init__(self, folder: Optional[Path] = None) -> None:
        self.path = Path(folder or data_dir()) / "settings.json"

    def load(self) -> Settings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            return Settings(**{k: v for k, v in data.items() if k in known})
        except (OSError, ValueError, TypeError):
            return Settings()

    def save(self, settings: Settings) -> Settings:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
        tmp.replace(self.path)
        return settings

    def update(self, **changes) -> Settings:
        return self.save(replace(self.load(), **changes))


__all__ = ["Settings", "SettingsStore", "TIMEFRAMES"]
