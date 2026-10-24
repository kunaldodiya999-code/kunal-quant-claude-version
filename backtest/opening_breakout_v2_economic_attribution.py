"""Economic attribution for Opening Breakout V2 option trades.

Reporting/accounting layer only. This module does not alter signal, sizing,
execution, stop/target, or broker-cost behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from backtest.broker_cost_model import (
    OptionsCostProfile,
    calculate_options_trade_costs,
    fyers_options_profile,
)


@dataclass(frozen=True)
class TradeEconomicAttribution:
    signal_price: float
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    quantity: int
    exit_reason: str
    theoretical_exit: float | None
    theoretical_strategy_pnl: float | None
    entry_execution_impact: float
    exit_execution_impact: float | None
    gross_pnl: float
    strategy_risk: float
    intended_risk: float
    realized_r: float
    brokerage: float
    exchange_transaction: float
    stt: float
    sebi: float
    stamp_duty: float
    ipft: float
    gst: float
    total_cost: float
    net_pnl: float
    net_r: float
    execution_adjusted_from_signal: float | None


def attribute_trade_economics(
    trade: Any,
    *,
    intended_risk: float,
    cost_profile: OptionsCostProfile | None = None,
    trade_date: date | None = None,
) -> TradeEconomicAttribution:
    """Attribute one already-simulated closed trade without changing it."""
    if trade.quantity <= 0:
        raise ValueError("trade quantity must be > 0")
    if trade.entry.price is None or trade.exit.price is None:
        raise ValueError("closed trade must have entry and exit prices")
    if trade.stop_price is None or trade.target_price is None:
        raise ValueError("closed trade must have stop and target prices")

    qty = int(trade.quantity)
    signal = float(trade.option_signal_price)
    entry = float(trade.entry.price)
    stop = float(trade.stop_price)
    target = float(trade.target_price)
    exit_price = float(trade.exit.price)
    gross = float(trade.gross_pnl)
    exit_reason = str(trade.exit.reason)
    multiplier = 1.0 if trade.event.direction == "LONG" else -1.0

    if exit_reason == "STOP_LOSS":
        theoretical_exit = stop
    elif exit_reason == "TARGET":
        theoretical_exit = target
    else:
        theoretical_exit = None

    theoretical_strategy_pnl = (
        (theoretical_exit - signal) * qty * multiplier
        if theoretical_exit is not None
        else None
    )
    entry_impact = (signal - entry) * qty * multiplier

    exit_impact = (
        (exit_price - theoretical_exit) * qty * multiplier
        if theoretical_exit is not None
        else None
    )
    execution_adjusted = (
        theoretical_strategy_pnl + entry_impact + exit_impact
        if theoretical_strategy_pnl is not None and exit_impact is not None
        else None
    )

    if cost_profile is None:
        if trade_date is None:
            trade_date = getattr(trade, "event_date", None)
        if trade_date is None:
            raise ValueError(
                "trade_date is required when cost_profile is not supplied"
            )
        cost_profile = fyers_options_profile(trade_date)

    costs = calculate_options_trade_costs(
        entry_price=entry,
        exit_price=exit_price,
        quantity=qty,
        profile=cost_profile,
        gross_pnl=gross,
    )

    strategy_risk = abs(entry - stop) * qty
    realized_r = gross / strategy_risk if strategy_risk > 0 else 0.0
    net_r = costs.net_pnl / strategy_risk if strategy_risk > 0 else 0.0

    return TradeEconomicAttribution(
        signal_price=signal,
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        exit_price=exit_price,
        quantity=qty,
        exit_reason=exit_reason,
        theoretical_exit=theoretical_exit,
        theoretical_strategy_pnl=theoretical_strategy_pnl,
        entry_execution_impact=entry_impact,
        exit_execution_impact=exit_impact,
        gross_pnl=gross,
        strategy_risk=strategy_risk,
        intended_risk=float(intended_risk),
        realized_r=realized_r,
        brokerage=costs.brokerage,
        exchange_transaction=costs.exchange_transaction,
        stt=costs.stt,
        sebi=costs.sebi,
        stamp_duty=costs.stamp_duty,
        ipft=costs.ipft,
        gst=costs.gst,
        total_cost=costs.total_cost,
        net_pnl=costs.net_pnl,
        net_r=net_r,
        execution_adjusted_from_signal=execution_adjusted,
    )
