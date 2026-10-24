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


# ---- PUT side mirrored (owner decision 2026-10-25), targets, ladder, one config object

from research.hft_gap_open_v1 import (  # noqa: E402
    HftGapOpenConfig, exit_limit_price, option_ladder, setup_is_valid, target_prices,
)


def test_put_setup_is_the_mirror_of_the_call_setup():
    setup = SetupCandle(100, 100, 80, 82)                      # gap down: Open = High
    assert setup_is_valid(setup, "PUT") and not setup_is_valid(setup, "CALL")
    assert evaluate_entry(setup, 79, 80, "PUT").triggered is False          # broke 80 but not the limit 78
    filled = evaluate_entry(setup, 77, 80, "PUT")
    assert (filled.triggered, filled.limit_price, filled.initial_sl, filled.risk_points) == (True, 78, 98, 20)
    inside = evaluate_entry(SetupCandle(100, 100, 90, 92), 87, 89, "PUT")
    assert (inside.initial_sl, inside.risk_points) == (100, 13)             # setup high within the 20 cap


def test_targets_trailing_and_exit_limit_follow_the_side():
    assert target_prices(100, 10, "CALL") == [120, 130, 140]
    assert target_prices(100, 10, "PUT") == [80, 70, 60]
    assert target_prices(100, 10, config=HftGapOpenConfig(targets_enabled=False)) == []
    assert trailing_stop_price(100, 75, 10, 15, side="PUT") == 85
    assert trailing_stop_price(100, 90, 10, 15, side="PUT") is None
    assert exit_limit_price(50.0) == 48.0


def test_ladder_is_out_of_the_money_on_both_sides_and_everything_is_configurable():
    assert option_ladder(24000, "CALL") == [(24000 + k, "CE") for k in (0, 50, 100, 150, 200, 250)]
    assert option_ladder(24000, "PUT") == [(24000 - k, "PE") for k in (0, 50, 100, 150, 200, 250)]
    custom = HftGapOpenConfig(gap_threshold=30, initial_sl_max_points=15)
    assert gap_signal(100.0, 131.0, custom).side == "CALL" and gap_signal(100.0, 131.0) is None
    assert HftGapOpenConfig().enabled is False
