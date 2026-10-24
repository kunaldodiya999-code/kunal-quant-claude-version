from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from backtest.opening_breakout_v2_fill_engine import (
    HistoricalBar,
    simulate_exit,
    simulate_limit_fill,
)


def bar(ts, o, h, l, c):
    return HistoricalBar(ts, o, h, l, c)


def test_entry_never_fills_on_signal_candle():
    bars = [
        bar(100, 100, 110, 99, 109),
        bar(101, 111, 112, 110, 111),
    ]
    result = simulate_limit_fill(
        bars,
        start_after_timestamp=100,
        side="BUY",
        limit_price=110,
        timeout_seconds=10,
    )
    assert result.filled
    assert result.timestamp == 101
    assert result.price == 110


def test_buy_fill_uses_open_when_market_opens_below_limit():
    result = simulate_limit_fill(
        [bar(101, 108, 112, 107, 111)],
        start_after_timestamp=100,
        side="BUY",
        limit_price=110,
        timeout_seconds=10,
    )
    assert result.price == 108


def test_one_minute_historical_window_reaches_next_bar():
    result = simulate_limit_fill(
        [bar(160, 173.25, 185, 170.95, 184.20)],
        start_after_timestamp=100,
        side="BUY",
        limit_price=174.55,
        timeout_seconds=60,
    )
    assert result.filled
    assert result.timestamp == 160
    assert result.price == 173.25


def test_timeout_does_not_invent_fill():
    result = simulate_limit_fill(
        [bar(120, 100, 101, 99, 100)],
        start_after_timestamp=100,
        side="BUY",
        limit_price=110,
        timeout_seconds=10,
    )
    assert not result.filled
    assert result.reason == "FILL_TIMEOUT"


def test_stop_wins_when_stop_and_target_share_same_bar():
    policy = V2ExecutionPolicy(exit_buffer_points=2)
    result, final_stop = simulate_exit(
        [bar(101, 100, 110, 90, 105)],
        entry_timestamp=100,
        direction="LONG",
        quantity=65,
        stop_price=95,
        target_price=105,
        policy=policy,
        entry_price=100,
    )
    assert result.reason == "STOP_LOSS"
    assert result.timestamp == 101
    assert final_stop == 95


def test_force_exit_uses_bar_open_after_cutoff():
    policy = V2ExecutionPolicy()
    result, _ = simulate_exit(
        [bar(101, 102, 105, 101, 104)],
        entry_timestamp=100,
        direction="LONG",
        quantity=65,
        stop_price=90,
        target_price=120,
        policy=policy,
        force_exit_timestamp=101,
        entry_price=100,
    )
    assert result.reason == "FORCE_EXIT"
    assert result.price == 102
