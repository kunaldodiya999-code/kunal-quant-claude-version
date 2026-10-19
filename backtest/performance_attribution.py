"""Grouped performance attribution for completed option trades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class AttributionRow:
    key: str
    trades: int
    gross_pnl: float
    total_cost: float
    net_pnl: float
    wins: int
    losses: int
    win_rate_pct: float
    profit_factor: float | None


@dataclass(frozen=True)
class DrawdownMetrics:
    max_drawdown: float
    max_drawdown_pct: float
    peak_equity: float
    trough_equity: float


def _row(key: str, rows: list[object]) -> AttributionRow:
    pnls = [float(r.net_pnl) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    return AttributionRow(
        key=key,
        trades=len(rows),
        gross_pnl=sum(float(r.gross_pnl) for r in rows),
        total_cost=sum(float(r.total_cost) for r in rows),
        net_pnl=sum(pnls),
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=(len(wins) / len(rows) * 100) if rows else 0.0,
        profit_factor=(gp / gl) if gl else None,
    )


def group_attribution(
    *,
    economic_rows: Iterable[object],
    audit_rows: Iterable[object],
) -> dict[str, list[AttributionRow]]:
    economic = list(economic_rows)
    audits = list(audit_rows)

    if len(economic) != len(audits):
        raise ValueError("Economic and audit rows must have equal length.")

    by_strategy: dict[str, list[object]] = {}
    by_direction: dict[str, list[object]] = {}
    exit_reason_rows: dict[str, list[object]] = {}

    for e, a in zip(economic, audits):
        by_strategy.setdefault(str(e.strategy_id), []).append(e)
        by_direction.setdefault(str(e.direction), []).append(e)
        exit_reason_rows.setdefault(str(a.final_exit_reason), []).append(e)

    return {
        "strategy": [_row(k, v) for k, v in sorted(by_strategy.items())],
        "direction": [_row(k, v) for k, v in sorted(by_direction.items())],
        "final_exit_reason": [
            _row(k, v) for k, v in sorted(exit_reason_rows.items())
        ],
    }


def calculate_max_drawdown(
    *,
    starting_capital: float,
    economic_rows: Iterable[object],
) -> DrawdownMetrics:
    equity = float(starting_capital)
    peak = equity
    max_dd = 0.0
    max_dd_pct = 0.0
    drawdown_trough = equity

    for row in economic_rows:
        equity += float(row.net_pnl)

        if equity > peak:
            peak = equity

        dd = peak - equity
        dd_pct = (dd / peak * 100.0) if peak else 0.0

        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
            drawdown_trough = equity

    return DrawdownMetrics(
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        peak_equity=peak,
        trough_equity=drawdown_trough,
    )
