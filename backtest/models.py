"""Core models for the Kunal Quant backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    TIME_EXIT = "TIME_EXIT"
    MANUAL = "MANUAL"
    END_OF_DATA = "END_OF_DATA"

    KAMA_LONG_CLOSE_BELOW = "KAMA_LONG_CLOSE_BELOW"
    KAMA_SHORT_CLOSE_ABOVE = "KAMA_SHORT_CLOSE_ABOVE"


@dataclass(frozen=True)
class BacktestBar:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: int = 0
    open_interest: Optional[int] = None


@dataclass(frozen=True)
class OpenPosition:
    direction: str
    entry_timestamp: int
    entry_price: float
    quantity: int

    # Original V1/V2 terminology.
    lot_size: int = 1
    stop_loss: Optional[float] = None
    target: Optional[float] = None

    strategy_id: str = "UNKNOWN"
    config_version: str = "UNKNOWN"

    planned_risk: float = 0.0

    # Original market price before entry slippage.
    entry_reference_price: Optional[float] = None

    # Compatibility aliases for newer code.
    @property
    def stop_loss_price(self) -> Optional[float]:
        return self.stop_loss

    @property
    def target_price(self) -> Optional[float]:
        return self.target


@dataclass(frozen=True)
class CompletedTrade:
    direction: str

    entry_timestamp: int
    entry_price: float

    exit_timestamp: int
    exit_price: float

    quantity: int

    # Gross P&L before transaction costs.
    pnl: float

    # Net P&L after transaction costs.
    net_pnl: float

    exit_reason: ExitReason

    strategy_id: str = "UNKNOWN"
    config_version: str = "UNKNOWN"

    holding_bars: int = 0

    planned_risk: float = 0.0
    realized_risk: float = 0.0
    maximum_adverse_excursion: float = 0.0

    entry_reference_price: Optional[float] = None
    exit_reference_price: Optional[float] = None

    entry_slippage: float = 0.0
    exit_slippage: float = 0.0

    entry_fixed_charge: float = 0.0
    exit_fixed_charge: float = 0.0

    total_cost: float = 0.0

    # ----------------------------------------------------------
    # Backward-compatible V1/V2 property.
    # ----------------------------------------------------------

    @property
    def gross_pnl(self) -> float:
        return self.pnl


@dataclass(frozen=True)
class BacktestResult:
    trades: tuple[CompletedTrade, ...]

    initial_capital: float
    final_equity: float

    @property
    def total_pnl(self) -> float:
        """Backward-compatible total P&L.

        When costs are enabled this is NET P&L.
        """

        return sum(
            trade.net_pnl
            for trade in self.trades
        )

    @property
    def gross_pnl(self) -> float:
        return sum(
            trade.pnl
            for trade in self.trades
        )

    @property
    def total_cost(self) -> float:
        return sum(
            trade.total_cost
            for trade in self.trades
        )

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def winning_trades(self) -> int:
        return sum(
            1
            for trade in self.trades
            if trade.net_pnl > 0
        )

    @property
    def losing_trades(self) -> int:
        return sum(
            1
            for trade in self.trades
            if trade.net_pnl < 0
        )

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0

        return (
            self.winning_trades
            / self.trade_count
            * 100.0
        )