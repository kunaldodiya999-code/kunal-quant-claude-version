"""The owner's BBP_NM strategy (28 Oct 2026), as plain rules (no network, fully tested).

ENTRY / EXIT - only on a FINISHED candle of the chart (1, 3 or 5 min) of the index on the chart:
  * Direction crosses ABOVE 0  -> exit an open PUT; if the CALL box is ticked, buy a CALL.
  * Direction crosses BELOW 0  -> exit an open CALL; if the PUT box is ticked, buy a PUT.
    (CALL only ticked: the call is exited on the cross below and NO put is bought, and the other way round.)
  * A cross = the sign of Direction changes between two finished candles that have a value (bars where BBP_NM is
    na are skipped, as TradingView's line joins them). No trade on the first sign seen after the terminal starts.
  * Stop loss: the LOW of the option's own candle (same timeframe) that closed at the signal. Option price at or
    below it -> exit.
  * New entries 09:30 to 15:00, everything closed at 15:10 (owner's day rules; settings).
WHICH OPTION (one mode at a time, owner 28 Oct 2026):
  * PREMIUM RANGE  lo - hi: of the strikes whose price is inside lo..hi, the CHEAPEST one
                   (73000 CE at 195 and 72900 CE at 182 -> 72900 CE).
  * PER LOT AMOUNT X: the strike whose 1 lot (price x lot size) is nearest to X without going above it
                   (Rs 6,500 and NIFTY lot 65 -> the price nearest to Rs 100, at most 100).
HOW MANY LOTS: whole lots that "Funds to use per entry" buys (never more than the funds available).
ORDERS: LIMIT only, never market: buy at price + buffer (2), sell at price - buffer (2).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Sequence

MODES = ("RANGE", "PER_LOT")


@dataclass(frozen=True)
class ChainRow:
    strike: float
    symbol: str
    price: Optional[float]      # last traded price (None = no price yet)


@dataclass(frozen=True)
class Pick:
    row: Optional[ChainRow]
    reason: str


def direction_events(directions: Sequence[Optional[float]], start_sign: int = 0) -> list[tuple[int, str]]:
    """(bar index, "UP" or "DOWN") where Direction changes sign. ``start_sign`` = the sign known before these bars
    (0 = unknown: the first sign is only remembered, never traded)."""
    events, sign = [], start_sign
    for i, d in enumerate(directions):
        if d is None or d == 0:
            continue
        now = 1 if d > 0 else -1
        if sign and now != sign:
            events.append((i, "UP" if now > 0 else "DOWN"))
        sign = now
    return events


def last_sign(directions: Sequence[Optional[float]]) -> int:
    for d in reversed(directions):
        if d is not None and d != 0:
            return 1 if d > 0 else -1
    return 0


def pick_strike(rows: Sequence[ChainRow], *, mode: str, low: float = 0.0, high: float = 0.0,
                per_lot: float = 0.0, lot_size: int = 1) -> Pick:
    priced = [r for r in rows if r.price is not None and r.price > 0]
    if mode == "RANGE":
        if not (0 < low <= high):
            return Pick(None, "premium range is empty: fill both boxes (e.g. 180 - 200)")
        inside = [r for r in priced if low <= r.price <= high]
        if not inside:
            return Pick(None, f"no strike priced between {low:g} and {high:g}")
        best = min(inside, key=lambda r: (r.price, r.strike))
        return Pick(best, f"cheapest inside {low:g}-{high:g}: {best.symbol} at {best.price:g}")
    if mode == "PER_LOT":
        if per_lot <= 0 or lot_size < 1:
            return Pick(None, "per lot amount is empty")
        target = per_lot / lot_size
        under = [r for r in priced if r.price <= target]
        if not under:
            return Pick(None, f"no strike at or below {target:.2f} (Rs {per_lot:,.0f} / lot {lot_size})")
        best = max(under, key=lambda r: (r.price, -r.strike))
        return Pick(best, f"nearest to {target:.2f} without going above: {best.symbol} at {best.price:g}")
    raise ValueError(f"mode must be one of {MODES}")


def lots_for(funds_per_entry: float, available: float, price: float, lot_size: int) -> int:
    """Whole lots the money buys (the smaller of 'funds to use per entry' and the funds available)."""
    money = max(0.0, min(float(funds_per_entry), float(available)))
    if price <= 0 or lot_size < 1 or money <= 0:
        return 0
    cost = Decimal(str(price)) * lot_size
    return int((Decimal(str(money)) / cost).to_integral_value(rounding=ROUND_DOWN))


@dataclass(frozen=True)
class Action:
    kind: str                   # "EXIT" or "ENTER"
    side: str                   # "CALL" or "PUT"
    reason: str


def plan(event: str, *, position: Optional[str], call_on: bool, put_on: bool, entries_allowed: bool) -> list[Action]:
    """What to do on a Direction cross. ``position`` = "CALL", "PUT" or None."""
    actions = []
    if event == "UP":
        if position == "PUT":
            actions.append(Action("EXIT", "PUT", "Direction crossed above 0"))
        if call_on and position != "CALL" and entries_allowed:
            actions.append(Action("ENTER", "CALL", "Direction crossed above 0"))
    elif event == "DOWN":
        if position == "CALL":
            actions.append(Action("EXIT", "CALL", "Direction crossed below 0"))
        if put_on and position != "PUT" and entries_allowed:
            actions.append(Action("ENTER", "PUT", "Direction crossed below 0"))
    return actions


__all__ = ["Action", "ChainRow", "MODES", "Pick", "direction_events", "last_sign", "lots_for", "pick_strike", "plan"]
