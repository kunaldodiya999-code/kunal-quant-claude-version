"""Economic trading cost model for Kunal Quant.

Keeps trading logic separate from execution/economic assumptions.
The initial V1 supports fixed per-order charges plus percentage slippage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EconomicCostConfig:
    """Execution-cost assumptions applied to each entry/exit order."""

    slippage_pct: float = 0.0025
    fixed_entry_charge: float = 25.0
    fixed_exit_charge: float = 25.0


@dataclass(frozen=True)
class OrderCost:
    """Cost details for one executed order."""

    reference_price: float
    execution_price: float
    quantity: int
    turnover: float
    slippage_cost: float
    fixed_charge: float
    total_cost: float


@dataclass(frozen=True)
class TradeEconomicResult:
    """Gross-to-net reconciliation for one completed trade."""

    gross_pnl: float
    entry_cost: OrderCost
    exit_costs: tuple[OrderCost, ...]
    total_slippage: float
    total_fixed_charges: float
    total_cost: float
    net_pnl: float


def _validate_price(value: float, name: str) -> float:
    price = float(value)
    if price <= 0:
        raise ValueError(f"{name} must be > 0.")
    return price


def _validate_quantity(quantity: int) -> int:
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError("quantity must be > 0.")
    return quantity


class EconomicCostModel:
    """Applies configurable slippage and fixed execution charges."""

    def __init__(
        self,
        config: EconomicCostConfig = EconomicCostConfig(),
    ) -> None:
        if config.slippage_pct < 0:
            raise ValueError("slippage_pct cannot be negative.")
        if config.fixed_entry_charge < 0:
            raise ValueError("fixed_entry_charge cannot be negative.")
        if config.fixed_exit_charge < 0:
            raise ValueError("fixed_exit_charge cannot be negative.")

        self.config = config

    def calculate_order_cost(
        self,
        *,
        side: str,
        reference_price: float,
        quantity: int,
    ) -> OrderCost:
        reference_price = _validate_price(reference_price, "reference_price")
        quantity = _validate_quantity(quantity)

        normalized_side = str(side).upper()
        if normalized_side not in {"BUY", "SELL"}:
            raise ValueError("side must be BUY or SELL.")

        slippage = reference_price * self.config.slippage_pct

        if normalized_side == "BUY":
            execution_price = reference_price + slippage
            fixed_charge = self.config.fixed_entry_charge
        else:
            execution_price = max(0.0, reference_price - slippage)
            fixed_charge = self.config.fixed_exit_charge

        turnover = execution_price * quantity
        slippage_cost = abs(execution_price - reference_price) * quantity
        total_cost = slippage_cost + fixed_charge

        return OrderCost(
            reference_price=reference_price,
            execution_price=execution_price,
            quantity=quantity,
            turnover=turnover,
            slippage_cost=slippage_cost,
            fixed_charge=fixed_charge,
            total_cost=total_cost,
        )

    def calculate_trade_net_pnl(
        self,
        *,
        direction: str,
        entry_price: float,
        entry_quantity: int,
        exits: list[dict] | tuple[dict, ...],
        gross_pnl: float,
    ) -> TradeEconomicResult:
        normalized_direction = str(direction).upper()
        if normalized_direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT.")

        if entry_quantity <= 0:
            raise ValueError("entry_quantity must be > 0.")

        if not exits:
            raise ValueError("At least one exit is required.")

        entry_side = "BUY" if normalized_direction == "LONG" else "SELL"
        exit_side = "SELL" if normalized_direction == "LONG" else "BUY"

        entry_cost = self.calculate_order_cost(
            side=entry_side,
            reference_price=entry_price,
            quantity=entry_quantity,
        )

        exit_costs: list[OrderCost] = []

        for exit_event in exits:
            exit_costs.append(
                self.calculate_order_cost(
                    side=exit_side,
                    reference_price=float(exit_event["price"]),
                    quantity=int(exit_event["quantity"]),
                )
            )

        total_slippage = (
            entry_cost.slippage_cost
            + sum(order.slippage_cost for order in exit_costs)
        )
        total_fixed_charges = (
            entry_cost.fixed_charge
            + sum(order.fixed_charge for order in exit_costs)
        )
        total_cost = total_slippage + total_fixed_charges
        net_pnl = float(gross_pnl) - total_cost

        return TradeEconomicResult(
            gross_pnl=float(gross_pnl),
            entry_cost=entry_cost,
            exit_costs=tuple(exit_costs),
            total_slippage=total_slippage,
            total_fixed_charges=total_fixed_charges,
            total_cost=total_cost,
            net_pnl=net_pnl,
        )
