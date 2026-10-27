"""Which strike to buy, by the money (owner 27 Oct 2026).

"For NIFTY use Rs 8,000 max for 1 lot. If we have Rs 15,000 we can buy 2 lots of Rs 115 each. The call or put we buy
is ATM or ATM+1, whichever can buy MORE lots, never beyond ATM+1."

    cost of 1 lot = premium x lot size                 (115 x 65 = Rs 7,475)
    a strike whose 1 lot costs more than the cap is not allowed (cap 0 = no cap)
    lots          = whole lots the budget pays for      (Rs 15,000 / 7,475 = 2)
    choice        = the strike with more lots; equal lots -> ATM (closer to the money)
    no strike with 1 whole lot -> no trade, with the reason

ATM+1 = one strike further out of the money (CALL: one strike up, PUT: one strike down; owner 24 Oct 2026).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Sequence

AUTO_CHOICES = (("ATM", 0), ("ATM+1", 1))


@dataclass(frozen=True)
class StrikeChoice:
    label: Optional[str]          # "ATM" / "ATM+1", None = no trade
    offset: Optional[int]
    premium: float
    lots: int
    cost_per_lot: float
    reason: str                   # plain words: what was compared and why


def lots_for(budget: float, premium: float, lot_size: int, max_lot_cost: float = 0.0) -> tuple[int, float]:
    """(whole lots, cost of one lot); 0 lots when one lot is above the cap or the budget."""
    cost = Decimal(str(float(premium))) * int(lot_size)
    if premium <= 0 or lot_size < 1:
        return 0, float(cost)
    if max_lot_cost and cost > Decimal(str(float(max_lot_cost))):
        return 0, float(cost)
    lots = int((Decimal(str(max(float(budget), 0.0))) / cost).to_integral_value(rounding=ROUND_DOWN))
    return lots, float(cost)


def choose_strike(candidates: Sequence[tuple[str, int, float]], *, budget: float, lot_size: int,
                  max_lot_cost: float = 0.0) -> StrikeChoice:
    """``candidates``: (label, offset, premium) for ATM and ATM+1 (or one strike in manual mode)."""
    rows = []
    best = None
    for label, offset, premium in candidates:
        lots, cost = lots_for(budget, premium, lot_size, max_lot_cost)
        note = (f"{label} {premium:g}: 1 lot Rs {cost:,.0f}"
                + (f" > cap Rs {max_lot_cost:,.0f}" if max_lot_cost and cost > max_lot_cost else f" -> {lots} lot(s)"))
        rows.append(note)
        if lots >= 1 and (best is None or lots > best[3]):          # equal lots: keep the first (ATM)
            best = (label, offset, premium, lots, cost)
    compared = "; ".join(rows) + f" (budget Rs {budget:,.0f})"
    if best is None:
        return StrikeChoice(None, None, 0.0, 0, 0.0, f"no trade: not one whole lot within the rules - {compared}")
    label, offset, premium, lots, cost = best
    return StrikeChoice(label, offset, premium, lots, cost, f"{label} chosen - {compared}")


__all__ = ["AUTO_CHOICES", "StrikeChoice", "choose_strike", "lots_for"]
