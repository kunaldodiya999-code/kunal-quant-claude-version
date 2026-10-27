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
from strategies.strike_ladder import STRIKE_CHOICES

SETTINGS_FILE = "strategy_settings.json"


STRIKE_MODES = ("MANUAL", "AUTO_ATM_ATM1")


@dataclass(frozen=True)
class StrategySettings:
    timeframe_minutes: int = 3        # one of 1, 3, 5, 10, 15, 30, 60
    trade_direction: str = "BOTH"     # LONG (calls only), SHORT (puts only), BOTH
    entry_start: str = "09:30"        # first new entry allowed, HH:MM IST
    entry_end: str = "15:00"          # no new entries from this time
    force_exit: str = "15:10"         # open positions closed at this time
    # Order window. Dropdowns: which of the 5 strikes to buy.
    call_strike: str = "ATM"          # ITM1, ATM, OTM1, OTM2, OTM3
    put_strike: str = "ATM"
    # Checkboxes. When either is ticked they decide the strike(s) instead of the
    # dropdowns; both ticked = two trades per signal (ATM and ATM+1).
    use_atm: bool = False
    use_atm_plus_1: bool = False
    # Dashboard "Trade in": False = watch this index (signals, chart) but take no entries.
    trading_enabled: bool = True
    # Owner 27 Oct 2026: AUTO = buy ATM or ATM+1, whichever buys MORE lots with the money (never beyond ATM+1);
    # MANUAL = the dropdowns / checkboxes above. max_lot_cost: one lot may cost at most this (Rs, 0 = no cap),
    # in both modes (NIFTY: Rs 8,000). strategies/funds_strike.py.
    strike_mode: str = "MANUAL"
    max_lot_cost: float = 0.0

    def __post_init__(self) -> None:
        for name in (self.call_strike, self.put_strike):
            if name not in STRIKE_CHOICES:
                raise ValueError(f"strike choice must be one of {tuple(STRIKE_CHOICES)}")
        if not all(isinstance(v, bool) for v in (self.use_atm, self.use_atm_plus_1, self.trading_enabled)):
            raise ValueError("use_atm, use_atm_plus_1 and trading_enabled must be true or false")
        if self.strike_mode not in STRIKE_MODES:
            raise ValueError(f"strike_mode must be one of {STRIKE_MODES}")
        if not (isinstance(self.max_lot_cost, (int, float)) and self.max_lot_cost >= 0):
            raise ValueError("max_lot_cost must be 0 (no cap) or a positive rupee amount")
        if self.timeframe_minutes not in SUPPORTED_RESOLUTIONS:
            raise ValueError(f"timeframe must be one of {SUPPORTED_RESOLUTIONS} minutes")
        if self.trade_direction not in TRADE_DIRECTIONS:
            raise ValueError(f"trade direction must be one of {TRADE_DIRECTIONS}")
        # Reuses the session-controls rules: valid HH:MM, start < end <= force exit.
        SessionControlsConfig.from_hhmm(self.entry_start, self.entry_end, self.force_exit)


def entry_strike_offsets(settings: StrategySettings, direction: str) -> list[tuple[str, int]]:
    """(label, offset) for every trade one signal should open, in slot order. AUTO: one trade, strike chosen at
    the entry from ATM / ATM+1 by the money (label "AUTO")."""
    if settings.strike_mode == "AUTO_ATM_ATM1":
        return [("AUTO", 0)]
    if settings.use_atm or settings.use_atm_plus_1:
        plan = []
        if settings.use_atm:
            plan.append(("ATM", 0))
        if settings.use_atm_plus_1:
            plan.append(("ATM+1", 1))
        return plan
    choice = settings.call_strike if direction == "LONG" else settings.put_strike
    return [(choice, STRIKE_CHOICES[choice])]


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
            self._mtime = self._path.stat().st_mtime
        else:
            self._mtime = None

    def refresh(self) -> StrategySettings:
        """Pick up a change saved by another program (the dashboard). A broken
        file keeps the last good settings instead of stopping a live session."""
        if self._path is None or not self._path.exists():
            return self._settings
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            self._mtime = mtime
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._settings = replace(self._settings, **data)
            except (ValueError, TypeError):
                pass
        return self._settings

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
            self._mtime = self._path.stat().st_mtime
        return self._settings


__all__ = ["STRIKE_MODES", "SETTINGS_FILE", "StrategySettings", "StrategySettingsStore", "entry_strike_offsets"]
