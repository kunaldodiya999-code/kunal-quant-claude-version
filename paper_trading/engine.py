"""Deterministic paper-trading core; deliberately has no broker/order API.

This module coordinates independent strategy positions while delegating all
option position sizing and exit rules to the locked OptionTradeLifecycle V1.
It accepts already-resolved contracts and observed prices; market-data and
contract-resolution adapters are intentionally separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from math import isfinite
from typing import Optional

from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradeLifecycle,
    OptionTradeLifecycleConfig,
    OptionTradePosition,
)
from paper_trading.recorder import PaperTradeRecorder


class PaperStrategyId(str, Enum):
    STRATEGY_A = "KTMI_LONG_SHORT_SPEED"
    STRATEGY_B = "KTMI_MOMENTUM_ONLY"
    MODULE_CONFLUENCE = "KTMI_MODULE_CONFLUENCE"


@dataclass(frozen=True)
class PaperEngineConfig:
    """Independent ON/OFF switches; all three strategies default to enabled."""

    strategy_a_enabled: bool = True
    strategy_b_enabled: bool = True
    module_confluence_enabled: bool = True
    lifecycle_config: OptionTradeLifecycleConfig = field(
        default_factory=OptionTradeLifecycleConfig
    )

    def is_enabled(self, strategy_id: PaperStrategyId) -> bool:
        return {
            PaperStrategyId.STRATEGY_A: self.strategy_a_enabled,
            PaperStrategyId.STRATEGY_B: self.strategy_b_enabled,
            PaperStrategyId.MODULE_CONFLUENCE: self.module_confluence_enabled,
        }[strategy_id]


@dataclass
class PaperTradeRecord:
    """One paper trade and all lifecycle exit events belonging to it."""

    strategy_id: PaperStrategyId
    entry_timestamp: int
    position: OptionTradePosition
    exits: list[OptionTradeExit] = field(default_factory=list)
    last_processed_timestamp: Optional[int] = None

    @property
    def closed(self) -> bool:
        return self.position.closed

    @property
    def gross_pnl(self) -> float:
        return self.position.gross_pnl


class PaperTradingEngine:
    """Strategy-isolated paper position state using locked lifecycle rules.

    At most one position per strategy may be open at a time. Different
    strategies can hold independent positions simultaneously, including on
    the same symbol. Disabled strategies cannot open new positions.
    This class never creates a broker client or submits an order.
    """

    def __init__(
        self,
        config: Optional[PaperEngineConfig] = None,
        *,
        recorder: PaperTradeRecorder | None = None,
        lifecycle: object | None = None,
    ) -> None:
        self.config = config or PaperEngineConfig()
        self.recorder = recorder
        # Default remains the locked V1 lifecycle. Buyer-only paper behaviour
        # must be explicitly injected; historical V1 is never rewritten.
        self.lifecycle = (
            lifecycle if lifecycle is not None
            else OptionTradeLifecycle(self.config.lifecycle_config)
        )
        self.trade_logs: dict[PaperStrategyId, list[PaperTradeRecord]] = {
            strategy_id: [] for strategy_id in PaperStrategyId
        }
        self.active_positions: dict[PaperStrategyId, PaperTradeRecord] = {}

    @staticmethod
    def _strategy_id(value: PaperStrategyId | str | Enum) -> PaperStrategyId:
        raw = value.value if isinstance(value, Enum) else value
        try:
            return PaperStrategyId(str(raw))
        except ValueError as exc:
            raise ValueError(f"Unsupported paper strategy: {raw}") from exc

    @staticmethod
    def _direction(value: OptionTradeDirection | str | Enum) -> OptionTradeDirection:
        raw = value.value if isinstance(value, Enum) else value
        try:
            return OptionTradeDirection(str(raw).upper())
        except ValueError as exc:
            raise ValueError(f"Unsupported trade direction: {raw}") from exc

    def open_position(
        self,
        *,
        strategy_id: PaperStrategyId | str | Enum,
        direction: OptionTradeDirection | str | Enum,
        symbol: str,
        entry_price: float,
        timestamp: int,
    ) -> Optional[PaperTradeRecord]:
        """Open a simulated position from a validated option entry quote.

        Returns None when the strategy is disabled or already has an open
        position. Invalid price/allocation inputs are rejected by V1.
        """
        strategy = self._strategy_id(strategy_id)
        if not self.config.is_enabled(strategy):
            return None

        current = self.active_positions.get(strategy)
        if current is not None and not current.closed:
            return None

        position = self.lifecycle.create_position(
            strategy_id=strategy.value,
            direction=self._direction(direction),
            symbol=symbol,
            entry_price=entry_price,
        )
        record = PaperTradeRecord(
            strategy_id=strategy,
            entry_timestamp=int(timestamp),
            position=position,
            last_processed_timestamp=int(timestamp),
        )
        # Persist the entry before exposing it as an accepted paper position.
        # A disk error therefore fails visibly instead of silently losing the entry.
        if self.recorder is not None:
            self.recorder.record_trade_open(record)
        self.trade_logs[strategy].append(record)
        self.active_positions[strategy] = record
        return record

    def process_option_candle(
        self,
        *,
        strategy_id: PaperStrategyId | str | Enum,
        timestamp: int,
        option_high: float,
        option_low: float,
        option_close: float,
        underlying_close: float,
        kama_value: Optional[float],
    ) -> list[OptionTradeExit]:
        """Advance only the selected strategy's position through lifecycle V1."""
        strategy = self._strategy_id(strategy_id)
        record = self.active_positions.get(strategy)
        if record is None or record.closed:
            return []

        candle_timestamp = int(timestamp)
        if record.last_processed_timestamp is not None and candle_timestamp <= record.last_processed_timestamp:
            raise ValueError(
                "Option candle timestamps must be strictly increasing and later than entry."
            )

        exits = self.lifecycle.process_candle(
            position=record.position,
            timestamp=candle_timestamp,
            option_high=float(option_high),
            option_low=float(option_low),
            option_close=float(option_close),
            underlying_close=float(underlying_close),
            kama_value=kama_value,
        )
        record.exits.extend(exits)
        record.last_processed_timestamp = candle_timestamp
        if self.recorder is not None:
            for exit_event in exits:
                self.recorder.record_trade_exit(record, exit_event)
        return exits

    def force_close(
        self,
        strategy_id: PaperStrategyId | str | Enum,
        *,
        timestamp: int,
        price: float,
        reason: OptionExitReason = OptionExitReason.END_OF_DATA,
    ) -> Optional[OptionTradeExit]:
        """Close the whole remaining position at ``price`` (forced exit or kill switch).

        Uses the existing END_OF_DATA reason so the locked lifecycle enum is not
        changed; the cause is recorded separately by SessionControls.
        """
        strategy = self._strategy_id(strategy_id)
        record = self.active_positions.get(strategy)
        if record is None or record.closed:
            return None
        price = float(price)
        if not isfinite(price) or price <= 0:
            raise ValueError("A forced exit needs a finite, positive price.")
        ts = int(timestamp)
        if record.last_processed_timestamp is not None and ts <= record.last_processed_timestamp:
            raise ValueError("Forced exit must be later than the last processed candle.")
        position = record.position
        quantity, lots = position.remaining_quantity, position.remaining_lots
        pnl = self.lifecycle.calculate_pnl(
            direction=position.direction, entry_price=position.entry_price,
            exit_price=price, quantity=quantity,
        )
        position.gross_pnl += pnl
        position.remaining_quantity = 0
        position.remaining_lots = 0
        position.closed = True
        exit_event = OptionTradeExit(
            timestamp=ts, reason=reason, price=price, quantity=quantity, lots=lots,
            pnl=pnl, remaining_quantity=0, remaining_lots=0,
        )
        record.exits.append(exit_event)
        record.last_processed_timestamp = ts
        if self.recorder is not None:
            self.recorder.record_trade_exit(record, exit_event)
        return exit_event

    def open_trade(self, strategy_id: PaperStrategyId | str | Enum) -> Optional[PaperTradeRecord]:
        """Return the selected strategy's active trade, if any."""
        strategy = self._strategy_id(strategy_id)
        record = self.active_positions.get(strategy)
        return record if record is not None and not record.closed else None

    def trades(self, strategy_id: PaperStrategyId | str | Enum) -> tuple[PaperTradeRecord, ...]:
        """Return an immutable snapshot of one strategy's paper trade log."""
        return tuple(self.trade_logs[self._strategy_id(strategy_id)])

    def all_trades(self) -> tuple[PaperTradeRecord, ...]:
        """Return all trade records grouped by strategy insertion order."""
        return tuple(
            trade
            for strategy in PaperStrategyId
            for trade in self.trade_logs[strategy]
        )
