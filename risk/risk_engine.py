"""
Kunal Quant Risk Engine V1.

This module calculates position size from:
    capital
    risk budget
    entry price
    stop-loss price
    lot size

It does NOT:
    - place orders
    - decide strategy direction
    - decide stop-loss location
    - decide targets
    - enforce a final daily-loss policy

Those decisions belong to higher-level components.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import floor


class RiskMethod(str, Enum):
    """Method used to determine the maximum trade risk."""

    FIXED_AMOUNT = "FIXED_AMOUNT"
    PERCENT_OF_CAPITAL = "PERCENT_OF_CAPITAL"


@dataclass(frozen=True)
class RiskRequest:
    """Inputs required for one position-sizing calculation."""

    capital: float

    entry_price: float
    stop_loss_price: float

    lot_size: int = 1

    risk_method: RiskMethod = RiskMethod.FIXED_AMOUNT

    fixed_risk_amount: float | None = None
    risk_percent: float | None = None

    def __post_init__(self) -> None:

        if self.capital <= 0:
            raise ValueError("capital must be > 0.")

        if self.entry_price <= 0:
            raise ValueError(
                "entry_price must be > 0."
            )

        if self.stop_loss_price <= 0:
            raise ValueError(
                "stop_loss_price must be > 0."
            )

        if self.entry_price == self.stop_loss_price:
            raise ValueError(
                "entry_price and stop_loss_price "
                "cannot be identical."
            )

        if self.lot_size < 1:
            raise ValueError(
                "lot_size must be >= 1."
            )

        if (
            self.risk_method == RiskMethod.FIXED_AMOUNT
            and (
                self.fixed_risk_amount is None
                or self.fixed_risk_amount <= 0
            )
        ):
            raise ValueError(
                "fixed_risk_amount must be > 0 "
                "when using FIXED_AMOUNT."
            )

        if (
            self.risk_method
            == RiskMethod.PERCENT_OF_CAPITAL
            and (
                self.risk_percent is None
                or self.risk_percent <= 0
            )
        ):
            raise ValueError(
                "risk_percent must be > 0 "
                "when using PERCENT_OF_CAPITAL."
            )


@dataclass(frozen=True)
class RiskResult:
    """Result of one position-sizing calculation."""

    risk_budget: float

    risk_per_unit: float

    theoretical_quantity: float

    quantity: int

    lots: int

    actual_risk: float

    unused_risk: float

    entry_price: float

    stop_loss_price: float

    lot_size: int

    @property
    def has_position(self) -> bool:
        """Return True if the calculated quantity is tradable."""

        return self.quantity > 0


def calculate_risk_budget(
    request: RiskRequest,
) -> float:
    """Calculate the maximum monetary risk allowed."""

    if request.risk_method == RiskMethod.FIXED_AMOUNT:

        assert request.fixed_risk_amount is not None

        return request.fixed_risk_amount

    assert request.risk_percent is not None

    return (
        request.capital
        * request.risk_percent
        / 100.0
    )


def calculate_position_size(
    request: RiskRequest,
) -> RiskResult:
    """
    Calculate quantity using stop-loss distance.

    Formula:

        risk_per_unit =
            abs(entry_price - stop_loss_price)

        theoretical_quantity =
            risk_budget / risk_per_unit

    Final quantity is rounded DOWN to a complete lot.
    """

    risk_budget = calculate_risk_budget(
        request
    )

    risk_per_unit = abs(
        request.entry_price
        - request.stop_loss_price
    )

    if risk_per_unit <= 0:
        raise ValueError(
            "Risk per unit must be > 0."
        )

    theoretical_quantity = (
        risk_budget
        / risk_per_unit
    )

    lots = floor(
        theoretical_quantity
        / request.lot_size
    )

    quantity = (
        lots
        * request.lot_size
    )

    actual_risk = (
        quantity
        * risk_per_unit
    )

    unused_risk = (
        risk_budget
        - actual_risk
    )

    return RiskResult(
        risk_budget=risk_budget,
        risk_per_unit=risk_per_unit,
        theoretical_quantity=theoretical_quantity,
        quantity=quantity,
        lots=lots,
        actual_risk=actual_risk,
        unused_risk=unused_risk,
        entry_price=request.entry_price,
        stop_loss_price=request.stop_loss_price,
        lot_size=request.lot_size,
    )


__all__ = [
    "RiskMethod",
    "RiskRequest",
    "RiskResult",
    "calculate_position_size",
    "calculate_risk_budget",
]