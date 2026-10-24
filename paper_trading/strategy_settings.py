"""Owner-editable strategy settings, saved in ``strategy_settings.json``.

Like ``allocation.json``: the saved file wins over the code defaults, so a
choice survives restarts. Change it with ``scripts/paper_settings.py`` (and
later from the UI) instead of editing Python.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from paper_trading.controls import SessionControlsConfig
from paper_trading.coordinator import TRADE_DIRECTIONS
from paper_trading.market_data_pipeline import SUPPORTED_RESOLUTIONS

SETTINGS_FILE = "strategy_settings.json"


@dataclass(frozen=True)
class StrategySettings:
    timeframe_minutes: int = 3        # one of 1, 3, 5, 10, 15, 30, 60
    trade_direction: str = "BOTH"     # LONG (calls only), SHORT (puts only), BOTH
    entry_start: str = "09:30"        # first new entry allowed, HH:MM IST
    entry_end: str = "15:00"          # no new entries from this time
    force_exit: str = "15:10"         # open positions closed at this time

    def __post_init__(self) -> None:
        if self.timeframe_minutes not in SUPPORTED_RESOLUTIONS:
            raise ValueError(f"timeframe must be one of {SUPPORTED_RESOLUTIONS} minutes")
        if self.trade_direction not in TRADE_DIRECTIONS:
            raise ValueError(f"trade direction must be one of {TRADE_DIRECTIONS}")
        # Reuses the session-controls rules: valid HH:MM, start < end <= force exit.
        SessionControlsConfig.from_hhmm(self.entry_start, self.entry_end, self.force_exit)


class StrategySettingsStore:
    def __init__(self, default: StrategySettings, journal_dir: str | Path | None = None) -> None:
        self._settings = default
        self._path = None if journal_dir is None else Path(journal_dir) / SETTINGS_FILE
        if self._path is not None and self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._settings = replace(default, **data)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{self._path} is invalid ({exc}); fix or delete it to use the defaults.") from exc

    @property
    def settings(self) -> StrategySettings:
        return self._settings

    @property
    def path(self) -> Path | None:
        return self._path

    def update(self, **changes) -> StrategySettings:
        self._settings = replace(self._settings, **changes)  # validates
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(asdict(self._settings), indent=2), encoding="utf-8")
        return self._settings


__all__ = ["SETTINGS_FILE", "StrategySettings", "StrategySettingsStore"]
