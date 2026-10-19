"""
KUNAL QUANT — OPTION TRADE LIFECYCLE V1

Purpose
-------
Manages an already-selected option position through:

1. Entry
2. 20% stop loss
3. 1:3 target
4. 50% partial exit
5. Remaining quantity continues
6. KAMA exit for remaining quantity

Important
---------
- This module does NOT generate KTMI signals.
- This module does NOT select the option contract.
- This module does NOT calculate KAMA.
- It receives those inputs from the existing project layers.
- It is deliberately separate from backtest/engine.py for V1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


# =====================================================================
# ENUMS
# =====================================================================

class OptionTradeDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class OptionExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET_3R = "TARGET_3R"
    KAMA_EXIT = "KAMA_EXIT"
    END_OF_DATA = "END_OF_DATA"


# =====================================================================
# CONFIG
# =====================================================================

@dataclass(frozen=True)
class OptionTradeLifecycleConfig:
    """
    Locked V1 trade-management parameters.
    """

    allocation: float = 15_000.0

    lot_size: int = 65

    stop_loss_pct: float = 0.20

    target_rr: float = 3.0

    partial_exit_fraction: float = 0.50

    # Keep target enabled for V1.
    target_enabled: bool = True


# =====================================================================
# POSITION
# =====================================================================

@dataclass
class OptionTradePosition:
    strategy_id: str
    direction: OptionTradeDirection

    symbol: str

    entry_price: float

    lots: int
    quantity: int

    stop_loss: float
    target: Optional[float]

    remaining_lots: int
    remaining_quantity: int

    partial_exit_done: bool = False
    closed: bool = False

    gross_pnl: float = 0.0


# =====================================================================
# EXIT EVENT
# =====================================================================

@dataclass(frozen=True)
class OptionTradeExit:
    timestamp: int

    reason: OptionExitReason

    price: float

    quantity: int

    lots: int

    pnl: float

    remaining_quantity: int

    remaining_lots: int


# =====================================================================
# RESULT
# =====================================================================

@dataclass(frozen=True)
class OptionTradeResult:
    position: OptionTradePosition

    exits: tuple[OptionTradeExit, ...]

    total_pnl: float

    closed: bool


# =====================================================================
# ENGINE
# =====================================================================

class OptionTradeLifecycle:

    def __init__(
        self,
        config: OptionTradeLifecycleConfig | None = None,
    ) -> None:

        self.config = (
            config
            if config is not None
            else OptionTradeLifecycleConfig()
        )

    # -----------------------------------------------------------------
    # POSITION CREATION
    # -----------------------------------------------------------------

    def create_position(
        self,
        *,
        strategy_id: str,
        direction: OptionTradeDirection,
        symbol: str,
        entry_price: float,
    ) -> OptionTradePosition:

        if entry_price <= 0:
            raise ValueError(
                "entry_price must be greater than zero"
            )

        if self.config.lot_size <= 0:
            raise ValueError(
                "lot_size must be greater than zero"
            )

        # -------------------------------------------------------------
        # Calculate how many complete lots the allocation can purchase.
        # -------------------------------------------------------------

        affordable_lots = int(
            self.config.allocation
            // (
                entry_price
                * self.config.lot_size
            )
        )

        if affordable_lots < 1:
            raise ValueError(
                "Allocation cannot purchase one complete lot"
            )

        quantity = (
            affordable_lots
            * self.config.lot_size
        )

        # -------------------------------------------------------------
        # LONG:
        #   SL = 20% below entry
        #
        # SHORT:
        #   SL = 20% above entry
        # -------------------------------------------------------------

        if direction == OptionTradeDirection.LONG:

            stop_loss = (
                entry_price
                * (1.0 - self.config.stop_loss_pct)
            )

            target = (
                entry_price
                + (
                    entry_price
                    - stop_loss
                )
                * self.config.target_rr
            )

        elif direction == OptionTradeDirection.SHORT:

            stop_loss = (
                entry_price
                * (1.0 + self.config.stop_loss_pct)
            )

            target = (
                entry_price
                - (
                    stop_loss
                    - entry_price
                )
                * self.config.target_rr
            )

        else:

            raise ValueError(
                f"Unsupported direction: {direction}"
            )

        return OptionTradePosition(
            strategy_id=strategy_id,
            direction=direction,
            symbol=symbol,
            entry_price=entry_price,
            lots=affordable_lots,
            quantity=quantity,
            stop_loss=stop_loss,
            target=target,
            remaining_lots=affordable_lots,
            remaining_quantity=quantity,
        )

    # -----------------------------------------------------------------
    # PARTIAL EXIT LOT CALCULATION
    # -----------------------------------------------------------------

    @staticmethod
    def calculate_partial_exit_lots(
        total_lots: int,
    ) -> tuple[int, int]:

        if total_lots < 1:
            raise ValueError(
                "total_lots must be at least 1"
            )

        if total_lots == 1:

            return 0, 1

        # -------------------------------------------------------------
        # Locked rule:
        #
        # Exit 50% rounded UP.
        # Keep at least 1 lot for KAMA.
        #
        # 1 -> 0 + 1
        # 2 -> 1 + 1
        # 3 -> 2 + 1
        # 4 -> 2 + 2
        # 5 -> 3 + 2
        # 6 -> 3 + 3
        # 7 -> 4 + 3
        # -------------------------------------------------------------

        exit_lots = (
            total_lots + 1
        ) // 2

        remaining_lots = (
            total_lots - exit_lots
        )

        if remaining_lots < 1:

            exit_lots = total_lots - 1
            remaining_lots = 1

        return exit_lots, remaining_lots

    # -----------------------------------------------------------------
    # P&L
    # -----------------------------------------------------------------

    @staticmethod
    def calculate_pnl(
        *,
        direction: OptionTradeDirection,
        entry_price: float,
        exit_price: float,
        quantity: int,
    ) -> float:

        if direction == OptionTradeDirection.LONG:

            return (
                exit_price
                - entry_price
            ) * quantity

        if direction == OptionTradeDirection.SHORT:

            return (
                entry_price
                - exit_price
            ) * quantity

        raise ValueError(
            f"Unsupported direction: {direction}"
        )

    # -----------------------------------------------------------------
    # PROCESS CANDLE
    # -----------------------------------------------------------------

    def process_candle(
    self,
    *,
    position: OptionTradePosition,
    timestamp: int,
    option_high: float,
    option_low: float,
    option_close: float,
    underlying_close: float,
    kama_value: Optional[float],
) -> list[OptionTradeExit]:

        if position.closed:
            return []

        exits: list[OptionTradeExit] = []

        # -------------------------------------------------------------
        # STOP LOSS
        #
        # Conservative ordering:
        # If both SL and target are touched in the same candle,
        # SL is considered first.
        # -------------------------------------------------------------

        if position.direction == OptionTradeDirection.LONG:

            if option_low <= position.stop_loss:

                pnl = self.calculate_pnl(
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=position.stop_loss,
                    quantity=position.remaining_quantity,
                )

                exit_event = OptionTradeExit(
                    timestamp=timestamp,
                    reason=OptionExitReason.STOP_LOSS,
                    price=position.stop_loss,
                    quantity=position.remaining_quantity,
                    lots=position.remaining_lots,
                    pnl=pnl,
                    remaining_quantity=0,
                    remaining_lots=0,
                )

                position.gross_pnl += pnl
                position.remaining_quantity = 0
                position.remaining_lots = 0
                position.closed = True

                exits.append(exit_event)

                return exits

        else:

            if option_high >= position.stop_loss:

                pnl = self.calculate_pnl(
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=position.stop_loss,
                    quantity=position.remaining_quantity,
                )

                exit_event = OptionTradeExit(
                    timestamp=timestamp,
                    reason=OptionExitReason.STOP_LOSS,
                    price=position.stop_loss,
                    quantity=position.remaining_quantity,
                    lots=position.remaining_lots,
                    pnl=pnl,
                    remaining_quantity=0,
                    remaining_lots=0,
                )

                position.gross_pnl += pnl
                position.remaining_quantity = 0
                position.remaining_lots = 0
                position.closed = True

                exits.append(exit_event)

                return exits

        # -------------------------------------------------------------
        # 3R TARGET
        # -------------------------------------------------------------

        if (
            self.config.target_enabled
            and position.target is not None
            and not position.partial_exit_done
        ):

            target_hit = False

            if position.direction == OptionTradeDirection.LONG:

                target_hit = option_high >= position.target

            else:

                target_hit = option_low <= position.target

            if target_hit:

                exit_lots, remaining_lots = (
                    self.calculate_partial_exit_lots(
                        position.remaining_lots
                    )
                )

                exit_quantity = (
                    exit_lots * self.config.lot_size
                )

                remaining_quantity = (
                    remaining_lots * self.config.lot_size
                )

                # -----------------------------------------------------
                # One-lot position:
                #
                # There is no valid 50% partial exit while preserving
                # a lot for KAMA.
                #
                # It remains under KAMA management.
                # -----------------------------------------------------

                if exit_lots > 0:

                    pnl = self.calculate_pnl(
                        direction=position.direction,
                        entry_price=position.entry_price,
                        exit_price=position.target,
                        quantity=exit_quantity,
                    )

                    exit_event = OptionTradeExit(
                        timestamp=timestamp,
                        reason=OptionExitReason.TARGET_3R,
                        price=position.target,
                        quantity=exit_quantity,
                        lots=exit_lots,
                        pnl=pnl,
                        remaining_quantity=remaining_quantity,
                        remaining_lots=remaining_lots,
                    )

                    position.gross_pnl += pnl

                    position.remaining_quantity = remaining_quantity
                    position.remaining_lots = remaining_lots
                    position.partial_exit_done = True

                    exits.append(exit_event)

                    # Do not evaluate KAMA on the same candle.
                    return exits

        # -------------------------------------------------------------
        # KAMA EXIT
        #
        # Remaining quantity exits using the OPTION CANDLE CLOSE.
        #
        # LONG:
        #   underlying close < KAMA
        #
        # SHORT:
        #   underlying close > KAMA
        #
        # Equal = HOLD
        # KAMA unavailable = HOLD
        # -------------------------------------------------------------

        if (
            not position.closed
            and position.remaining_quantity > 0
            and kama_value is not None
        ):

            kama_exit = False

            if position.direction == OptionTradeDirection.LONG:

                kama_exit = underlying_close < kama_value

            else:

                kama_exit = underlying_close > kama_value

            if kama_exit:

                pnl = self.calculate_pnl(
                    direction=position.direction,
                    entry_price=position.entry_price,
                    exit_price=option_close,
                    quantity=position.remaining_quantity,
                )

                exit_event = OptionTradeExit(
                    timestamp=timestamp,
                    reason=OptionExitReason.KAMA_EXIT,
                    price=option_close,
                    quantity=position.remaining_quantity,
                    lots=position.remaining_lots,
                    pnl=pnl,
                    remaining_quantity=0,
                    remaining_lots=0,
                )

                position.gross_pnl += pnl
                position.remaining_quantity = 0
                position.remaining_lots = 0
                position.closed = True

                exits.append(exit_event)

                return exits

        return exits