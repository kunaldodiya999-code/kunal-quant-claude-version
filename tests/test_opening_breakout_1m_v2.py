from datetime import datetime

import pytest

from config import opening_breakout_1m_v2 as cfg
from execution.opening_breakout_chart import EntryWindow, TradeChartTool
from research.opening_breakout_1m_v2 import (
    Candle,
    ContractQuote,
    IndicatorSnapshot,
    OptionOpeningCandle,
    build_opening_alerts,
    V2Config,
    build_signals,
    calculation_timeframe,
    calculate_position_size,
    entry_allowed,
    entry_limit_price,
    opening_candidate_directions,
    select_option_contract,
    stop_loss_price,
    target_price,
    trailing_stop_price,
)


def test_default_schema_values_match_requested_defaults():
    assert cfg.CAPITAL_ALLOCATION_PERCENT == 100.0
    assert cfg.MARKET_BIAS == "NEUTRAL"
    assert cfg.DMI_LENGTH == 14
    assert cfg.DMI_ADX_SMOOTHING == 14
    assert cfg.DMI_BUY_CALL_PLUS_DI == 25.0
    assert cfg.DMI_BUY_PUT_MINUS_DI == 25.0
    assert cfg.DMI_ADX_THRESHOLD == 25.0


def test_tolerance_is_absolute_price_distance_and_inclusive():
    candle = Candle(1, 100, 105, 99, 103)
    config = V2Config(
        filter_open_low=True,
        open_equal_tolerance_points=1.0,
        selected_triggers=(),
    )
    assert opening_candidate_directions(candle, config) == ("LONG",)


def test_opening_high_and_low_are_independent_candidates_when_both_enabled():
    candle = Candle(1, 100, 100.04, 99.96, 100.0)
    config = V2Config(
        filter_open_high=True,
        filter_open_low=True,
        open_equal_tolerance_points=0.05,
        selected_triggers=(),
    )
    assert opening_candidate_directions(candle, config) == ("LONG", "SHORT")


def test_opening_alerts_show_both_option_sides_independently():
    items = [
        OptionOpeningCandle("CE1", 24000, "CE", Candle(1, 100, 110, 100, 108)),
        OptionOpeningCandle("PE1", 24000, "PE", Candle(1, 100, 100, 90, 92)),
    ]
    config = V2Config(
        filter_open_low=True,
        filter_open_high=True,
        open_equal_tolerance_points=0.0,
        selected_triggers=(),
    )
    alerts = build_opening_alerts(items, config)
    assert {a.symbol for a in alerts} == {"CE1", "PE1"}
    assert {a.condition for a in alerts} == {"OPEN_LOW", "OPEN_HIGH"}


def test_multiple_timeframes_force_one_minute_calculation():
    assert calculation_timeframe(("3M", "5M")) == "1M"
    assert calculation_timeframe(("3M",)) == "3M"


def test_selected_triggers_are_and_conditions():
    candle = Candle(1, 100, 110, 100, 108)
    indicators = IndicatorSnapshot(vwap=105)
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH", "ABOVE_VWAP"),
        trade_instrument="CALL",
    )
    assert build_signals(candle, indicators, config, current_ltp=110)


def test_candle_high_requires_actual_crossing_price():
    candle = Candle(1, 100, 110, 100, 108)
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH",),
        trade_instrument="CALL",
    )
    assert not build_signals(candle, IndicatorSnapshot(), config, current_ltp=109)
    assert build_signals(candle, IndicatorSnapshot(), config, current_ltp=110)


def test_ktmi_call_defaults_and_thresholds():
    candle = Candle(1, 100, 110, 100, 108)
    indicators = IndicatorSnapshot(
        ktmi_buying_speed=0.5,
        ktmi_momentum_speed=0.5,
    )
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("KTMI",),
        trade_instrument="CALL",
    )
    assert build_signals(candle, indicators, config)


def test_dmi_put_requires_minus_di_and_adx():
    candle = Candle(1, 105, 105, 90, 92)
    indicators = IndicatorSnapshot(minus_di=25, adx=25)
    config = V2Config(
        filter_open_high=True,
        selected_triggers=("DMI",),
        trade_instrument="PUT",
    )
    assert build_signals(candle, indicators, config)


def test_spot_and_futures_are_not_forced_into_call_put():
    candle = Candle(1, 100, 110, 100, 108)
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH",),
        trade_instrument="SPOT",
    )
    signals = build_signals(candle, IndicatorSnapshot(), config, current_ltp=110)
    assert signals[0].instrument == "SPOT"
    assert signals[0].direction == "LONG"


