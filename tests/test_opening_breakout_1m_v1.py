from config import opening_breakout_1m as cfg
from research.opening_breakout_1m_v1 import (
    Candle, StrategyConfig, build_entry_signal, entry_allowed,
    entry_limit_price, opening_filter_passes, stop_loss_price,
    target_price, sl_trigger_limit_price,
)
from execution.opening_breakout_state import ExecutionState, OrderState


def test_default_research_strategy_is_disabled():
    assert cfg.OPENING_BREAKOUT_ENABLED_DEFAULT is False


def test_open_low_filter_tolerance():
    c = Candle(1, 100, 110, 100.02, 108)
    config = StrategyConfig(filter_open_low=True, open_equal_tolerance_points=0.05)
    assert opening_filter_passes(c, config)


def test_both_filters_false_bypass():
    c = Candle(1, 100, 110, 90, 105)
    config = StrategyConfig(filter_open_high=False, filter_open_low=False)
    assert opening_filter_passes(c, config)


def test_bias_blocks_opposite_direction():
    c = Candle(1, 100, 110, 100, 108)
    config = StrategyConfig(market_bias="DOWN", breakout_trigger="1_MIN_HIGH")
    assert build_entry_signal(c, config) is None


def test_manual_instrument_is_preserved():
    c = Candle(1, 100, 110, 100, 108)
    config = StrategyConfig(market_bias="UP", trade_instrument="PUT", breakout_trigger="1_MIN_HIGH")
    signal = build_entry_signal(c, config)
    assert signal is not None
    assert signal.instrument == "PUT"
    assert signal.direction == "LONG"


def test_low_breakout_is_short():
    c = Candle(1, 95, 105, 95, 98)
    config = StrategyConfig(filter_open_low=True, breakout_trigger="1_MIN_LOW")
    signal = build_entry_signal(c, config)
    assert signal is not None
    assert signal.direction == "SHORT"
    assert signal.breakout_price == 95


def test_entry_slippage_guard_and_marketable_limit():
    assert entry_allowed(105, 100, "LONG", 5)
    assert not entry_allowed(105.01, 100, "LONG", 5)
    assert entry_limit_price(105, "LONG", 2) == 107
    assert entry_limit_price(95, "SHORT", 2) == 93


def test_stop_and_rr_target():
    c = Candle(1, 100, 110, 100, 108)
    sl = stop_loss_price(120, c, "CUSTOM_POINTS", 20, direction="LONG")
    assert sl == 100
    assert target_price(120, sl, "RR_RATIO", rr_multiplier=2, direction="LONG") == 160


def test_sl_trigger_limit():
    assert sl_trigger_limit_price(100, "LONG", 2) == 98
    assert sl_trigger_limit_price(100, "SHORT", 2) == 102


def test_state_machine_transitions():
    s = ExecutionState()
    assert s.state == OrderState.PENDING_ENTRY
    s.mark_filled(100)
    assert s.state == OrderState.FILLED
    s.request_exit(
        __import__("execution.opening_breakout_state", fromlist=["OrderIntent"]).OrderIntent("SELL", 1, 98, "SL"),
        __import__("execution.opening_breakout_state", fromlist=["ExitReason"]).ExitReason.STOP_LOSS,
    )
    assert s.state == OrderState.EXIT_PENDING
    s.mark_closed(98)
    assert s.state == OrderState.CLOSED
