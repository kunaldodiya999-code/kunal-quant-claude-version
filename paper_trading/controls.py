"""Session controls for paper trading: entry window, forced exit, daily loss, kill switch.

Defaults mirror the handover candidates (entries 09:45 to 15:00 IST, forced
exit 15:10 IST). They are CANDIDATE parameters until the owner approves them,
so every value is configurable and validated. Nothing here contacts a broker.

* The kill switch survives a restart: its state is written to
  ``controls_state.json``. An unreadable state file fails closed (halted).
* Daily loss counts REALISED gross P&L of trades entered today (IST). Costs
  and open-position mark-to-market are not included yet.
* Every halt, resume and forced exit is appended to ``controls_events.csv``.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Mapping, Optional
from zoneinfo import ZoneInfo

from backtest.option_trade_lifecycle import OptionTradeExit
from paper_trading.engine import PaperStrategyId, PaperTradingEngine

IST = ZoneInfo("Asia/Kolkata")
EVENT_FIELDS = ["recorded_at", "event_timestamp", "event_type", "detail"]


class HaltMode(str, Enum):
    BLOCK_ENTRIES = "BLOCK_ENTRIES"  # no new entries; open positions keep their stop and target
    FLATTEN = "FLATTEN"              # no new entries and open positions are closed at the next supplied price


def parse_hhmm(text: str) -> time:
    try:
        hour, minute = (int(part) for part in str(text).split(":"))
        return time(hour, minute)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Expected HH:MM, got {text!r}.") from exc


@dataclass(frozen=True)
class SessionControlsConfig:
    entry_start: time = time(9, 45)
    entry_end: time = time(15, 0)
    force_exit: time = time(15, 10)
    max_daily_loss: Optional[float] = None  # rupees, positive; None disables the cap

    def __post_init__(self) -> None:
        if not (self.entry_start < self.entry_end <= self.force_exit):
            raise ValueError("Require entry_start < entry_end <= force_exit.")
        if self.max_daily_loss is not None and not (
            isfinite(self.max_daily_loss) and self.max_daily_loss > 0
        ):
            raise ValueError("max_daily_loss must be a positive number or None.")

    @classmethod
    def from_hhmm(cls, entry_start: str, entry_end: str, force_exit: str,
                  max_daily_loss: Optional[float] = None) -> "SessionControlsConfig":
        return cls(parse_hhmm(entry_start), parse_hhmm(entry_end),
                   parse_hhmm(force_exit), max_daily_loss)


@dataclass(frozen=True)
class ForceExitResult:
    closed: tuple[tuple[PaperStrategyId, OptionTradeExit], ...]
    unpriced: tuple[PaperStrategyId, ...]  # still open: no price was supplied for them


class SessionControls:
    def __init__(self, config: SessionControlsConfig | None = None, *,
                 journal_dir: str | Path | None = None) -> None:
        self.config = config or SessionControlsConfig()
        self.engine: PaperTradingEngine | None = None
        self.halted = False
        self.halt_reason = ""
        self.halt_mode = HaltMode.BLOCK_ENTRIES
        self._dir = Path(journal_dir) if journal_dir is not None else None
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._load_state()

    # ---- wiring -------------------------------------------------------
    def bind(self, engine: PaperTradingEngine) -> None:
        self.engine = engine

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
            self.halted = bool(data["halted"])
            self.halt_reason = str(data.get("reason", ""))
            self.halt_mode = HaltMode(data.get("mode", HaltMode.BLOCK_ENTRIES.value))
        except (ValueError, KeyError, TypeError):
            # Fail closed: a damaged kill-switch file must never re-enable trading.
            self.halted = True
            self.halt_reason = "controls_state.json is unreadable; halted for safety."
            self.halt_mode = HaltMode.BLOCK_ENTRIES

    def _save_state(self) -> None:
        path = self._state_path
        if path is not None:
            path.write_text(json.dumps({
                "halted": self.halted, "reason": self.halt_reason, "mode": self.halt_mode.value,
            }), encoding="utf-8")

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
    def halt(self, reason: str, *, mode: HaltMode = HaltMode.BLOCK_ENTRIES,
             timestamp: int | None = None) -> None:
        if not str(reason).strip():
            raise ValueError("A halt needs a reason.")
        self.halted, self.halt_reason, self.halt_mode = True, str(reason).strip(), HaltMode(mode)
        self._save_state()
        self._log("HALT", f"{self.halt_mode.value}: {self.halt_reason}", timestamp)

    def resume(self, *, timestamp: int | None = None) -> None:
        self.halted, self.halt_reason, self.halt_mode = False, "", HaltMode.BLOCK_ENTRIES
        self._save_state()
        self._log("RESUME", "Trading resumed by operator.", timestamp)

    # ---- rules --------------------------------------------------------
    @staticmethod
    def _ist(timestamp: int) -> datetime:
        return datetime.fromtimestamp(int(timestamp), IST)

    def realized_pnl_today(self, timestamp: int) -> float:
        if self.engine is None:
            return 0.0
        day = self._ist(timestamp).date()
        return sum(
            record.position.gross_pnl for record in self.engine.all_trades()
            if self._ist(record.entry_timestamp).date() == day
        )

    def entry_block_reason(self, timestamp: int) -> Optional[str]:
        """Return why a new entry is not allowed at this time, or None if it is."""
        if self.halted:
            return f"Trading halted ({self.halt_mode.value}): {self.halt_reason}"
        clock = self._ist(timestamp).time()
        if clock < self.config.entry_start:
            return f"Before entry window (opens {self.config.entry_start:%H:%M} IST)."
        if clock >= self.config.entry_end:
            return f"After entry cutoff ({self.config.entry_end:%H:%M} IST)."
        cap = self.config.max_daily_loss
        if cap is not None:
            pnl = self.realized_pnl_today(timestamp)
            if pnl <= -cap:
                return f"Daily loss limit reached (realised {pnl:,.0f} against a cap of {cap:,.0f})."
        return None

    def force_exit_due(self, timestamp: int) -> bool:
        return self._ist(timestamp).time() >= self.config.force_exit

    def exits_due(self, timestamp: int) -> bool:
        return self.force_exit_due(timestamp) or (self.halted and self.halt_mode == HaltMode.FLATTEN)

    def close_due_positions(
        self, engine: PaperTradingEngine, *, timestamp: int,
        prices: Mapping[PaperStrategyId | str, float],
    ) -> ForceExitResult:
        """Close open paper positions when the forced exit or a FLATTEN halt is due."""
        if not self.exits_due(timestamp):
            return ForceExitResult(closed=(), unpriced=())
        cause = "Forced session exit" if self.force_exit_due(timestamp) else f"Kill switch: {self.halt_reason}"
        by_value = {getattr(k, "value", k): float(v) for k, v in prices.items()}
        closed, unpriced = [], []
        for strategy in PaperStrategyId:
            if engine.open_trade(strategy) is None:
                continue
            price = by_value.get(strategy.value)
            if price is None:
                unpriced.append(strategy)
                self._log("FORCE_EXIT_NO_PRICE", f"{strategy.value} still open: no price supplied.", timestamp)
                continue
            exit_event = engine.force_close(strategy, timestamp=timestamp, price=price)
            if exit_event is not None:
                closed.append((strategy, exit_event))
                self._log("FORCE_EXIT", f"{strategy.value} closed at {price}: {cause}.", timestamp)
        return ForceExitResult(closed=tuple(closed), unpriced=tuple(unpriced))


__all__ = ["ForceExitResult", "HaltMode", "SessionControls", "SessionControlsConfig", "parse_hhmm"]
