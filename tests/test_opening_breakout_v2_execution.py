from datetime import datetime

from execution.opening_breakout_v2_execution import (
    V2ExecutionPolicy,
    build_entry_intent,
    build_exit_intent,
    entry_side,
    entry_window_open,
    exit_side,
    force_exit_due,
)
from research.opening_breakout_1m_v2 import Signal


def test_option_entry_is_always_buy_and_uses_upward_marketable_limit():
    signal = Signal("SHORT", "PUT", "OPEN_HIGH+CANDLE_LOW", 1)
    policy = V2ExecutionPolicy(entry_buffer_points=2)
    intent = build_entry_intent(signal, 65, 100, policy)
    assert entry_side(signal) == "BUY"
    assert intent.side == "BUY"
    assert intent.limit_price == 102


def test_futures_short_entry_uses_sell_side_and_downward_limit():
    signal = Signal("SHORT", "FUTURES", "CANDLE_LOW", 1)
    policy = V2ExecutionPolicy(entry_buffer_points=2)
    intent = build_entry_intent(signal, 50, 100, policy)
    assert intent.side == "SELL"
    assert intent.limit_price == 98


def test_option_exit_is_sell_and_marketable_below_trigger():
    signal = Signal("SHORT", "PUT", "OPEN_HIGH", 1)
    policy = V2ExecutionPolicy(exit_buffer_points=2)
    intent = build_exit_intent(signal, 65, 90, "SL", policy)
    assert exit_side(signal) == "SELL"
    assert intent.side == "SELL"
    assert intent.limit_price == 88


def test_entry_window_and_force_exit():
    policy = V2ExecutionPolicy(
        entry_start_hhmm="09:15",
        entry_end_hhmm="15:10",
        force_exit_hhmm="15:15",
    )
    assert entry_window_open(datetime(2026, 9, 29, 9, 15), policy)
    assert not entry_window_open(datetime(2026, 9, 29, 15, 11), policy)
    assert force_exit_due(datetime(2026, 9, 29, 15, 15), policy)
