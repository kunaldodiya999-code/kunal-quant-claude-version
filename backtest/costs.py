"""Trading cost and slippage model for Kunal Quant."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostConfig:
    """Backtest transaction-cost configuration."""

    enabled: bool = True

    # Slippage expressed as percentage of execution price.
    # Example:
    # 0.25 = 0.25%
    entry_slippage_percent: float = 0.25
    exit_slippage_percent: float = 0.25

    # Fixed brokerage/other charges per executed order.
    entry_fixed_charge: float = 25.0
    exit_fixed_charge: float = 25.0

    def __post_init__(self) -> None:

        if self.entry_slippage_percent < 0:
            raise ValueError(
                "Entry slippage cannot be negative."
            )

        if self.exit_slippage_percent < 0:
            raise ValueError(
                "Exit slippage cannot be negative."
            )

        if self.entry_fixed_charge < 0:
            raise ValueError(
                "Entry fixed charge cannot be negative."
            )

        if self.exit_fixed_charge < 0:
            raise ValueError(
                "Exit fixed charge cannot be negative."
            )


@dataclass(frozen=True)
class ExecutionResult:
    """Execution price after applying slippage."""

    reference_price: float
    execution_price: float
    slippage_amount: float


@dataclass(frozen=True)
class TradeCostResult:
    """Complete cost calculation for one trade."""

    entry_slippage: float
    exit_slippage: float

    entry_fixed_charge: float
    exit_fixed_charge: float

    total_cost: float


def calculate_entry_execution(
    direction: str,
    reference_price: float,
    config: CostConfig,
) -> ExecutionResult:
    """Calculate entry execution price."""

    if reference_price <= 0:
        raise ValueError(
            "Reference price must be positive."
        )

    if not config.enabled:
        return ExecutionResult(
            reference_price=reference_price,
            execution_price=reference_price,
            slippage_amount=0.0,
        )

    slippage = (
        reference_price
        * config.entry_slippage_percent
        / 100.0
    )

    direction = direction.upper()

    # Buying is worse at a higher price.
    # Selling short is worse at a lower price.
    if direction == "LONG":
        execution_price = (
            reference_price + slippage
        )

    elif direction == "SHORT":
        execution_price = (
            reference_price - slippage
        )

    else:
        raise ValueError(
            f"Unsupported direction: {direction}"
        )

    return ExecutionResult(
        reference_price=reference_price,
        execution_price=execution_price,
        slippage_amount=slippage,
    )


def calculate_exit_execution(
    direction: str,
    reference_price: float,
    config: CostConfig,
) -> ExecutionResult:
    """Calculate exit execution price."""

    if reference_price <= 0:
        raise ValueError(
            "Reference price must be positive."
        )

    if not config.enabled:
        return ExecutionResult(
            reference_price=reference_price,
            execution_price=reference_price,
            slippage_amount=0.0,
        )

    slippage = (
        reference_price
        * config.exit_slippage_percent
        / 100.0
    )

    direction = direction.upper()

    # Closing LONG = selling.
    # Closing SHORT = buying.
    if direction == "LONG":
        execution_price = (
            reference_price - slippage
        )

    elif direction == "SHORT":
        execution_price = (
            reference_price + slippage
        )

    else:
        raise ValueError(
            f"Unsupported direction: {direction}"
        )

    return ExecutionResult(
        reference_price=reference_price,
        execution_price=execution_price,
        slippage_amount=slippage,
    )


def calculate_trade_costs(
    entry_price: float,
    exit_price: float,
    quantity: int,
    direction: str,
    config: CostConfig,
) -> TradeCostResult:
    """Calculate total transaction costs."""

    if quantity <= 0:
        raise ValueError(
            "Quantity must be greater than zero."
        )

    entry = calculate_entry_execution(
        direction=direction,
        reference_price=entry_price,
        config=config,
    )

    exit = calculate_exit_execution(
        direction=direction,
        reference_price=exit_price,
        config=config,
    )

    entry_slippage = (
        abs(
            entry.execution_price
            - entry.reference_price
        )
        * quantity
    )

    exit_slippage = (
        abs(
            exit.execution_price
            - exit.reference_price
        )
        * quantity
    )

    if not config.enabled:
        entry_fixed = 0.0
        exit_fixed = 0.0
    else:
        entry_fixed = config.entry_fixed_charge
        exit_fixed = config.exit_fixed_charge

    total_cost = (
        entry_slippage
        + exit_slippage
        + entry_fixed
        + exit_fixed
    )

    return TradeCostResult(
        entry_slippage=entry_slippage,
        exit_slippage=exit_slippage,
        entry_fixed_charge=entry_fixed,
        exit_fixed_charge=exit_fixed,
        total_cost=total_cost,
    )