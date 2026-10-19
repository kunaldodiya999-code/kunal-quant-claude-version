"""
Kunal Quant Trade Candidate.

A TradeCandidate connects a strategy decision with the prices
needed by the risk engine.

This module does NOT decide:
    - where the stop loss should be
    - where the target should be
    - how a position should be exited
    - whether an order should actually be sent

Those remain separate strategy/risk/execution concerns.
"""

from __future__ import annotations

from dataclasses import dataclass

from risk.risk_engine import (
    RiskRequest,
    RiskResult,
    calculate_position_size,
)
from strategies.direction_filter import Direction
from strategies.ktmi_strategy import (
    KTMIEntryDecision,
    StrategyAction,
)


@dataclass(frozen=True)
class TradeCandidate:
    """Candidate trade before final execution."""

    direction: Direction

    entry_price: float

    stop_loss_price: float

    lot_size: int

    strategy_id: str = "KTMI_V1"

    config_version: str = "1.0"

    timestamp: int | None = None


@dataclass(frozen=True)
class TradePlan:
    """Trade candidate combined with calculated risk sizing."""

    candidate: TradeCandidate

    risk: RiskResult

    strategy_decision: KTMIEntryDecision

    @property
    def quantity(self) -> int:
        """Final quantity permitted by the risk engine."""

        return self.risk.quantity

    @property
    def lots(self) -> int:
        """Final number of complete lots."""

        return self.risk.lots

    @property
    def tradable(self) -> bool:
        """Return True when a non-zero position is possible."""

        return self.risk.has_position


def build_trade_plan(
    candidate: TradeCandidate,
    strategy_decision: KTMIEntryDecision,
    risk_method,
    fixed_risk_amount: float | None = None,
    risk_percent: float | None = None,
    capital: float = 0.0,
) -> TradePlan:
    """
    Build a risk-sized trade plan.

    The caller supplies the stop-loss price.
    This function does not calculate the stop-loss.
    """

    if strategy_decision.action == StrategyAction.NO_ENTRY:
        raise ValueError(
            "Cannot build a trade plan from NO_ENTRY."
        )

    expected_direction = (
        Direction.LONG
        if strategy_decision.action
        == StrategyAction.LONG
        else Direction.SHORT
    )

    if candidate.direction != expected_direction:
        raise ValueError(
            "Trade candidate direction does not match "
            "strategy decision."
        )

    request = RiskRequest(
        capital=capital,
        entry_price=candidate.entry_price,
        stop_loss_price=candidate.stop_loss_price,
        lot_size=candidate.lot_size,
        risk_method=risk_method,
        fixed_risk_amount=fixed_risk_amount,
        risk_percent=risk_percent,
    )

    risk_result = calculate_position_size(
        request
    )

    return TradePlan(
        candidate=candidate,
        risk=risk_result,
        strategy_decision=strategy_decision,
    )


__all__ = [
    "TradeCandidate",
    "TradePlan",
    "build_trade_plan",
]