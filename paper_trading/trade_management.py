"""Trade management: initial stop, trailing stop (TSL), 2R partial booking, session rules.

Every number is a setting (``trade_management.json`` per index, changed from the dashboard
or ``scripts/trade_settings.py``). Defaults = the owner's requirements brief (24 Oct 2026):

  initial stop 30% of option premium      TSL on, indicator mode, Chandelier Exit (everget) 9 x 1.5
  TSL calculated on the OPTION chart        TSL candles = the strategy timeframe
  TSL exit when a candle CLOSES beyond it   partial booking at 2R, 50% of the lots
  one-lot trade: closed in full at 2R       after the partial: stop to breakeven, then the TSL trails
  forced exit on (15:10, from strategy settings), no new entries from 15:00
  allocation 20% of AVAILABLE CASH          daily-loss cutoff off
  reward 1:[box] empty (no fixed target: partial + TSL); a number closes the whole trade at 1:number

Changes apply to NEW trades only: each trade keeps a snapshot of the settings it was opened with.
Exception: the manual stop of an open trade (manual mode) can be moved at any time.

TSL rules (no look-ahead):
* A stop calculated at a candle's close protects only the following candles.
* Stops only tighten (ratchet): up for a LONG series, down for a SHORT series.
* Source OPTION: the traded option's own candles; the series is LONG (bought premium).
  Source SPOT: the index candles; CALL trades use a LONG series (stop below the index),
  PUT trades a SHORT series (stop above the index). The option is sold at its current price.
* Trigger CLOSE: exit when a candle closes beyond the stop (at that close).
  Trigger TOUCH: exit when a candle touches the stop (at the stop, or at the open if it gapped).
* Parabolic SAR also exits when it switches to the other side of price.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from market_data.resampling import Candle
from paper_trading.tsl_methods import PRESETS, PRESET_LABELS, method_stops

IST = ZoneInfo("Asia/Kolkata")
SETTINGS_FILE = "trade_management.json"
TSL_MODES = ("INDICATOR", "MANUAL")
TSL_SOURCES = ("OPTION", "SPOT")
TSL_TIMEFRAMES = ("STRATEGY", "1", "3", "5", "10", "15", "30", "60")
TSL_TRIGGERS = ("CLOSE", "TOUCH")
AFTER_PARTIAL = ("BREAKEVEN", "LOCK_1R", "KEEP")
ONE_LOT_AT_TARGET = ("CLOSE_ALL", "KEEP_TRAILING")
ALLOCATION_BASES = ("AVAILABLE_CASH", "BALANCE")
LABELS = {
    "INDICATOR": "Indicator (automatic)", "MANUAL": "Manual (I move the stop)",
    "OPTION": "Option chart (the traded CE / PE)", "SPOT": "Spot chart (the index)",
    "STRATEGY": "Same as strategy timeframe",
    "CLOSE": "Candle CLOSES beyond the stop", "TOUCH": "Price TOUCHES the stop",
    "BREAKEVEN": "Move stop to entry (breakeven), then TSL", "LOCK_1R": "Move stop to entry + 1R, then TSL",
    "KEEP": "Leave the stop, only the TSL moves it",
    "CLOSE_ALL": "Close the whole lot at the target", "KEEP_TRAILING": "Keep the lot, only trail it",
    "AVAILABLE_CASH": "Available cash", "BALANCE": "Account balance",
    **PRESET_LABELS,
}


def default_method_params() -> dict:
    return {key: dict(params) for key, (_, params) in PRESETS.items()}


@dataclass(frozen=True)
class TradeManagementSettings:
    initial_sl_pct: float = 30.0                 # % below the option premium paid
    tsl_enabled: bool = True
    tsl_mode: str = "INDICATOR"
    tsl_method: str = "CHANDELIER_9_1.5"         # one of tsl_methods.PRESETS
    method_params: dict = field(default_factory=default_method_params)   # every preset's numbers, editable
    tsl_source: str = "OPTION"
    tsl_timeframe: str = "STRATEGY"
    tsl_trigger: str = "CLOSE"
    partial_enabled: bool = True
    partial_r: float = 2.0
    partial_pct: float = 50.0
    one_lot_at_target: str = "CLOSE_ALL"
    after_partial: str = "BREAKEVEN"
    forced_exit_enabled: bool = True
    allocation_basis: str = "AVAILABLE_CASH"
    daily_loss_cutoff_enabled: bool = False
    daily_loss_cutoff_pct: float = 3.0           # % of the day's opening equity, used only when enabled
    # Reward 1 : [box] (owner rule, every strategy): a number = close the WHOLE trade at that target;
    # empty (None) = no fixed target, the partial booking (if on) and the TSL take the trade out.
    exit_target_rr: Optional[float] = None

    def __post_init__(self) -> None:
        checks = ((self.tsl_mode, TSL_MODES, "tsl_mode"), (self.tsl_source, TSL_SOURCES, "tsl_source"),
                  (str(self.tsl_timeframe), TSL_TIMEFRAMES, "tsl_timeframe"), (self.tsl_trigger, TSL_TRIGGERS, "tsl_trigger"),
                  (self.after_partial, AFTER_PARTIAL, "after_partial"),
                  (self.one_lot_at_target, ONE_LOT_AT_TARGET, "one_lot_at_target"),
                  (self.allocation_basis, ALLOCATION_BASES, "allocation_basis"))
        for value, allowed, name in checks:
            if value not in allowed:
                raise ValueError(f"{name} must be one of {allowed}")
        if self.tsl_method not in PRESETS:
            raise ValueError(f"tsl_method must be one of {tuple(PRESETS)}")
        if not 0 < self.initial_sl_pct < 100:
            raise ValueError("initial_sl_pct must be between 0 and 100")
        if not self.partial_r > 0 or not 0 < self.partial_pct < 100:
            raise ValueError("partial_r must be positive and partial_pct between 0 and 100")
        if not 0 < self.daily_loss_cutoff_pct <= 100:
            raise ValueError("daily_loss_cutoff_pct must be above 0 and at most 100")
        for flag in ("tsl_enabled", "partial_enabled", "forced_exit_enabled", "daily_loss_cutoff_enabled"):
            if not isinstance(getattr(self, flag), bool):
                raise ValueError(f"{flag} must be true or false")
        from strategies.exit_plan import parse_rr
        object.__setattr__(self, "exit_target_rr", parse_rr(self.exit_target_rr))
        if self.exit_target_rr is None and not self.tsl_enabled and not self.partial_enabled:
            raise ValueError("with an empty reward box turn on the TSL or the partial booking (otherwise only the stop exits)")
        merged = default_method_params()
        for key, params in (self.method_params or {}).items():
            if key in merged and isinstance(params, dict):
                merged[key].update(params)
        object.__setattr__(self, "method_params", merged)
        object.__setattr__(self, "tsl_timeframe", str(self.tsl_timeframe))

    # what the TSL needs
    def method(self) -> tuple[str, dict]:
        kind, _ = PRESETS[self.tsl_method]
        return kind, dict(self.method_params[self.tsl_method])

    def timeframe_minutes(self, strategy_minutes: int) -> int:
        return int(strategy_minutes) if self.tsl_timeframe == "STRATEGY" else int(self.tsl_timeframe)

    def to_dict(self) -> dict:
        return asdict(self)


class TradeManagementStore:
    """``trade_management.json`` in the index folder; the saved file wins over the defaults."""

    def __init__(self, journal_dir: str | Path | None, default: TradeManagementSettings | None = None) -> None:
        self._settings = default or TradeManagementSettings()
        self._path = None if journal_dir is None else Path(journal_dir) / SETTINGS_FILE
        self._mtime = None
        if self._path is not None and self._path.exists():
            try:
                self._settings = replace(self._settings, **json.loads(self._path.read_text(encoding="utf-8")))
            except (ValueError, TypeError) as exc:
                raise ValueError(f"{self._path} is invalid ({exc}); fix or delete it to use the defaults.") from exc
            self._mtime = self._path.stat().st_mtime

    @property
    def settings(self) -> TradeManagementSettings:
        return self._settings

    @property
    def path(self) -> Path | None:
        return self._path

    def refresh(self) -> TradeManagementSettings:
        """Pick up a change saved by the dashboard; a broken file keeps the last good settings."""
        if self._path is None or not self._path.exists():
            return self._settings
        mtime = self._path.stat().st_mtime
        if mtime != self._mtime:
            self._mtime = mtime
            try:
                self._settings = replace(self._settings, **json.loads(self._path.read_text(encoding="utf-8")))
            except (ValueError, TypeError):
                pass
        return self._settings

    def update(self, **changes) -> TradeManagementSettings:
        self._settings = replace(self._settings, **changes)          # validates
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._settings.to_dict(), indent=2), encoding="utf-8")
            self._mtime = self._path.stat().st_mtime
        return self._settings


# ------------------------------------------------------------------ candles for the TSL

def session_bars(minutes: Sequence, timeframe: int, *, now: int | None = None) -> list[Candle]:
    """Group 1-minute candles into ``timeframe``-minute candles from 09:15 (each day).

    A candle counts as finished when a later minute exists after its end (or ``now`` has passed
    its end). Minutes missing inside a candle (thin option trading) do not block it.
    """
    if timeframe == 1 and now is None:
        return [Candle(m.timestamp, m.open, m.high, m.low, m.close, getattr(m, "volume", None)) for m in minutes]
    groups: dict[int, list] = {}
    last_ts = None
    for m in sorted(minutes, key=lambda c: c.timestamp):
        local = datetime.fromtimestamp(int(m.timestamp), IST)
        open_ts = int(local.replace(hour=9, minute=15, second=0, microsecond=0).timestamp())
        start = open_ts + ((int(m.timestamp) - open_ts) // (timeframe * 60)) * timeframe * 60
        groups.setdefault(start, []).append(m)
        last_ts = int(m.timestamp)
    out = []
    for start in sorted(groups):
        end = start + timeframe * 60
        session_end = int(datetime.fromtimestamp(start, IST).replace(hour=15, minute=30, second=0).timestamp())
        end = min(end, session_end)
        # finished once its last minute (or any later minute) has arrived, or the clock passed its end
        finished = (last_ts is not None and last_ts + 60 >= end) or (now is not None and now >= end)
        if not finished:
            continue
        g = groups[start]
        vols = [getattr(c, "volume", None) for c in g]
        out.append(Candle(start, g[0].open, max(c.high for c in g), min(c.low for c in g), g[-1].close,
                          None if any(v is None for v in vols) else sum(vols)))
    return out


def bar_end(bar_ts: int, timeframe: int) -> int:
    session_end = int(datetime.fromtimestamp(bar_ts, IST).replace(hour=15, minute=30, second=0).timestamp())
    return min(int(bar_ts) + timeframe * 60, session_end)


# ------------------------------------------------------------------ the per-trade trail

@dataclass
class TslExit:
    timestamp: int          # close time of the candle that triggered the exit
    reason: str             # TSL_CLOSE, TSL_TOUCH, SAR_FLIP or MANUAL_STOP
    source_price: float     # level on the TSL chart (stop, close or open)
    option_price: Optional[float]   # fill on the option chart when the TSL runs on the option itself
    detail: str


class TslTracker:
    """One trade's trailing stop. Feed it the TSL chart's finished candles (history included)."""

    def __init__(self, *, trade_id: str, settings: TradeManagementSettings, side: str, entry_timestamp: int,
                 entry_price: float, timeframe: int, method: Optional[tuple[str, dict]] = None,
                 label: str | None = None) -> None:
        self.trade_id, self.settings, self.side = trade_id, settings, side.upper()
        self.entry_timestamp, self.entry_price, self.timeframe = int(entry_timestamp), float(entry_price), int(timeframe)
        self.kind, self.params = method or settings.method()
        self.label = label or LABELS.get(settings.tsl_method, settings.tsl_method)
        self.stop: Optional[float] = None
        self.manual_stop: Optional[float] = None
        self.last_bar_ts: Optional[int] = None
        self.exited: Optional[TslExit] = None

    @property
    def long(self) -> bool:
        return self.side == "LONG"

    def _tighter(self, a: Optional[float], b: Optional[float]) -> Optional[float]:
        if a is None:
            return b
        if b is None:
            return a
        return max(a, b) if self.long else min(a, b)

    def current_stop(self) -> Optional[float]:
        if self.settings.tsl_mode == "MANUAL":
            return self.manual_stop
        return self.stop

    def on_bars(self, bars: Sequence[Candle]) -> Optional[TslExit]:
        """Process every finished candle not seen before; returns the exit when one happens."""
        if self.exited is not None or not bars:
            return self.exited
        new = [i for i, b in enumerate(bars) if self.last_bar_ts is None or b.timestamp > self.last_bar_ts]
        if not new:
            return None
        points = None
        if self.settings.tsl_mode == "INDICATOR":
            points = method_stops(self.kind, self.params, bars, self.side, entry_price=self.entry_price)
        for i in new:
            bar = bars[i]
            closes_at = bar_end(bar.timestamp, self.timeframe)
            self.last_bar_ts = bar.timestamp
            in_trade = closes_at > self.entry_timestamp
            stop = self.current_stop()
            if in_trade and stop is not None:
                hit = self._check(bar, stop, closes_at)
                if hit is not None:
                    self.exited = hit
                    return hit
            if points is not None:
                point = points[i]
                if in_trade and point.against:
                    self.exited = TslExit(closes_at, "SAR_FLIP", bar.close, bar.close,
                                          f"{self.label}: SAR switched sides; exit at the close {bar.close}")
                    return self.exited
                if point.stop is not None:
                    # before the entry candle the stop simply follows the method; from entry it only tightens
                    self.stop = point.stop if not in_trade or self.stop is None else self._tighter(self.stop, point.stop)
        return None

    def _check(self, bar: Candle, stop: float, closes_at: int) -> Optional[TslExit]:
        manual = self.settings.tsl_mode == "MANUAL"
        reason_name = "MANUAL_STOP" if manual else ("TSL_CLOSE" if self.settings.tsl_trigger == "CLOSE" else "TSL_TOUCH")
        name = "Manual stop" if manual else self.label
        if self.settings.tsl_trigger == "CLOSE":
            beyond = bar.close < stop if self.long else bar.close > stop
            if beyond:
                return TslExit(closes_at, reason_name, bar.close, bar.close,
                               f"{name}: candle closed at {bar.close} beyond the stop {round(stop, 2)}")
            return None
        touched = bar.low <= stop if self.long else bar.high >= stop
        if not touched:
            return None
        gapped = bar.open < stop if self.long else bar.open > stop
        level = bar.open if gapped else stop
        return TslExit(bar.timestamp, reason_name, level, level,
                       f"{name}: price touched the stop {round(stop, 2)}" + (" (opened beyond it)" if gapped else ""))

    def state(self) -> dict:
        return {"stop": self.stop, "manual_stop": self.manual_stop, "last_bar_ts": self.last_bar_ts}


__all__ = [
    "AFTER_PARTIAL", "ALLOCATION_BASES", "LABELS", "ONE_LOT_AT_TARGET", "SETTINGS_FILE", "TSL_MODES", "TSL_SOURCES",
    "TSL_TIMEFRAMES", "TSL_TRIGGERS", "TradeManagementSettings", "TradeManagementStore", "TslExit", "TslTracker",
    "bar_end", "default_method_params", "session_bars",
]
