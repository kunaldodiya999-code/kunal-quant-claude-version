"""Conservative historical fill and trade simulation for Opening Breakout V2.

Research-only. Broker-neutral. This module consumes an already validated
OpeningBreakoutEvent and historical bars for the traded contract.

No-lookahead rules:
- The signal candle is never used to fill the entry.
- Entry search begins on the first bar strictly after trigger_timestamp.
- A pending marketable-limit order can fill only when that bar's OHLC can
  prove the limit was reachable.
- When both SL and TP are reachable inside one OHLC bar, SL wins.
- Fill timeout is measured from the trigger timestamp.
- Force-exit is evaluated only after the position is actually filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from research.opening_breakout_1m_v2 import Direction, Signal, sl_trigger_limit_price, trailing_stop_price
from execution.opening_breakout_v2_execution import V2ExecutionPolicy, build_entry_intent


@dataclass(frozen=True)
class HistoricalBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        if self.high < max(self.open, self.close) or self.low > min(self.open, self.close):
            raise ValueError("invalid OHLC bar")


@dataclass(frozen=True)
class FillResult:
    filled: bool
    timestamp: int | None
    price: float | None
    reason: str


@dataclass(frozen=True)
class HistoricalTrade:
    signal: object
    entry: FillResult
    exit: FillResult
    stop_price: float | None
    target_price: float | None
    final_stop_price: float | None
    gross_pnl: float
    quantity: int


def _limit_reachable(bar: HistoricalBar, side: str, limit_price: float) -> bool:
    if side == "BUY":
        return bar.low <= limit_price
    return bar.high >= limit_price


def _conservative_fill_price(
    bar: HistoricalBar,
    side: str,
    limit_price: float,
) -> float | None:
    if not _limit_reachable(bar, side, limit_price):
        return None

    if side == "BUY":
        return min(bar.open, limit_price)
    return max(bar.open, limit_price)


def simulate_limit_fill(
    bars: Sequence[HistoricalBar],
    *,
    start_after_timestamp: int,
    side: str,
    limit_price: float,
    timeout_seconds: int,
) -> FillResult:
    """Find the first provable fill strictly after the signal timestamp."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be > 0")

    deadline = start_after_timestamp + timeout_seconds
    for bar in bars:
        if bar.timestamp <= start_after_timestamp:
            continue
        if bar.timestamp > deadline:
            break
        price = _conservative_fill_price(bar, side, limit_price)
        if price is not None:
            return FillResult(True, bar.timestamp, price, "FILLED")
    return FillResult(False, None, None, "FILL_TIMEOUT")


def _stop_hit(bar: HistoricalBar, direction: Direction, stop_price: float) -> bool:
    return bar.low <= stop_price if direction == "LONG" else bar.high >= stop_price


def _target_hit(bar: HistoricalBar, direction: Direction, target_price: float) -> bool:
    return bar.high >= target_price if direction == "LONG" else bar.low <= target_price


def simulate_exit(
    bars: Sequence[HistoricalBar],
    *,
    entry_timestamp: int,
    direction: Direction,
    quantity: int,
    stop_price: float | None,
    target_price: float | None,
    policy: V2ExecutionPolicy,
    force_exit_timestamp: int | None = None,
    trailing_enabled: bool = False,
    trailing_mode: str = "POINTS",
    trail_trigger_points: float = 40.0,
    trail_distance_points: float = 20.0,
    trail_to_cost: bool = False,
    trail_rr_steps: Sequence[tuple[float, float]] = ((2.0, 0.0), (3.0, 1.0)),
    entry_price: float | None = None,
) -> tuple[FillResult, float | None]:
    """Simulate exits after an entry fill.

    Stop has precedence over target when both are touched in one OHLC bar.
    A stop trigger is converted to its configured marketable-limit price, but
    the historical fill is conservatively bounded to the trigger/limit rather
    than pretending the order existed at the bar open.
    """
    if quantity <= 0:
        raise ValueError("quantity must be > 0")
    if entry_price is None:
        raise ValueError("entry_price is required")

    current_stop = stop_price
    planned_stop = stop_price

    for bar in bars:
        if bar.timestamp <= entry_timestamp:
            continue

        if force_exit_timestamp is not None and bar.timestamp >= force_exit_timestamp:
            return FillResult(True, bar.timestamp, bar.open, "FORCE_EXIT"), current_stop

        if current_stop is not None and _stop_hit(bar, direction, current_stop):
            trigger_limit = sl_trigger_limit_price(
                current_stop,
                direction,
                policy.exit_buffer_points,
            )
            if direction == "LONG":
                # Long stop: the trigger occurs on the way down. The fill cannot
                # be better than the stop trigger and is conservatively bounded
                # by the lower marketable-limit price.
                price = min(current_stop, trigger_limit)
            else:
                price = max(current_stop, trigger_limit)
            return FillResult(True, bar.timestamp, price, "STOP_LOSS"), current_stop

        if target_price is not None and _target_hit(bar, direction, target_price):
            side = "SELL" if direction == "LONG" else "BUY"
            limit = (
                target_price - policy.exit_buffer_points
                if side == "SELL"
                else target_price + policy.exit_buffer_points
            )
            price = _conservative_fill_price(bar, side, limit)
            if price is None:
                price = target_price
            return FillResult(True, bar.timestamp, price, "TARGET"), current_stop

        if trailing_enabled and current_stop is not None and planned_stop is not None:
            current_stop = trailing_stop_price(
                entry_price,
                planned_stop,
                current_stop,
                bar.close,
                direction,
                True,
                mode=trailing_mode,
                trigger_points=trail_trigger_points,
                trail_distance_points=trail_distance_points,
                trail_to_cost=trail_to_cost,
                rr_steps=trail_rr_steps,
            )

    return FillResult(False, None, None, "NO_EXIT"), current_stop


