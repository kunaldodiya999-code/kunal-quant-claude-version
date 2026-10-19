from config import hft_strategy
from research.hft_gap_open_v1 import (
    SetupCandle, capital_allocation, calculate_initial_sl,
    evaluate_entry, first_candle_open_equals_low, gap_signal,
    trailing_stop_price,
)

def test_defaults_are_configurable_and_disabled():
    assert hft_strategy.HFT_GAP_OPEN_ENABLED_DEFAULT is False
    assert hft_strategy.HFT_UNDERLYING_MODE == "NIFTY_FUTURES"
    assert hft_strategy.GAP_THRESHOLD_POINTS == 50.0
    assert hft_strategy.INITIAL_SL_MAX_POINTS == 20.0
    assert hft_strategy.CAPITAL_PER_LOT == 10_000.0
    assert hft_strategy.DEFAULT_LOTS == 4

def test_gap_direction():
    assert gap_signal(100.0, 151.0).side == "CALL"
    assert gap_signal(100.0, 49.0).side == "PUT"
    assert gap_signal(100.0, 149.9) is None

def test_first_candle_open_equals_low():
    assert first_candle_open_equals_low(SetupCandle(100, 110, 100, 108))
    assert not first_candle_open_equals_low(SetupCandle(100, 110, 99.99, 108))

def test_entry_requires_break_and_limit_fill():
    setup = SetupCandle(100, 120, 100, 118)
    assert evaluate_entry(setup, 120, 121).triggered is False
    assert evaluate_entry(setup, 125, 130).triggered is False
    filled = evaluate_entry(setup, 125, 121)
    assert filled.triggered is True
    assert filled.limit_price == 123

def test_initial_sl_is_capped_at_20_points():
    stop, risk = calculate_initial_sl(130, 100)
    assert stop == 110
    assert risk == 20

def test_initial_sl_uses_candle_low_inside_cap():
    stop, risk = calculate_initial_sl(110, 100)
    assert stop == 100
    assert risk == 10

def test_manual_trailing_example():
    assert trailing_stop_price(100, 125, 10, 15) == 115

def test_capital_allocation():
    assert capital_allocation(10_000, 4) == 40_000
