from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from backtest.opening_breakout_v2_signal_engine import SignalSeries, scan_series, scan_session


def _empty_provider(timestamp, candle):
    return IndicatorSnapshot()


def test_opening_candle_never_triggers_itself():
    series = SignalSeries(
        "NIFTY24000CE", "CE", 24000, 65,
        (
            Candle(1, 100, 110, 100, 108),
        ),
    )
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH",),
        trade_instrument="CALL",
    )
    alerts, signals = scan_series(series, config, _empty_provider)
    assert len(alerts) == 1
    assert signals == ()


def test_breakout_requires_later_completed_candle():
    series = SignalSeries(
        "NIFTY24000CE", "CE", 24000, 65,
        (
            Candle(1, 100, 110, 100, 108),
            Candle(2, 108, 109, 107, 108),
            Candle(3, 108, 111, 108, 110),
        ),
    )
    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH",),
        trade_instrument="CALL",
    )
    alerts, signals = scan_series(series, config, _empty_provider)
    assert len(alerts) == 1
    assert len(signals) == 1
    assert signals[0].trigger_timestamp == 3
    assert signals[0].breakout_price == 110


def test_multiple_selected_filters_are_and_conditions():
    series = SignalSeries(
        "NIFTY24000CE", "CE", 24000, 65,
        (
            Candle(1, 100, 110, 100, 108),
            Candle(2, 108, 111, 107, 109),
            Candle(3, 109, 112, 108, 111),
        ),
    )

    def provider(timestamp, candle):
        return IndicatorSnapshot(
            vwap=110.0,
            upper_bb=110.5,
        )

    config = V2Config(
        filter_open_low=True,
        selected_triggers=("CANDLE_HIGH", "ABOVE_VWAP", "CLOSE_ABOVE_UPPER_BB"),
        trade_instrument="CALL",
    )
    _, signals = scan_series(series, config, provider)
    assert len(signals) == 1
    assert signals[0].trigger_timestamp == 3


def test_dmi_put_requires_minus_di_and_adx():
    series = SignalSeries(
        "NIFTY24000PE", "PE", 24000, 65,
        (
            Candle(1, 100, 100, 90, 92),
            Candle(2, 92, 93, 89, 91),
            Candle(3, 91, 92, 88, 89),
        ),
    )

    def provider(timestamp, candle):
        return IndicatorSnapshot(minus_di=25.0, adx=25.0)

    config = V2Config(
        filter_open_high=True,
        selected_triggers=("CANDLE_LOW", "DMI"),
        trade_instrument="PUT",
    )
    _, signals = scan_series(series, config, provider)
    assert len(signals) == 1
    assert signals[0].direction == "SHORT"


def test_market_bias_blocks_opposite_candidate():
    series = SignalSeries(
        "NIFTY24000PE", "PE", 24000, 65,
        (
            Candle(1, 100, 100, 90, 92),
            Candle(2, 92, 93, 89, 91),
            Candle(3, 91, 92, 88, 89),
        ),
    )
    config = V2Config(
        market_bias="UP",
        filter_open_high=True,
        selected_triggers=("CANDLE_LOW",),
        trade_instrument="PUT",
    )
    _, signals = scan_series(series, config, _empty_provider)
    assert signals == ()


def test_session_returns_all_opening_alerts_and_timeframe_rule():
    ce = SignalSeries(
        "CE", "CE", 24000, 65,
        (Candle(1, 100, 110, 100, 108), Candle(2, 110, 111, 109, 110)),
    )
    pe = SignalSeries(
        "PE", "PE", 24000, 65,
        (Candle(1, 100, 100, 90, 92), Candle(2, 92, 93, 89, 91)),
    )
    config = V2Config(
        selected_timeframes=("5S", "1M", "3M"),
        filter_open_high=True,
        filter_open_low=True,
        selected_triggers=(),
        trade_instrument="CALL",
    )
    result = scan_session((ce, pe), config, _empty_provider)
    assert result.calculation_timeframe == "1M"
    assert {a.symbol for a in result.alerts} == {"CE", "PE"}
