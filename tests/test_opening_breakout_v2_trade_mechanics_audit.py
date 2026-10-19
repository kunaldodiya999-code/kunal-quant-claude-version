from scripts.audit_opening_breakout_v2_trade_mechanics import summarize_trades


def test_summarize_trades_classifies_exit_and_pnl():
    class Event:
        trigger_timestamp = 0

    class Contract:
        symbol = "TEST"

    class Fill:
        def __init__(self, price, reason):
            self.price = price
            self.reason = reason

    class Trade:
        status = "CLOSED"
        event = Event()
        contract = Contract()
        quantity = 75
        lots = 1
        entry = Fill(100.0, "FILLED")
        exit = Fill(80.0, "STOP_LOSS")
        stop_price = 80.0
        gross_pnl = -1500.0

    summary = summarize_trades([Trade()])
    assert summary["closed"] == 1
    assert summary["exit_reasons"] == {"STOP_LOSS": 1}
    assert summary["pnl_buckets"] == {"LOSS": 1}
    assert summary["quantities"][75] == 1
    assert summary["gross_pnl"] == -1500.0