def test_risk_sizing_matches_user_example():
    config = V2Config(
        capital_allocation_percent=100,
        sl_mode="CUSTOM_POINTS",
        risk_method="FIXED_AMOUNT",
        risk_per_trade_value=10000,
    )
    result = calculate_position_size(
        capital=100000,
        entry_price=100,
        stop_loss_price_value=80,
        lot_size=65,
        config=config,
    )
    assert result.lots == 7
    assert result.quantity == 455
    assert result.actual_risk == 9100
    assert result.notional == 45500


def test_capital_allocation_can_reduce_risk_sized_position():
    config = V2Config(
        capital_allocation_percent=40,
        sl_mode="CUSTOM_POINTS",
        risk_method="FIXED_AMOUNT",
        risk_per_trade_value=10000,
    )
    result = calculate_position_size(100000, 100, 80, 65, config)
    assert result.quantity == 390
    assert result.lots == 6


def test_value_sl_cap_is_whole_position_budget():
    config = V2Config(
        capital_allocation_percent=100,
        sl_mode="VALUE",
        sl_value_cap=10000,
        risk_method="FIXED_AMOUNT",
        risk_per_trade_value=20000,
    )
    result = calculate_position_size(100000, 100, 80, 65, config)
    assert result.risk_budget == 10000
    assert result.actual_risk <= 10000


def test_tp_value_is_whole_position_value():
    assert target_price(
        fill_price=100,
        stop_price=80,
        mode="VALUE",
        direction="LONG",
        value_target=10000,
        quantity=500,
    ) == 120


def test_price_range_and_lot_value_contract_selection():
    contracts = [
        ContractQuote("A", "CE", 24000, 90, 65),
        ContractQuote("B", "CE", 24100, 100, 65),
        ContractQuote("C", "CE", 24200, 110, 65),
    ]
    chosen = select_option_contract(
        contracts, "PRICE_RANGE", 10000, 80, 100
    )
    # PRICE_RANGE accepts every contract inside the configured range; the
    # current deterministic selector returns the first eligible contract.
    assert chosen.symbol == "A"

    chosen = select_option_contract(
        contracts, "LOT_VALUE", 6500, 80, 120
    )
    assert chosen.symbol == "B"


def test_trailing_points_moves_stop_up_from_planned_stop_and_never_back():
    stop = trailing_stop_price(
        entry_price=100,
        planned_stop_price=80,
        current_stop_price=80,
        current_price=140,
        direction="LONG",
        enabled=True,
        mode="POINTS",
        trigger_points=40,
        trail_distance_points=20,
    )
    assert stop == 100

    assert trailing_stop_price(
        100, 80, 100, 120, "LONG", True, "POINTS", 40, 20
    ) == 100


def test_trailing_rr_steps_moves_cost_at_2r_then_1r_at_3r():
    assert trailing_stop_price(
        100, 80, 80, 140, "LONG", True, "RR_STEPS",
        rr_steps=((2.0, 0.0), (3.0, 1.0))
    ) == 100
    assert trailing_stop_price(
        100, 80, 100, 160, "LONG", True, "RR_STEPS",
        rr_steps=((2.0, 0.0), (3.0, 1.0))
    ) == 120


def test_entry_slippage_and_marketable_limit():
    assert entry_allowed(102, 100, "LONG", 2)
    assert not entry_allowed(102.01, 100, "LONG", 2)
    assert entry_limit_price(102, "LONG", 1.5) == 103.5


def test_chart_drag_overrides_planned_levels():
    tool = TradeChartTool(
        symbol="NSE:TEST",
        side="LONG",
        quantity=65,
        entry_price=100,
        planned_sl=80,
        planned_tp=140,
    )
    assert tool.effective_sl == 80
    assert tool.effective_tp == 140
    tool.override_sl(92)
    tool.override_tp(118)
    assert tool.effective_sl == 92
    assert tool.effective_tp == 118
    assert any(line.overridden for line in tool.lines)

    no_filter_tool = TradeChartTool(
        symbol="NSE:TEST", side="LONG", quantity=65, entry_price=100
    )
    no_filter_tool.seed_manual_levels(20, 30)
    assert no_filter_tool.effective_sl == 80
    assert no_filter_tool.effective_tp == 130


def test_entry_window_and_force_exit():
    window = EntryWindow.from_hhmm("09:15", "15:10", "15:15")
    assert window.accepts_entry(datetime(2026, 9, 29, 9, 15))
    assert window.accepts_entry(datetime(2026, 9, 29, 15, 10))
    assert not window.accepts_entry(datetime(2026, 9, 29, 15, 11))
    assert window.requires_force_exit(datetime(2026, 9, 29, 15, 15))


def test_invalid_capital_allocation_rejected():
    with pytest.raises(ValueError):
        V2Config(capital_allocation_percent=101)
