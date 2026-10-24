from research import hft_gap_open_v1 as strategy
from scripts.inspect_hft_10s_signal import (
    classify_gap,
    high_breaks,
    opening_gap,
    open_equals_low,
)


def test_opening_gap_and_direction():
    assert opening_gap(23000, 22920) == -80
    assert classify_gap(80) == "CALL"
    assert classify_gap(-80) == "PUT"
    assert classify_gap(49.99) == "NONE"


def test_first_candle_open_equals_low_is_exact():
    assert open_equals_low(100.0, 100.0) is True
    assert open_equals_low(100.0, 99.99) is False


def test_next_candle_must_break_setup_high():
    assert high_breaks(110.0, 110.01) is True
    assert high_breaks(110.0, 110.0) is False
    assert high_breaks(110.0, 109.99) is False


def test_forensic_helpers_match_strategy_gap_threshold():
    assert strategy.GAP_THRESHOLD_POINTS == 50.0
    assert classify_gap(50.0, strategy.GAP_THRESHOLD_POINTS) == "CALL"
    assert classify_gap(-50.0, strategy.GAP_THRESHOLD_POINTS) == "PUT"
