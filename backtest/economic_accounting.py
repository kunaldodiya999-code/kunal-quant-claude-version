"""Trade-level economic accounting for Kunal Quant.

This layer converts audited gross trade exits into execution-cost-adjusted
net P&L without changing signal or trade lifecycle logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from backtest.economic_costs import (
    EconomicCostConfig,
    EconomicCostModel,
)
from backtest.trade_audit import TradeAuditSummary


@dataclass(frozen=True)
class EconomicTradeSummary:
    trade_key: int
    strategy_id: str
    symbol: str
    direction: str
    gross_pnl: float
    slippage_cost: float
    fixed_charges: float
    total_cost: float
    net_pnl: float


@dataclass(frozen=True)
class EconomicTotals:
    trades: int
    gross_pnl: float
    slippage_cost: float
    fixed_charges: float
    total_cost: float
    net_pnl: float


def calculate_economic_trade(
    summary: TradeAuditSummary,
    *,
    model: EconomicCostModel,
) -> EconomicTradeSummary:
    if not summary.quantity_balanced:
        raise ValueError(
            f"Trade {summary.trade_key} has unbalanced quantity."
        )

    if not summary.pnl_balanced:
        raise ValueError(
            f"Trade {summary.trade_key} has unbalanced P&L."
        )

    exits = [
        {
            "price": exit_event.price,
            "quantity": exit_event.quantity,
        }
        for exit_event in summary.exits
    ]

    result = model.calculate_trade_net_pnl(
        direction=summary.direction,
        entry_price=summary.entry_price,
        entry_quantity=summary.entry_quantity,
        exits=exits,
        gross_pnl=summary.total_pnl,
    )

    return EconomicTradeSummary(
        trade_key=summary.trade_key,
        strategy_id=summary.strategy_id,
        symbol=summary.symbol,
        direction=summary.direction,
        gross_pnl=result.gross_pnl,
        slippage_cost=result.total_slippage,
        fixed_charges=result.total_fixed_charges,
        total_cost=result.total_cost,
        net_pnl=result.net_pnl,
    )


def calculate_economic_totals(
    summaries: Iterable[EconomicTradeSummary],
) -> EconomicTotals:
    rows = list(summaries)

    return EconomicTotals(
        trades=len(rows),
        gross_pnl=sum(row.gross_pnl for row in rows),
        slippage_cost=sum(row.slippage_cost for row in rows),
        fixed_charges=sum(row.fixed_charges for row in rows),
        total_cost=sum(row.total_cost for row in rows),
        net_pnl=sum(row.net_pnl for row in rows),
    )


DEFAULT_ECONOMIC_MODEL = EconomicCostModel(
    EconomicCostConfig(
        slippage_pct=0.0025,
        fixed_entry_charge=25.0,
        fixed_exit_charge=25.0,
    )
)
