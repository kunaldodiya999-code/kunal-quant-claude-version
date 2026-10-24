"""Opening Breakout V2 execution policy.

This layer converts validated strategy signals into broker-neutral order
intents. It deliberately does not call FYERS, so Backtest/Paper/Live adapters
can consume the same intent model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from execution.opening_breakout_state import OrderIntent
from research.opening_breakout_1m_v2 import Signal


@dataclass(frozen=True)
class V2ExecutionPolicy:
    entry_buffer_points: float = 1.0
    exit_buffer_points: float = 2.0
    max_slippage_points: float = 2.0
    fill_timeout_seconds: int = 10
    entry_start_hhmm: str = "09:15"
    entry_end_hhmm: str = "15:10"
    force_exit_hhmm: str = "15:15"

    def __post_init__(self) -> None:
        if self.entry_buffer_points < 0 or self.exit_buffer_points < 0:
            raise ValueError("order buffers must be >= 0")
        if self.max_slippage_points < 0:
            raise ValueError("max_slippage_points must be >= 0")
        if self.fill_timeout_seconds <= 0:
            raise ValueError("fill_timeout_seconds must be > 0")


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = (int(x) for x in value.split(":"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM: {value}")
    return hour, minute


def _inside(timestamp: datetime, start: str, end: str) -> bool:
    current = timestamp.hour * 60 + timestamp.minute
    sh, sm = _parse_hhmm(start)
    eh, em = _parse_hhmm(end)
    return sh * 60 + sm <= current <= eh * 60 + em


def entry_window_open(timestamp: datetime, policy: V2ExecutionPolicy) -> bool:
    return _inside(timestamp, policy.entry_start_hhmm, policy.entry_end_hhmm)


def force_exit_due(timestamp: datetime, policy: V2ExecutionPolicy) -> bool:
    fh, fm = _parse_hhmm(policy.force_exit_hhmm)
    return timestamp.hour * 60 + timestamp.minute >= fh * 60 + fm


def entry_side(signal: Signal) -> str:
    """Map option signals to BUY and cash/futures signals to direction side."""
    if signal.instrument in {"CALL", "PUT"}:
        return "BUY"
    return "BUY" if signal.direction == "LONG" else "SELL"


def exit_side(signal: Signal) -> str:
    return "SELL" if entry_side(signal) == "BUY" else "BUY"


def build_entry_intent(
    signal: Signal,
    quantity: int,
    ltp: float,
    policy: V2ExecutionPolicy,
) -> OrderIntent:
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    return OrderIntent(
        side=entry_side(signal),
        quantity=quantity,
        limit_price=(
            ltp + policy.entry_buffer_points
            if entry_side(signal) == "BUY"
            else ltp - policy.entry_buffer_points
        ),
        reason="OPENING_BREAKOUT_ENTRY",
    )


def build_exit_intent(
    signal: Signal,
    quantity: int,
    trigger_price: float,
    reason: str,
    policy: V2ExecutionPolicy,
) -> OrderIntent:
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    direction = signal.direction
    return OrderIntent(
        side=exit_side(signal),
        quantity=quantity,
        limit_price=(
            trigger_price - policy.exit_buffer_points
            if exit_side(signal) == "SELL"
            else trigger_price + policy.exit_buffer_points
        ),
        reason=reason,
    )
