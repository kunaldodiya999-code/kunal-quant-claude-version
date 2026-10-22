"""Session controls: market segments, entry windows, forced exit, daily loss cap, kill switch.

Rules (owner-specified, all configurable):

* Kill switch: ONE action. The owner picks which segments to stop (any mix of
  NSE & BSE F&O, Equity, Currency, Commodity, or all). New entries in those
  segments stop for ``kill_hours`` (default 12). It cannot be shortened or
  undone from the app; open positions are left alone. The only override is
  deleting ``controls_state.json`` by hand. An unreadable state file fails
  closed (all entries blocked).
* Entry window per segment. F&O default 09:30 to 15:00 IST, forced exit 15:10 IST.
  Equity has the same window and the same 15:10 forced exit. Commodity and Currency have
  no forced exit and no entry cutoff set here. All values are meant to be edited.
* Forced exit applies ONLY to segments with a ``force_exit`` time (F&O by default).
* Daily loss cap is OFF by default. It can be an absolute rupee amount, a percent of the
  day's OPENING equity, or both (the stricter limit applies). It watches live net
  liquidation value (see account.py): realised + unrealised mark-to-market - costs. An open
  drawdown counts. When it trips, NEW entries stop for the rest of the IST day; open
  positions are left to their own stops. With the cap on, entries are also blocked if an
  open position has no live price, because the account cannot be valued.

Nothing here contacts a broker.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionTradeExit
from paper_trading.account import EquitySnapshot, PaperAccount
from paper_trading.engine import PaperStrategyId, PaperTradingEngine

IST = ZoneInfo("Asia/Kolkata")
EVENT_FIELDS = ["recorded_at", "event_timestamp", "event_type", "detail"]


class Segment(str, Enum):
    FNO = "FNO"
    EQUITY = "EQUITY"
    CURRENCY = "CURRENCY"
    COMMODITY = "COMMODITY"

    @property
    def label(self) -> str:
        return {"FNO": "NSE & BSE F&O", "EQUITY": "Equity",
                "CURRENCY": "Currency", "COMMODITY": "Commodity"}[self.value]


ALL_SEGMENTS: tuple[Segment, ...] = tuple(Segment)


def parse_hhmm(text: str) -> time:
    try:
        hour, minute = (int(part) for part in str(text).split(":"))
        return time(hour, minute)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Expected HH:MM, got {text!r}.") from exc


@dataclass(frozen=True)
class SegmentRules:
    entry_start: time = time(9, 30)
    entry_end: Optional[time] = time(15, 0)     # None: controls set no entry cutoff
    force_exit: Optional[time] = None           # None: open positions are never force-closed

    def __post_init__(self) -> None:
        if self.entry_end is not None and not self.entry_start < self.entry_end:
            raise ValueError("entry_start must be earlier than entry_end.")
        if self.force_exit is not None:
            floor = self.entry_end if self.entry_end is not None else self.entry_start
            if self.force_exit < floor or self.force_exit == self.entry_start:
                raise ValueError("force_exit must not be earlier than the entry cutoff.")


def default_rules() -> dict[Segment, SegmentRules]:
    return {
        Segment.FNO: SegmentRules(time(9, 30), time(15, 0), time(15, 10)),
        Segment.EQUITY: SegmentRules(time(9, 30), time(15, 0), time(15, 10)),
        Segment.CURRENCY: SegmentRules(time(9, 30), None, None),
        Segment.COMMODITY: SegmentRules(time(9, 30), None, None),
    }


@dataclass(frozen=True)
class SessionControlsConfig:
    rules: Mapping[Segment, SegmentRules] = field(default_factory=default_rules)
    max_daily_loss_amount: Optional[float] = None   # rupees
    max_daily_loss_pct: Optional[float] = None      # percent of the day's opening equity
    kill_hours: float = 12.0

    def __post_init__(self) -> None:
        if set(self.rules) != set(Segment):
            raise ValueError("rules must define every segment.")
        if not (isfinite(self.kill_hours) and self.kill_hours > 0):
            raise ValueError("kill_hours must be positive.")
        amount, pct = self.max_daily_loss_amount, self.max_daily_loss_pct
        if amount is not None and not (isfinite(amount) and amount > 0):
            raise ValueError("max_daily_loss_amount must be positive or None.")
        if pct is not None and not (isfinite(pct) and 0 < pct <= 100):
            raise ValueError("max_daily_loss_pct must be above 0 and at most 100.")

    @property
    def loss_cap_enabled(self) -> bool:
        return self.max_daily_loss_amount is not None or self.max_daily_loss_pct is not None

    def daily_loss_limit(self, opening_equity: float) -> Optional[float]:
        """Rupee limit for a day: the stricter of the amount and the percent of opening equity."""
        limits = []
        if self.max_daily_loss_amount is not None:
            limits.append(self.max_daily_loss_amount)
        if self.max_daily_loss_pct is not None:
            limits.append(opening_equity * self.max_daily_loss_pct / 100.0)
        return min(limits) if limits else None

    @classmethod
    def from_hhmm(cls, entry_start: str, entry_end: str, force_exit: str, **kwargs
                  ) -> "SessionControlsConfig":
        """Set the F&O and equity window and forced exit; other segments keep defaults."""
        rules = default_rules()
        start, end = parse_hhmm(entry_start), parse_hhmm(entry_end)
        rules[Segment.FNO] = SegmentRules(start, end, parse_hhmm(force_exit))
        rules[Segment.EQUITY] = SegmentRules(start, end, parse_hhmm(force_exit))
        return cls(rules=rules, **kwargs)


@dataclass(frozen=True)
class ForceExitResult:
    closed: tuple[tuple[PaperStrategyId, OptionTradeExit], ...]
    unpriced: tuple[PaperStrategyId, ...]  # still open: no price was supplied for them


def _segments(values: Iterable[Segment | str]) -> set[Segment]:
    if isinstance(values, (str, Segment)):
        values = [values]
    try:
        chosen = {Segment(v) for v in values}
    except ValueError as exc:
        raise ValueError(f"Unknown segment: {exc}") from exc
    if not chosen:
        raise ValueError("Choose at least one segment to kill.")
    return chosen


class SessionControls:
    def __init__(self, config: SessionControlsConfig | None = None, *,
                 journal_dir: str | Path | None = None) -> None:
        self.config = config or SessionControlsConfig()
        self.engine: PaperTradingEngine | None = None
        self.account: PaperAccount | None = None
        self._kills: dict[Segment, int] = {}   # segment -> epoch second the kill ends
        self._corrupt = False
        self._dir = Path(journal_dir) if journal_dir is not None else None
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load_state()

    def bind(self, engine: PaperTradingEngine, account: PaperAccount | None = None) -> None:
        self.engine = engine
        self.account = account

    def live_snapshot(self, timestamp: int, marks=None) -> EquitySnapshot | None:
        """Live equity for the UI and the loss cap, or None if no account is attached."""
        return None if self.account is None else self.account.snapshot(timestamp, marks)

    # ---- persistence --------------------------------------------------
    @property
    def _state_path(self) -> Optional[Path]:
        return None if self._dir is None else self._dir / "controls_state.json"

    @property
    def events_path(self) -> Optional[Path]:
        return None if self._dir is None else self._dir / "controls_events.csv"

    def _load_state(self) -> None:
        path = self._state_path
        if path is None or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._kills = {Segment(k): int(v) for k, v in data["kills"].items()}
        except (ValueError, KeyError, TypeError, AttributeError):
            self._kills, self._corrupt = {}, True   # fail closed

    def _save_state(self) -> None:
        path = self._state_path
        if path is not None:
            path.write_text(json.dumps({"kills": {s.value: u for s, u in self._kills.items()}}),
                            encoding="utf-8")

    def _log(self, event_type: str, detail: str, timestamp: int | None = None) -> None:
        path = self.events_path
        if path is None:
            return
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
            if is_new:
                writer.writeheader()
            writer.writerow({
                "recorded_at": datetime.now(IST).isoformat(timespec="seconds"),
                "event_timestamp": "" if timestamp is None else int(timestamp),
                "event_type": event_type, "detail": detail,
            })

    # ---- kill switch --------------------------------------------------
    @staticmethod
    def _ist(timestamp: int) -> datetime:
        return datetime.fromtimestamp(int(timestamp), IST)

    def kill(self, segments: Iterable[Segment | str], *, timestamp: int) -> dict[Segment, int]:
        """Stop NEW entries in the chosen segments for ``kill_hours``. Cannot shorten an active kill."""
        chosen = _segments(segments)
        until = int(timestamp) + int(self.config.kill_hours * 3600)
        for segment in chosen:
            self._kills[segment] = max(self._kills.get(segment, 0), until)
        self._save_state()
        names = ", ".join(s.label for s in sorted(chosen, key=lambda s: s.value))
        self._log("KILL", f"New entries stopped for {names} until {self._ist(until):%Y-%m-%d %H:%M} IST.",
                  timestamp)
        return self.active_kills(timestamp)

    def active_kills(self, timestamp: int) -> dict[Segment, int]:
        return {s: u for s, u in self._kills.items() if int(timestamp) < u}

    # ---- rules --------------------------------------------------------
    def entry_block_reason(self, timestamp: int, segment: Segment | str = Segment.FNO,
                           marks=None) -> Optional[str]:
        """Return why a new entry in ``segment`` is not allowed now, or None if it is."""
        if self._corrupt:
            return "controls_state.json is unreadable; entries are blocked until it is repaired or removed."
        seg = Segment(segment)
        until = self._kills.get(seg)
        if until is not None and int(timestamp) < until:
            return f"Kill switch active for {seg.label} until {self._ist(until):%d %b %H:%M} IST."
        rules = self.config.rules[seg]
        clock = self._ist(timestamp).time()
        if clock < rules.entry_start:
            return f"Before entry window for {seg.label} (opens {rules.entry_start:%H:%M} IST)."
        if rules.entry_end is not None and clock >= rules.entry_end:
            return f"After entry cutoff for {seg.label} ({rules.entry_end:%H:%M} IST)."
        return self._loss_cap_reason(timestamp, marks)

    def _loss_cap_reason(self, timestamp: int, marks) -> Optional[str]:
        if not self.config.loss_cap_enabled:
            return None
        if self.account is None:
            return "Daily loss limit is on but no account is attached; entries are blocked."
        snap = self.account.snapshot(timestamp, marks)
        if snap.marks_missing:
            names = ", ".join(s.value for s in snap.marks_missing)
            return f"Daily loss limit is on but open position(s) have no live price ({names}); account cannot be valued."
        limit = self.config.daily_loss_limit(snap.opening_equity)
        if snap.day_pnl <= -limit:
            return (f"Daily loss limit reached (today {snap.day_pnl:,.0f} on opening equity "
                    f"{snap.opening_equity:,.0f}; limit {limit:,.0f}).")
        return None

    def exits_due(self, timestamp: int, segment: Segment | str = Segment.FNO) -> bool:
        """True when this segment has a forced-exit time and it has passed."""
        force = self.config.rules[Segment(segment)].force_exit
        return force is not None and self._ist(timestamp).time() >= force

    def close_due_positions(
        self, engine: PaperTradingEngine, *, timestamp: int,
        prices: Mapping[PaperStrategyId | str, float],
        segment_of: Callable[[PaperStrategyId], Segment] | None = None,
    ) -> ForceExitResult:
        """Force-close open positions whose segment has reached its forced-exit time.

        Positions in segments without a forced-exit time (commodity, currency) are
        never touched. ``segment_of`` defaults to F&O: the paper engine only trades
        NIFTY options today.
        """
        segment_of = segment_of or (lambda strategy: Segment.FNO)
        by_value = {getattr(k, "value", k): float(v) for k, v in prices.items()}
        closed, unpriced = [], []
        for strategy in PaperStrategyId:
            if engine.open_trade(strategy) is None:
                continue
            seg = Segment(segment_of(strategy))
            if not self.exits_due(timestamp, seg):
                continue
            price = by_value.get(strategy.value)
            if price is None:
                unpriced.append(strategy)
                self._log("FORCE_EXIT_NO_PRICE", f"{strategy.value} ({seg.label}) still open: no price supplied.",
                          timestamp)
                continue
            exit_event = engine.force_close(strategy, timestamp=timestamp, price=price)
            if exit_event is not None:
                closed.append((strategy, exit_event))
                self._log("FORCE_EXIT", f"{strategy.value} ({seg.label}) closed at {price}.", timestamp)
        return ForceExitResult(closed=tuple(closed), unpriced=tuple(unpriced))


__all__ = [
    "ALL_SEGMENTS", "ForceExitResult", "Segment", "SegmentRules", "SessionControls",
    "SessionControlsConfig", "default_rules", "parse_hhmm",
]
