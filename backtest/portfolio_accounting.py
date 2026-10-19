"""Portfolio equity accounting helpers for historical backtests.

This module only accounts for already-simulated closed trades. It does not
change signal, execution, sizing, resolver, or cost-model behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class EquityPoint:
    timestamp: int
    gross_pnl: float
    costs: float
    net_pnl: float
    equity: float
    peak_equity: float
    drawdown: float
    drawdown_pct: float


@dataclass(frozen=True)
class PortfolioAccountingResult:
    initial_capital: float
    ending_equity: float
    gross_pnl: float
    total_costs: float
    net_pnl: float
    peak_equity: float
    max_drawdown: float
    max_drawdown_pct: float
    wins: int
    losses: int
    win_rate_pct: float
    equity_curve: tuple[EquityPoint, ...]


def build_equity_curve(
    *,
    initial_capital: float,
    trades: Iterable[tuple[int, float, float]],
) -> PortfolioAccountingResult:
    """Build sequential equity from (timestamp, gross_pnl, costs) trades."""
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")

    equity = float(initial_capital)
    peak_equity = equity
    gross_pnl = 0.0
    total_costs = 0.0
    wins = 0
    losses = 0
    points: list[EquityPoint] = []

    for timestamp, gross, costs in sorted(trades, key=lambda item: item[0]):
        gross = float(gross)
        costs = float(costs)
        net = gross - costs
        equity += net
        peak_equity = max(peak_equity, equity)
        drawdown = peak_equity - equity
        drawdown_pct = (drawdown / peak_equity * 100.0) if peak_equity else 0.0

        gross_pnl += gross
        total_costs += costs
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1

        points.append(
            EquityPoint(
                timestamp=int(timestamp),
                gross_pnl=gross,
                costs=costs,
                net_pnl=net,
                equity=equity,
                peak_equity=peak_equity,
                drawdown=drawdown,
                drawdown_pct=drawdown_pct,
            )
        )

    closed = wins + losses
    net_pnl = gross_pnl - total_costs
    max_drawdown = max((point.drawdown for point in points), default=0.0)
    max_drawdown_pct = max(
        (point.drawdown_pct for point in points),
        default=0.0,
    )

    return PortfolioAccountingResult(
        initial_capital=float(initial_capital),
        ending_equity=equity,
        gross_pnl=gross_pnl,
        total_costs=total_costs,
        net_pnl=net_pnl,
        peak_equity=peak_equity,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        wins=wins,
        losses=losses,
        win_rate_pct=(wins / closed * 100.0) if closed else 0.0,
        equity_curve=tuple(points),
    )


__all__ = [
    "EquityPoint",
    "PortfolioAccountingResult",
    "build_equity_curve",
]
