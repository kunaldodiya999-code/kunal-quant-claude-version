"""Experimental execution/state machine for Opening Breakout V1.

Broker-neutral. A broker adapter can map these intents to FYERS/Paper/Live.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class OrderState(str, Enum):
    PENDING_ENTRY = "PENDING_ENTRY"
    FILLED = "FILLED"
    EXIT_PENDING = "EXIT_PENDING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    VWAP = "VWAP"
    SAFETY_CUTOFF = "SAFETY_CUTOFF"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class OrderIntent:
    side: Literal["BUY", "SELL"]
    quantity: int
    limit_price: float
    reason: str


@dataclass(frozen=True)
class ExecutionConfig:
    entry_buffer_points: float = 2.0
    exit_buffer_points: float = 2.0
    max_slippage_points: float = 2.0
    fill_timeout_seconds: int = 10
    square_off_minutes: int = 5

    def __post_init__(self) -> None:
        if self.entry_buffer_points < 0 or self.exit_buffer_points < 0:
            raise ValueError("order buffers must be >= 0")
        if self.max_slippage_points < 0:
            raise ValueError("max_slippage_points must be >= 0")
        if self.fill_timeout_seconds <= 0:
            raise ValueError("fill_timeout_seconds must be > 0")
        if self.square_off_minutes <= 0:
            raise ValueError("square_off_minutes must be > 0")


@dataclass
class ExecutionState:
    state: OrderState = OrderState.PENDING_ENTRY
    entry_order: OrderIntent | None = None
    exit_order: OrderIntent | None = None
    fill_price: float | None = None
    closed_price: float | None = None
    exit_reason: ExitReason | None = None

    def mark_filled(self, fill_price: float) -> None:
        if self.state != OrderState.PENDING_ENTRY:
            raise ValueError("Only a pending entry can become filled")
        if fill_price <= 0:
            raise ValueError("fill_price must be > 0")
        self.fill_price = float(fill_price)
        self.state = OrderState.FILLED

    def request_exit(self, intent: OrderIntent, reason: ExitReason) -> None:
        if self.state != OrderState.FILLED:
            raise ValueError("Only a filled position can request an exit")
        self.exit_order = intent
        self.exit_reason = reason
        self.state = OrderState.EXIT_PENDING

    def mark_closed(self, closed_price: float) -> None:
        if self.state != OrderState.EXIT_PENDING:
            raise ValueError("Only an exit-pending position can become closed")
        if closed_price <= 0:
            raise ValueError("closed_price must be > 0")
        self.closed_price = float(closed_price)
        self.state = OrderState.CLOSED

    def cancel_entry(self) -> None:
        if self.state != OrderState.PENDING_ENTRY:
            raise ValueError("Only a pending entry can be cancelled")
        self.state = OrderState.CANCELLED

    def reject_entry(self) -> None:
        if self.state != OrderState.PENDING_ENTRY:
            raise ValueError("Only a pending entry can be rejected")
        self.state = OrderState.REJECTED
