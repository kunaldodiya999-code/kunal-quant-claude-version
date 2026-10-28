"""Order policy and limit-price rules (pure functions, no network)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

BUFFER_UNITS = ("POINTS", "TICKS", "PERCENT")


@dataclass(frozen=True)
class LiveOrderPolicy:
    entry_buffer: float = 1.0            # BUY limit = reference + buffer
    exit_buffer: float = 2.0             # SELL limit = reference - buffer
    buffer_unit: str = "POINTS"          # POINTS, TICKS or PERCENT of the reference price
    tick_size: float = 0.05              # NIFTY options
    wait_seconds: float = 2.0            # wait for a fill before re-pricing
    max_reprice_attempts: int = 3
    max_entry_chase_points: float = 1.0  # first limit = CMP + 1, re-priced up to CMP + 1 + this at most (owner 27 Oct: CMP 100 -> 101 or 102, never above)
    product_type: str = "INTRADAY"
    max_lots_per_order: int = 10
    max_orders_per_day: int = 40

    def __post_init__(self) -> None:
        if self.buffer_unit not in BUFFER_UNITS:
            raise ValueError(f"buffer_unit must be one of {BUFFER_UNITS}")
        if min(self.entry_buffer, self.exit_buffer, self.max_entry_chase_points) < 0:
            raise ValueError("buffers must be >= 0")
        if self.tick_size <= 0 or self.wait_seconds <= 0:
            raise ValueError("tick_size and wait_seconds must be > 0")
        if self.max_reprice_attempts < 0 or self.max_lots_per_order < 1 or self.max_orders_per_day < 1:
            raise ValueError("invalid order limits")


def buffer_points(policy: LiveOrderPolicy, reference: float, buffer: float) -> float:
    if policy.buffer_unit == "TICKS":
        return buffer * policy.tick_size
    if policy.buffer_unit == "PERCENT":
        return reference * buffer / 100.0
    return buffer


def round_to_tick(price: float, tick: float, side: str) -> float:
    """BUY rounds up, SELL rounds down: never less aggressive than intended."""
    # round(…, 6) drops float noise (0.1 + 0.2 = 0.30000000000000004) before snapping.
    steps = Decimal(str(round(price, 6))) / Decimal(str(tick))
    steps = steps.to_integral_value(ROUND_CEILING if side == "BUY" else ROUND_FLOOR)
    return float(steps * Decimal(str(tick)))


def limit_price(reference: float, side: str, policy: LiveOrderPolicy) -> float:
    if reference <= 0:
        raise ValueError("reference price must be positive")
    if side == "BUY":
        return round_to_tick(reference + buffer_points(policy, reference, policy.entry_buffer), policy.tick_size, "BUY")
    if side == "SELL":
        raw = reference - buffer_points(policy, reference, policy.exit_buffer)
        return max(round_to_tick(raw, policy.tick_size, "SELL"), policy.tick_size)
    raise ValueError("side must be BUY or SELL")


__all__ = ["BUFFER_UNITS", "LiveOrderPolicy", "buffer_points", "limit_price", "round_to_tick"]
