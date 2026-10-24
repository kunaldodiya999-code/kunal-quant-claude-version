"""Limit-order execution: place, wait, re-price, and never fall back to market.

ENTRY (BUY): limit = fresh price + entry buffer, re-priced up to N times but
never above (first reference + max chase). If still not filled, the rest is
cancelled: no position is better than a chased one.

EXIT (SELL): limit = fresh price - exit buffer, re-priced up to N times. If
still not filled the order is LEFT WORKING and an ALERT is raised: the
position is still open. A market order is never sent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from live_trading.gateway import OrderError, OrderState
from live_trading.orders import LiveOrderPolicy, limit_price

FINAL_BAD = {"REJECTED", "CANCELLED", "EXPIRED"}


@dataclass
class ExecutionResult:
    kind: str                      # ENTRY / EXIT
    symbol: str
    side: str
    requested_qty: int
    status: str                    # FILLED, PARTIAL, NOT_FILLED, REJECTED, EXIT_WORKING, NOT_PLACED, ERROR
    filled_qty: int = 0
    avg_price: float | None = None
    order_ids: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def alert(self) -> bool:
        return self.status in ("EXIT_WORKING", "ERROR") or (self.kind == "EXIT" and self.status != "FILLED")


class LimitOrderExecutor:
    def __init__(self, gateway, policy: LiveOrderPolicy, price_source: Callable[[str], float],
                 *, sleep=time.sleep) -> None:
        self.gateway, self.policy, self.price_source, self._sleep = gateway, policy, price_source, sleep
        self.orders_today = 0

    def _fresh_price(self, symbol: str, fallback: float | None) -> float | None:
        try:
            return float(self.price_source(symbol))
        except (LookupError, ValueError):
            return fallback

    def execute(self, *, kind: str, symbol: str, qty: int, lot_size: int, reference: float | None = None,
                tag: str = "KQ") -> ExecutionResult:
        side = "BUY" if kind == "ENTRY" else "SELL"
        result = ExecutionResult(kind, symbol, side, int(qty), "NOT_PLACED")
        if qty <= 0 or qty % lot_size:
            result.message = f"quantity {qty} is not a whole number of lots ({lot_size})"
            return result
        if qty // lot_size > self.policy.max_lots_per_order:
            result.message = f"{qty // lot_size} lots is above the safety cap of {self.policy.max_lots_per_order}"
            return result
        if self.orders_today >= self.policy.max_orders_per_day:
            result.message = f"daily order cap reached ({self.policy.max_orders_per_day})"
            return result
        first = self._fresh_price(symbol, reference)
        if first is None:
            result.message = "no fresh option price: order not sent"
            return result

        price = limit_price(first, side, self.policy)
        cap = limit_price(first + self.policy.max_entry_chase_points, "BUY", self.policy) if side == "BUY" else None
        try:
            order_id = self.gateway.place_limit(symbol, side, qty, price, tag)
        except OrderError as exc:
            result.status, result.message = "REJECTED", str(exc)
            return result
        self.orders_today += 1
        result.order_ids.append(order_id)

        state: OrderState | None = None
        for attempt in range(self.policy.max_reprice_attempts + 1):
            self._sleep(self.policy.wait_seconds)
            try:
                state = self.gateway.state(order_id)
            except OrderError as exc:
                result.status, result.message = "ERROR", f"{exc}. Order {order_id} may still be working: check FYERS."
                return result
            result.filled_qty, result.avg_price = state.filled_qty, state.traded_price
            if state.status == "FILLED":
                result.status, result.message = "FILLED", state.message
                return result
            if state.status in FINAL_BAD:
                result.status = "PARTIAL" if state.filled_qty else "REJECTED"
                result.message = f"{state.status}: {state.message}"
                return result
            if attempt == self.policy.max_reprice_attempts:
                break
            new_price = limit_price(self._fresh_price(symbol, first) or first, side, self.policy)
            if side == "BUY":
                new_price = min(new_price, cap)
            if new_price != price:
                try:
                    self.gateway.modify_price(order_id, new_price)
                    price = new_price
                except OrderError as exc:
                    result.message = f"re-price refused: {exc}"

        if side == "BUY":
            try:
                self.gateway.cancel(order_id)
            except OrderError as exc:
                result.status, result.message = "ERROR", f"could not cancel unfilled entry {order_id}: {exc}. Check FYERS now."
                return result
            result.status = "PARTIAL" if result.filled_qty else "NOT_FILLED"
            result.message = f"entry not filled within {self.policy.max_reprice_attempts + 1} tries; rest cancelled"
            return result
        result.status = "EXIT_WORKING"
        result.message = (f"ALERT: exit SELL {order_id} still working at {price} "
                          f"({result.filled_qty}/{qty} filled). Position NOT fully closed. No market order was sent.")
        return result


__all__ = ["ExecutionResult", "LimitOrderExecutor"]
