from datetime import date
from types import SimpleNamespace

import pytest

from backtest.broker_cost_model import fyers_options_profile
from backtest.opening_breakout_v2_economic_attribution import (
    attribute_trade_economics,
)


def make_trade(*, exit_reason="STOP_LOSS", exit_price=79.0):
    return SimpleNamespace(
        quantity=75,
        option_signal_price=100.0,
        entry=SimpleNamespace(price=101.0),
        stop_price=81.0,
        target_price=141.0,
        exit=SimpleNamespace(price=exit_price, reason=exit_reason),
        gross_pnl=-1650.0 if exit_reason == "STOP_LOSS" else 0.0,
        event=SimpleNamespace(direction="LONG"),
    )


def test_closed_trade_economic_attribution_reconciles():
    trade = make_trade()
    row = attribute_trade_economics(
        trade,
        intended_risk=2000.0,
        trade_date=date(2025, 1, 2),
    )

    assert row.theoretical_strategy_pnl == -1425.0
    assert row.entry_execution_impact == -75.0
    assert row.exit_execution_impact == -150.0
    assert row.execution_adjusted_from_signal == -1650.0
    assert row.strategy_risk == 1500.0
    assert row.realized_r == -1.1
    assert row.net_pnl == pytest.approx(row.gross_pnl - row.total_cost)
    assert row.net_r == pytest.approx(row.net_pnl / row.strategy_risk)
    assert (
        row.brokerage
        + row.exchange_transaction
        + row.stt
        + row.sebi
        + row.stamp_duty
        + row.ipft
        + row.gst
    ) == pytest.approx(row.total_cost)


def test_force_exit_keeps_theoretical_outcome_unavailable():
    trade = make_trade(exit_reason="FORCE_EXIT", exit_price=105.0)
    trade.gross_pnl = 300.0

    row = attribute_trade_economics(
        trade,
        intended_risk=2000.0,
        cost_profile=fyers_options_profile(date(2025, 1, 2)),
    )

    assert row.theoretical_exit is None
    assert row.theoretical_strategy_pnl is None
    assert row.exit_execution_impact is None
    assert row.execution_adjusted_from_signal is None
    assert row.entry_execution_impact == -75.0
    assert row.gross_pnl == 300.0


def test_requires_explicit_date_or_profile():
    with pytest.raises(ValueError, match="trade_date"):
        attribute_trade_economics(make_trade(), intended_risk=2000.0)