def simulate_trade(
    signal: Signal,
    *,
    direction: Direction,
    quantity: int,
    trigger_timestamp: int,
    breakout_price: float,
    ltp_at_signal: float,
    bars: Sequence[HistoricalBar],
    policy: V2ExecutionPolicy,
    stop_price: float | None,
    target_price: float | None,
    force_exit_timestamp: int | None = None,
    trailing_enabled: bool = False,
    trailing_mode: str = "POINTS",
    trail_trigger_points: float = 40.0,
    trail_distance_points: float = 20.0,
    trail_to_cost: bool = False,
    trail_rr_steps: Sequence[tuple[float, float]] = ((2.0, 0.0), (3.0, 1.0)),
) -> HistoricalTrade:
    if quantity <= 0:
        raise ValueError("quantity must be > 0")

    distance = (
        ltp_at_signal - breakout_price
        if direction == "LONG"
        else breakout_price - ltp_at_signal
    )
    if distance > policy.max_slippage_points:
        entry = FillResult(False, None, None, "SLIPPAGE_REJECTED")
        return HistoricalTrade(
            signal, entry, FillResult(False, None, None, "NO_EXIT"),
            stop_price, target_price, stop_price, 0.0, quantity,
        )

    entry_intent = build_entry_intent(
        signal,
        quantity,
        ltp_at_signal,
        policy,
    )
    entry = simulate_limit_fill(
        bars,
        start_after_timestamp=trigger_timestamp,
        side=entry_intent.side,
        limit_price=entry_intent.limit_price,
        timeout_seconds=policy.fill_timeout_seconds,
    )

    if not entry.filled:
        return HistoricalTrade(
            signal, entry, FillResult(False, None, None, "NO_EXIT"),
            stop_price, target_price, stop_price, 0.0, quantity,
        )

    exit_result, final_stop = simulate_exit(
        bars,
        entry_timestamp=entry.timestamp,
        direction=direction,
        quantity=quantity,
        stop_price=stop_price,
        target_price=target_price,
        policy=policy,
        force_exit_timestamp=force_exit_timestamp,
        trailing_enabled=trailing_enabled,
        trailing_mode=trailing_mode,
        trail_trigger_points=trail_trigger_points,
        trail_distance_points=trail_distance_points,
        trail_to_cost=trail_to_cost,
        trail_rr_steps=trail_rr_steps,
        entry_price=entry.price,
    )

    if not exit_result.filled:
        return HistoricalTrade(
            signal, entry, exit_result,
            stop_price, target_price, final_stop, 0.0, quantity,
        )

    multiplier = 1.0 if direction == "LONG" else -1.0
    pnl = (exit_result.price - entry.price) * quantity * multiplier
    return HistoricalTrade(
        signal, entry, exit_result,
        stop_price, target_price, final_stop, pnl, quantity,
    )


__all__ = [
    "HistoricalBar",
    "FillResult",
    "HistoricalTrade",
    "simulate_limit_fill",
    "simulate_exit",
    "simulate_trade",
]
