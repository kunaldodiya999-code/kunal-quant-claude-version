"""Performance analytics for Kunal Quant completed trades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate_pct: float
    gross_pnl: float
    average_trade_pnl: float
    average_win: float
    average_loss: float
    profit_factor: float | None
    largest_win: float
    largest_loss: float
    total_cost: float
    net_pnl: float
    total_exit_events: int
    total_quantity: int
    stop_exits: int
    target_partial_exits: int
    kama_exits: int
    end_of_data_exits: int


def calculate_performance(
    *,
    economic_rows: Iterable[object],
    audit_rows: Iterable[object],
) -> PerformanceMetrics:
    economic = list(economic_rows)
    audits = list(audit_rows)

    pnl_values = [float(row.net_pnl) for row in economic]
    gross_values = [float(row.gross_pnl) for row in economic]

    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    breakeven = [value for value in pnl_values if value == 0]

    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))

    profit_factor = (
        gross_profit / gross_loss_abs
        if gross_loss_abs > 0
        else None
    )

    total_quantity = sum(
        int(row.entry_quantity)
        for row in audits
    )

    return PerformanceMetrics(
        trades=len(economic),
        wins=len(wins),
        losses=len(losses),
        breakeven=len(breakeven),
        win_rate_pct=(
            len(wins) / len(economic) * 100
            if economic
            else 0.0
        ),
        gross_pnl=sum(gross_values),
        average_trade_pnl=(
            sum(pnl_values) / len(pnl_values)
            if pnl_values
            else 0.0
        ),
        average_win=(
            sum(wins) / len(wins)
            if wins
            else 0.0
        ),
        average_loss=(
            sum(losses) / len(losses)
            if losses
            else 0.0
        ),
        profit_factor=profit_factor,
        largest_win=max(pnl_values, default=0.0),
        largest_loss=min(pnl_values, default=0.0),
        total_cost=sum(float(row.total_cost) for row in economic),
        net_pnl=sum(pnl_values),
        total_exit_events=sum(
            int(row.exit_count)
            for row in audits
        ),
        total_quantity=total_quantity,
        stop_exits=sum(
            1 for row in audits
            if row.final_exit_reason == "STOP_LOSS"
        ),
        target_partial_exits=sum(
            int(row.partial_exit_count)
            for row in audits
        ),
        kama_exits=sum(
            1 for row in audits
            if row.final_exit_reason == "KAMA_EXIT"
        ),
        end_of_data_exits=sum(
            1 for row in audits
            if row.final_exit_reason == "END_OF_DATA"
        ),
    )
