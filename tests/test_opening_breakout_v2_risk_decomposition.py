from types import SimpleNamespace

from scripts.audit_opening_breakout_v2_risk_decomposition import decompose_trade


def test_decomposition_separates_strategy_from_execution_and_costs():
    trade = SimpleNamespace(
        quantity=75,
        option_signal_price=100.0,
        entry=SimpleNamespace(price=101.0),
        stop_price=81.0,
        target_price=141.0,
        exit=SimpleNamespace(price=79.0, reason="STOP_LOSS"),
        gross_pnl=-1650.0,
        event=SimpleNamespace(direction="LONG", trigger_timestamp=1741000000),
    )

    row = decompose_trade(trade, entry_buffer=1.0, exit_buffer=2.0, intended_risk=2000.0)

    assert row["theoretical_strategy_pnl"] == -1425.0
    assert row["entry_execution_impact"] == -75.0
    assert row["exit_execution_impact"] == -150.0
    assert row["execution_adjusted_from_signal"] == -1650.0
    assert row["gross_pnl"] == -1650.0
    assert row["strategy_risk"] == 1500.0
    assert row["intended_risk"] == 2000.0
    assert row["realized_r"] == -1.1


from scripts.audit_opening_breakout_v2_risk_decomposition import summarize


def test_summary_reconciles_force_exit_separately():
    rows = [
        {
            "theoretical_strategy_pnl": -1425.0,
            "entry_execution_impact": -75.0,
            "exit_execution_impact": -150.0,
            "gross_pnl": -1650.0,
            "cost": 50.0,
            "brokerage": 10.0,
            "exchange_transaction": 10.0,
            "stt": 10.0,
            "sebi": 5.0,
            "stamp_duty": 5.0,
            "ipft": 5.0,
            "gst": 5.0,
            "net_pnl": -1700.0,
            "strategy_risk": 1500.0,
            "intended_risk": 2000.0,
            "exit_reason": "STOP_LOSS",
        },
        {
            "theoretical_strategy_pnl": None,
            "entry_execution_impact": -10.0,
            "exit_execution_impact": None,
            "gross_pnl": 500.0,
            "cost": 40.0,
            "brokerage": 10.0,
            "exchange_transaction": 10.0,
            "stt": 5.0,
            "sebi": 5.0,
            "stamp_duty": 5.0,
            "ipft": 2.0,
            "gst": 3.0,
            "net_pnl": 460.0,
            "strategy_risk": 1500.0,
            "intended_risk": 2000.0,
            "exit_reason": "FORCE_EXIT",
        },
    ]

    summary = summarize(rows)

    assert summary["entry_impact_known"] == -75.0
    assert summary["entry_impact_force"] == -10.0
    assert summary["exit_impact_known"] == -150.0
    assert summary["known_gross"] == -1650.0
    assert summary["force_exit_gross"] == 500.0
    assert summary["force_exit_residual"] == 510.0
    assert summary["gross"] == -1150.0
    assert summary["cost"] == 90.0
    assert summary["net"] == -1240.0


def test_summary_cost_components_reconcile():
    rows = [
        {
            "theoretical_strategy_pnl": -100.0,
            "entry_execution_impact": 0.0,
            "exit_execution_impact": 0.0,
            "gross_pnl": -100.0,
            "cost": 20.0,
            "brokerage": 10.0,
            "exchange_transaction": 2.0,
            "stt": 3.0,
            "sebi": 1.0,
            "stamp_duty": 1.0,
            "ipft": 1.0,
            "gst": 2.0,
            "net_pnl": -120.0,
            "strategy_risk": 100.0,
            "intended_risk": 200.0,
            "exit_reason": "STOP_LOSS",
        }
    ]
    summary = summarize(rows)
    assert summary["cost"] == 20.0
    assert (
        summary["brokerage"]
        + summary["exchange_transaction"]
        + summary["stt"]
        + summary["sebi"]
        + summary["stamp_duty"]
        + summary["ipft"]
        + summary["gst"]
    ) == summary["cost"]
    assert summary["net"] == summary["gross"] - summary["cost"]
