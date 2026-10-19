"""Broker-neutral chart trade-tool state for Opening Breakout V2.

The module is intentionally UI-agnostic.  A chart adapter can render these
levels as draggable lines and feed drag events back through the override
methods.  Manual chart changes always take precedence over filter-derived
SL/TP values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Literal


class ChartOrderState(str, Enum):
    PENDING_ENTRY = "PENDING_ENTRY"
    FILLED = "FILLED"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ChartLine:
    price: float
    kind: Literal["ENTRY", "SL", "TP"]
    draggable: bool = True
    overridden: bool = False


@dataclass
class TradeChartTool:
    symbol: str
    side: Literal["LONG", "SHORT"]
    quantity: int
    entry_price: float
    planned_sl: float | None = None
    planned_tp: float | None = None
    state: ChartOrderState = ChartOrderState.PENDING_ENTRY
    manual_sl: float | None = None
    manual_tp: float | None = None

    @property
    def effective_sl(self) -> float | None:
        return self.manual_sl if self.manual_sl is not None else self.planned_sl

    @property
    def effective_tp(self) -> float | None:
        return self.manual_tp if self.manual_tp is not None else self.planned_tp

    @property
    def lines(self) -> tuple[ChartLine, ...]:
        lines = [ChartLine(self.entry_price, "ENTRY", draggable=False)]
        if self.effective_sl is not None:
            lines.append(
                ChartLine(
                    self.effective_sl,
                    "SL",
                    draggable=True,
                    overridden=self.manual_sl is not None,
                )
            )
        if self.effective_tp is not None:
            lines.append(
                ChartLine(
                    self.effective_tp,
                    "TP",
                    draggable=True,
                    overridden=self.manual_tp is not None,
                )
            )
        return tuple(lines)

    def override_sl(self, price: float) -> None:
        if price <= 0:
            raise ValueError("SL price must be > 0")
        self.manual_sl = float(price)

    def override_tp(self, price: float) -> None:
        if price <= 0:
            raise ValueError("TP price must be > 0")
        self.manual_tp = float(price)

    def clear_sl_override(self) -> None:
        self.manual_sl = None

    def clear_tp_override(self) -> None:
        self.manual_tp = None

    def seed_manual_levels(self, sl_points: float, tp_points: float) -> None:
        """Populate draggable protection levels when strategy SL/TP are OFF.

        The seed is immediately treated as a manual chart override and can be
        dragged at any time. It is intentionally explicit rather than hidden
        inside the strategy filter engine.
        """
        if sl_points <= 0 or tp_points <= 0:
            raise ValueError("chart seed points must be > 0")
        if self.side == "LONG":
            self.manual_sl = self.entry_price - sl_points
            self.manual_tp = self.entry_price + tp_points
        else:
            self.manual_sl = self.entry_price + sl_points
            self.manual_tp = self.entry_price - tp_points

    def mark_filled(self) -> None:
        if self.state != ChartOrderState.PENDING_ENTRY:
            raise ValueError("only pending entry can become filled")
        self.state = ChartOrderState.FILLED

    def mark_exit_pending(self) -> None:
        if self.state != ChartOrderState.FILLED:
            raise ValueError("only a filled position can request exit")
        self.state = ChartOrderState.EXIT_PENDING

    def mark_closed(self) -> None:
        if self.state != ChartOrderState.EXIT_PENDING:
            raise ValueError("only exit-pending can become closed")
        self.state = ChartOrderState.CLOSED

    def cancel(self) -> None:
        if self.state not in {ChartOrderState.PENDING_ENTRY, ChartOrderState.FILLED}:
            raise ValueError("trade cannot be cancelled from current state")
        self.state = ChartOrderState.CANCELLED


@dataclass(frozen=True)
class EntryWindow:
    start: time
    end: time
    force_exit: time

    @classmethod
    def from_hhmm(cls, start: str, end: str, force_exit: str) -> "EntryWindow":
        def parse(value: str) -> time:
            hour, minute = (int(x) for x in value.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError(f"invalid HH:MM: {value}")
            return time(hour=hour, minute=minute)

        return cls(parse(start), parse(end), parse(force_exit))

    def accepts_entry(self, timestamp: datetime) -> bool:
        current = timestamp.time()
        return self.start <= current <= self.end

    def requires_force_exit(self, timestamp: datetime) -> bool:
        return timestamp.time() >= self.force_exit
