"""Kunal Quant Trade Management V1.

Configurable trade-management layer for:
    - capital allocation per trade
    - whole-lot position sizing
    - percentage stop loss
    - R-multiple target
    - partial exit
    - KAMA close-based exit for the remainder

This module intentionally does NOT modify:
    - KTMI calculation
    - KAMA calculation
    - the generic risk engine
    - the existing Backtest V1/V2 engine

It is an experimental V1 layer and can be integrated after validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Literal, Optional, Sequence

from backtest.models import BacktestBar


Direction = Literal["LONG", "SHORT"]


@dataclass(frozen=True)
class TradeManagementConfig:
    """User-facing trade-management parameters."""

    initial_capital: float = 100_000.0
    allocation_per_trade: float = 15_000.0

    lot_size: int = 65

    stop_loss_enabled: bool = True
    stop_loss_percent: float = 20.0

    target_enabled: bool = True
    target_rr: float = 3.0

    partial_exit_enabled: bool = True
    partial_exit_percent: float = 50.0

    kama_exit_enabled: bool = True

    # Whole-lot rule. Currently fixed to floor for V1.
    partial_rounding: str = "floor"


@dataclass(frozen=True)
class PositionSizingResult:
    entry_price: float
    lots: int
    quantity: int
    capital_used: float
    unused_allocation: float
    stop_loss: Optional[float]
    target: Optional[float]
    risk_per_unit: float
    planned_risk: float


@dataclass(frozen=True)
class TradeLeg:
    direction: Direction
    entry_price: float
    exit_price: float
    lots: int
    quantity: int
    exit_reason: str
    pnl: float


@dataclass(frozen=True)
class ManagedTrade:
    direction: Direction
    entry_price: float
    entry_lots: int
    entry_quantity: int
    capital_used: float

    stop_loss: Optional[float]
    target: Optional[float]

    partial_exit_lots: int
    partial_exit_quantity: int

    remaining_exit_lots: int
    remaining_exit_quantity: int

    legs: tuple[TradeLeg, ...]

    gross_pnl: float


def calculate_position_size(
    entry_price: float,
    direction: Direction,
    config: TradeManagementConfig,
) -> PositionSizingResult:
    """Size a position using allocation and whole lots.

    Example:
        allocation = 15000
        option price = 100
        lot size = 65

        affordable quantity = 150
        complete lots = 2
        final quantity = 130
    """

    if entry_price <= 0:
        raise ValueError("Entry price must be positive.")

    if direction not in {"LONG", "SHORT"}:
        raise ValueError("Direction must be LONG or SHORT.")

    if config.allocation_per_trade <= 0:
        raise ValueError("Allocation per trade must be positive.")

    if config.lot_size <= 0:
        raise ValueError("Lot size must be positive.")

    affordable_quantity = floor(
        config.allocation_per_trade / entry_price
    )

    lots = affordable_quantity // config.lot_size
    quantity = lots * config.lot_size

    if quantity <= 0:
        return PositionSizingResult(
            entry_price=entry_price,
            lots=0,
            quantity=0,
            capital_used=0.0,
            unused_allocation=config.allocation_per_trade,
            stop_loss=None,
            target=None,
            risk_per_unit=0.0,
            planned_risk=0.0,
        )

    capital_used = quantity * entry_price
    unused_allocation = (
        config.allocation_per_trade - capital_used
    )

    if config.stop_loss_enabled:
        distance = (
            entry_price * config.stop_loss_percent / 100.0
        )

        if direction == "LONG":
            stop_loss = entry_price - distance
        else:
            stop_loss = entry_price + distance

        if stop_loss <= 0:
            raise ValueError("Calculated stop loss must be positive.")

        risk_per_unit = abs(entry_price - stop_loss)
    else:
        stop_loss = None
        risk_per_unit = 0.0

    planned_risk = quantity * risk_per_unit

    if config.target_enabled:
        if not config.stop_loss_enabled:
            raise ValueError(
                "R-multiple target requires stop loss to calculate risk."
            )

        target_distance = risk_per_unit * config.target_rr

        if direction == "LONG":
            target = entry_price + target_distance
        else:
            target = entry_price - target_distance

        if target <= 0:
            raise ValueError("Calculated target must be positive.")
    else:
        target = None

    return PositionSizingResult(
        entry_price=entry_price,
        lots=lots,
        quantity=quantity,
        capital_used=capital_used,
        unused_allocation=unused_allocation,
        stop_loss=stop_loss,
        target=target,
        risk_per_unit=risk_per_unit,
        planned_risk=planned_risk,
    )


def calculate_partial_lots(
    total_lots: int,
    partial_percent: float,
) -> int:
    """Calculate whole lots to exit at the partial target."""

    if total_lots <= 0:
        raise ValueError("Total lots must be positive.")

    if not 0 < partial_percent <= 100:
        raise ValueError(
            "Partial exit percent must be greater than 0 and <= 100."
        )

    lots = floor(
        total_lots * partial_percent / 100.0
    )

    # A partial exit must leave at least one lot when possible.
    if lots >= total_lots and total_lots > 1:
        lots = total_lots - 1

    # With one lot, 50% cannot be represented as whole lots.
    if total_lots == 1:
        return 0

    return lots


def _pnl(
    direction: Direction,
    entry_price: float,
    exit_price: float,
    quantity: int,
) -> float:
    if direction == "LONG":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def run_trade_management(
    bars: Sequence[BacktestBar],
    direction: Direction,
    entry_price: float,
    kama_values: Sequence[Optional[float]],
    config: TradeManagementConfig,
) -> ManagedTrade:
    """Run one managed position.

    Rules:
        1. No same-candle exit.
        2. Stop loss has priority over target if both are touched.
        3. Target exits the configured whole-lot partial quantity.
        4. Remaining quantity exits when the candle closes through KAMA.
        5. If neither occurs, remaining position exits at end of data.

    This is intentionally a standalone V1 experiment.
    """

    if not bars:
        raise ValueError("Bars cannot be empty.")

    if len(kama_values) != len(bars):
        raise ValueError("bars and kama_values must have equal length.")

    sizing = calculate_position_size(
        entry_price=entry_price,
        direction=direction,
        config=config,
    )

    if sizing.lots <= 0:
        raise ValueError(
            "Allocation cannot purchase at least one complete lot."
        )

    partial_lots = 0
    if config.target_enabled and config.partial_exit_enabled:
        partial_lots = calculate_partial_lots(
            sizing.lots,
            config.partial_exit_percent,
        )

    partial_qty = partial_lots * config.lot_size
    remaining_lots = sizing.lots - partial_lots
    remaining_qty = remaining_lots * config.lot_size

    legs: list[TradeLeg] = []
    remaining_active = sizing.quantity
    partial_done = False

    for index, bar in enumerate(bars):
        # The entry candle is the first bar; never exit on it.
        if index == 0:
            continue

        # ------------------------------------------------------
        # STOP LOSS
        # ------------------------------------------------------
        if (
            sizing.stop_loss is not None
            and remaining_active > 0
        ):
            stop_hit = (
                bar.low <= sizing.stop_loss
                if direction == "LONG"
                else bar.high >= sizing.stop_loss
            )

            if stop_hit:
                legs.append(
                    TradeLeg(
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=sizing.stop_loss,
                        lots=remaining_active // config.lot_size,
                        quantity=remaining_active,
                        exit_reason="STOP_LOSS",
                        pnl=_pnl(
                            direction,
                            entry_price,
                            sizing.stop_loss,
                            remaining_active,
                        ),
                    )
                )
                remaining_active = 0
                break

        # ------------------------------------------------------
        # 3R PARTIAL TARGET
        # ------------------------------------------------------
        if (
            sizing.target is not None
            and not partial_done
            and partial_lots > 0
        ):
            target_hit = (
                bar.high >= sizing.target
                if direction == "LONG"
                else bar.low <= sizing.target
            )

            if target_hit:
                legs.append(
                    TradeLeg(
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=sizing.target,
                        lots=partial_lots,
                        quantity=partial_qty,
                        exit_reason="TARGET_3R_PARTIAL",
                        pnl=_pnl(
                            direction,
                            entry_price,
                            sizing.target,
                            partial_qty,
                        ),
                    )
                )
                remaining_active -= partial_qty
                partial_done = True

            print(
                f"DEBUG ENGINE | TARGET | "
                f"remaining_active={remaining_active} | "
                f"partial_done={partial_done}"
            )

        if remaining_active <= 0:
            break

        # ------------------------------------------------------
        # KAMA EXIT
        # ------------------------------------------------------
        kama = kama_values[index]

        print(
            f"DEBUG ENGINE | BAR {index} | "
            f"close={bar.close} | "
            f"kama={kama} | "
            f"remaining_active={remaining_active}"
        )

        if config.kama_exit_enabled and kama is not None:
            kama_exit = (
                bar.close < kama
                if direction == "LONG"
                else bar.close > kama
            )

            if kama_exit:
                remaining_lots_now = (
                    remaining_active // config.lot_size
                )

                print(
                    f"DEBUG ENGINE | KAMA EXIT | "
                    f"close={bar.close} | kama={kama}"
                )

                legs.append(
                    TradeLeg(
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=bar.close,
                        lots=remaining_lots_now,
                        quantity=remaining_active,
                        exit_reason=(
                            "KAMA_LONG_CLOSE_BELOW"
                            if direction == "LONG"
                            else "KAMA_SHORT_CLOSE_ABOVE"
                        ),
                        pnl=_pnl(
                            direction,
                            entry_price,
                            bar.close,
                            remaining_active,
                        ),
                    )
                )
                remaining_active = 0
                break

    # ----------------------------------------------------------
    # END OF DATA
    # ----------------------------------------------------------
    if remaining_active > 0:
        final_bar = bars[-1]
        remaining_lots_now = remaining_active // config.lot_size

        legs.append(
            TradeLeg(
                direction=direction,
                entry_price=entry_price,
                exit_price=final_bar.close,
                lots=remaining_lots_now,
                quantity=remaining_active,
                exit_reason="END_OF_DATA",
                pnl=_pnl(
                    direction,
                    entry_price,
                    final_bar.close,
                    remaining_active,
                ),
            )
        )

    return ManagedTrade(
        direction=direction,
        entry_price=entry_price,
        entry_lots=sizing.lots,
        entry_quantity=sizing.quantity,
        capital_used=sizing.capital_used,
        stop_loss=sizing.stop_loss,
        target=sizing.target,
        partial_exit_lots=partial_lots,
        partial_exit_quantity=partial_qty,
        remaining_exit_lots=remaining_lots,
        remaining_exit_quantity=remaining_qty,
        legs=tuple(legs),
        gross_pnl=sum(leg.pnl for leg in legs),
    )
