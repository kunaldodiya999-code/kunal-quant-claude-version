"""Buyer-only option lifecycle for KTMI paper trades.

Unlike the locked historical V1 lifecycle, both LONG (buy CE) and SHORT
(buy PE) represent long option premium. SHORT is retained as the underlying
signal direction for KAMA exits; it never means short-selling an option.
This module is additive and must not change backtest.option_trade_lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from paper_trading.sizing import calculate_lots, sizing_warning
from typing import Optional

from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradeLifecycleConfig,
    OptionTradePosition,
)


@dataclass(frozen=True)
class BuyerLifecycleConfig:
    """Paper buyer controls. Owner defaults: 30% initial stop, 3R target on that risk."""

    allocation: float = 15_000.0
    lot_size: int = 65
    stop_loss_pct: float = 0.30      # owner default: initial stop 30% below the premium paid
    target_rr: float = 3.0
    partial_exit_fraction: float = 0.50
    target_enabled: bool = True
    # One-lot trade at the target: CLOSE_ALL (owner rule: no impossible half-lot) or KEEP_TRAILING.
    single_lot_at_target: str = "CLOSE_ALL"
    # Stop of the remaining lots after the partial booking: BREAKEVEN (entry), LOCK_1R (entry + 1R) or KEEP.
    after_partial: str = "BREAKEVEN"

    def __post_init__(self) -> None:
        if not isfinite(self.allocation) or self.allocation <= 0:
            raise ValueError("allocation must be finite and positive")
        if self.lot_size < 1:
            raise ValueError("lot_size must be positive")
        if not 0 < self.stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be between 0 and 1")
        if not isfinite(self.target_rr) or self.target_rr <= 0:
            raise ValueError("target_rr must be finite and positive")
        if not 0 < self.partial_exit_fraction < 1:
            raise ValueError("partial_exit_fraction must be between 0 and 1")
        if self.single_lot_at_target not in ("CLOSE_ALL", "KEEP_TRAILING"):
            raise ValueError("single_lot_at_target must be CLOSE_ALL or KEEP_TRAILING")
        if self.after_partial not in ("BREAKEVEN", "LOCK_1R", "KEEP"):
            raise ValueError("after_partial must be BREAKEVEN, LOCK_1R or KEEP")


class BuyerOptionTradeLifecycle:
    """Long-premium lifecycle for both bought calls and bought puts.

    Stop/target/P&L always follow option premium. KAMA exit direction follows
    the underlying signal: LONG exits below KAMA; SHORT exits above KAMA.
    If stop and target touch in one candle, stop wins conservatively.
    """

    def __init__(self, config: BuyerLifecycleConfig | None = None) -> None:
        self.config = config or BuyerLifecycleConfig()
        # Each trade keeps the settings it was opened with (later changes apply to new trades only).
        self._snapshots: dict[int, BuyerLifecycleConfig] = {}

    def config_for(self, position: OptionTradePosition) -> BuyerLifecycleConfig:
        return self._snapshots.get(id(position), self.config)

    def remember(self, position: OptionTradePosition, config: BuyerLifecycleConfig) -> None:
        """Attach a settings snapshot to a position (new trades, or trades restored after a restart)."""
        self._snapshots[id(position)] = config

    def create_position(
        self, *, strategy_id: str, direction: OptionTradeDirection,
        symbol: str, entry_price: float, allocation: float | None = None,
    ) -> OptionTradePosition:
        if not isfinite(entry_price) or entry_price <= 0:
            raise ValueError("entry_price must be finite and positive")
        budget = self.config.allocation if allocation is None else float(allocation)
        sizing = calculate_lots(budget, entry_price, self.config.lot_size)
        if not sizing.tradable:
            raise ValueError(sizing_warning(sizing))
        lots, quantity = sizing.lots, sizing.quantity
        stop = entry_price * (1.0 - self.config.stop_loss_pct)
        target = entry_price + (entry_price - stop) * self.config.target_rr
        position = OptionTradePosition(
            strategy_id=strategy_id, direction=direction, symbol=symbol,
            entry_price=entry_price, lots=lots, quantity=quantity,
            stop_loss=stop, target=target, remaining_lots=lots,
            remaining_quantity=quantity,
        )
        self.remember(position, self.config)
        return position

    @staticmethod
    def calculate_partial_exit_lots(total_lots: int, fraction: float = 0.5,
                                    single_lot: str = "KEEP_TRAILING") -> tuple[int, int]:
        """Lots to book at the target and lots left. Half of 3 lots rounds up to 2.
        One lot: CLOSE_ALL books it in full; KEEP_TRAILING books nothing."""
        if total_lots < 1:
            raise ValueError("total_lots must be at least 1")
        if total_lots == 1:
            return (1, 0) if single_lot == "CLOSE_ALL" else (0, 1)
        exit_lots = min(max(1, int(total_lots * fraction + 0.5)), total_lots - 1)
        return exit_lots, total_lots - exit_lots

    @staticmethod
    def calculate_pnl(*, direction: OptionTradeDirection, entry_price: float,
                      exit_price: float, quantity: int) -> float:
        # Both CE and PE positions are long option premium.
        return (exit_price - entry_price) * quantity

    def process_candle(
        self, *, position: OptionTradePosition, timestamp: int,
        option_high: float, option_low: float, option_close: float,
        underlying_close: float, kama_value: Optional[float],
    ) -> list[OptionTradeExit]:
        if position.closed:
            return []
        values = (option_high, option_low, option_close, underlying_close)
        if not all(isfinite(float(v)) for v in values):
            raise ValueError("Candle prices must be finite")
        if min(option_high, option_low, option_close) <= 0 or option_low > option_high:
            raise ValueError("Invalid option candle prices")

        exits: list[OptionTradeExit] = []
        cfg = self.config_for(position)

        def close_quantity(reason: OptionExitReason, price: float,
                           quantity: int, lots: int) -> OptionTradeExit:
            pnl = self.calculate_pnl(
                direction=position.direction, entry_price=position.entry_price,
                exit_price=price, quantity=quantity,
            )
            position.gross_pnl += pnl
            position.remaining_quantity -= quantity
            position.remaining_lots -= lots
            position.closed = position.remaining_quantity == 0
            return OptionTradeExit(
                timestamp=int(timestamp), reason=reason, price=float(price),
                quantity=quantity, lots=lots, pnl=pnl,
                remaining_quantity=position.remaining_quantity,
                remaining_lots=position.remaining_lots,
            )

        # Stop is checked before target, including when both are touched.
        if option_low <= position.stop_loss:
            exits.append(close_quantity(
                OptionExitReason.STOP_LOSS, position.stop_loss,
                position.remaining_quantity, position.remaining_lots,
            ))
            return exits

        if (cfg.target_enabled and position.target is not None
                and not position.partial_exit_done
                and option_high >= position.target):
            exit_lots, remaining_lots = self.calculate_partial_exit_lots(
                position.remaining_lots, cfg.partial_exit_fraction, cfg.single_lot_at_target,
            )
            if exit_lots > 0:
                exit_quantity = min(exit_lots * cfg.lot_size, position.remaining_quantity) \
                    if remaining_lots else position.remaining_quantity
                # the locked journal enum calls every partial target TARGET_3R, whatever its R
                exits.append(close_quantity(
                    OptionExitReason.TARGET_3R, position.target,
                    exit_quantity, exit_lots,
                ))
                position.partial_exit_done = True
                if not position.closed:
                    risk = position.entry_price * cfg.stop_loss_pct
                    floor = {"BREAKEVEN": position.entry_price, "LOCK_1R": position.entry_price + risk,
                             "KEEP": position.stop_loss}[cfg.after_partial]
                    position.stop_loss = max(position.stop_loss, floor)
                return exits

        if not position.closed and position.remaining_quantity > 0 and kama_value is not None:
            kama_exit = (
                position.direction == OptionTradeDirection.LONG
                and underlying_close < kama_value
            ) or (
                position.direction == OptionTradeDirection.SHORT
                and underlying_close > kama_value
            )
            if kama_exit:
                exits.append(close_quantity(
                    OptionExitReason.KAMA_EXIT, option_close,
                    position.remaining_quantity, position.remaining_lots,
                ))
        return exits


__all__ = ["BuyerLifecycleConfig", "BuyerOptionTradeLifecycle"]
