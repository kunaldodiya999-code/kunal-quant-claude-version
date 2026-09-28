"""
Integration regression test for the V2 event audit ledger.

This is read-only and runs against the local historical database.
"""
from proposals.generate_reference_backtest_v2 import (
    load_all_complete_3m_bars,
    run_reference,
    select_last_days,
)
from strategies.ktmi_trigger_strategy import KTMITriggerStrategyConfig


def test_reference_v2_event_audit_accounts_for_all_selected_events():
    all_bars = load_all_complete_3m_bars()
    sample_bars = select_last_days(all_bars, 20)
    result = run_reference(
        all_bars=all_bars,
        sample_bars=sample_bars,
        trigger_config=KTMITriggerStrategyConfig(),
    )

    records = list(result["event_audit"])
    counts = result["counts"]

    assert len(records) == len(result["selected_events"])
    assert all(record["outcome"] is not None for record in records)

    assert sum(r["outcome"] == "closed" for r in records) == counts["closed"]
    assert sum(r["outcome"] == "open" for r in records) == counts["open"]
    assert sum(r["outcome"] == "lifecycle_rejected" for r in records) == counts["lifecycle_rejected"]
    assert sum(r["outcome"] == "allocation_rejected" for r in records) == counts.get("allocation_rejected", 0)
    assert sum(r["outcome"] == "unresolved" for r in records) == counts.get("unresolved", 0)
    assert sum(r["outcome"] == "no_entry_candle" for r in records) == counts.get("no_entry_candle", 0)
    assert sum(r["outcome"] == "outside_session" for r in records) == counts.get("outside_session", 0)

    entered = [r for r in records if r.get("lifecycle_action") == "ENTER"]
    assert len(entered) == 35
    assert sum(r["outcome"] == "closed" for r in entered) == 31
    assert sum(r["outcome"] == "open" for r in entered) == 2
    assert sum(r["outcome"] == "no_entry_candle" for r in entered) == 2

    for record in entered:
        if record["outcome"] in {"closed", "open"}:
            assert record["contract"]["symbol"]
            assert record["entry_timestamp"]
            assert record["entry_price"] is not None
        if record["outcome"] == "closed":
            assert record["exits"]
            assert record["total_pnl"] is not None
