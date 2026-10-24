"""Hand-calculated PSAR state-machine regression fixtures.

These tests pin the current isolated implementation's deterministic recurrence.
They do not claim exact TradingView ta.sar parity.
"""
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab


def _candle(ts, high, low, close):
    return OptionCandle(timestamp=ts, open=close, high=high, low=low, close=close)


def test_psar_initialization_and_bullish_acceleration_factor():
    state = {}
    bars = [
        _candle(60, high=10.0, low=8.0, close=9.0),
        _candle(120, high=12.0, low=9.0, close=11.0),
    ]

    sar = TslShadowLab._psar(bars, start=0.02, inc=0.02, maximum=0.20, state=state)

    # Initial bullish SAR is the two-bar lowest low; EP is the highest high.
    assert sar == 8.0
    assert state["psar_bull"] is True
    assert state["psar_ep"] == 12.0
    assert state["psar_af"] == 0.02


def test_psar_projects_clamps_and_increments_af_on_new_extreme():
    state = {}
    bars = [
        _candle(60, high=10.0, low=8.0, close=9.0),
        _candle(120, high=12.0, low=9.0, close=11.0),
    ]
    TslShadowLab._psar(bars, 0.02, 0.02, 0.20, state)

    bars.append(_candle(180, high=13.0, low=10.0, close=12.0))
    sar = TslShadowLab._psar(bars, 0.02, 0.02, 0.20, state)

    # Projection 8 + .02 * (12 - 8) = 8.08, clamped to prior two-bar low 8.
    assert sar == 8.0
    assert state["psar_ep"] == 13.0
    assert state["psar_af"] == 0.04


def test_psar_bullish_to_bearish_reversal_resets_af_and_uses_prior_ep():
    state = {}
    bars = [
        _candle(60, high=10.0, low=8.0, close=9.0),
        _candle(120, high=12.0, low=9.0, close=11.0),
        _candle(180, high=13.0, low=10.0, close=12.0),
        _candle(240, high=14.0, low=11.0, close=13.0),
    ]
    for end in range(2, len(bars) + 1):
        TslShadowLab._psar(bars[:end], 0.02, 0.02, 0.20, state)

    bars.append(_candle(300, high=12.0, low=7.0, close=8.0))
    sar = TslShadowLab._psar(bars, 0.02, 0.02, 0.20, state)

    # Prior EP was 14; a reversal sets SAR to that EP and starts a new AF.
    assert sar == 14.0
    assert state["psar_bull"] is False
    assert state["psar_ep"] == 7.0
    assert state["psar_af"] == 0.02


def test_psar_bearish_trend_updates_extreme_and_caps_acceleration():
    state = {}
    bars = [
        _candle(60, high=10.0, low=8.0, close=9.0),
        _candle(120, high=12.0, low=9.0, close=11.0),
        _candle(180, high=13.0, low=10.0, close=12.0),
        _candle(240, high=14.0, low=11.0, close=13.0),
        _candle(300, high=12.0, low=7.0, close=8.0),
    ]
    for end in range(2, len(bars) + 1):
        TslShadowLab._psar(bars[:end], 0.02, 0.02, 0.20, state)

    bars.append(_candle(360, high=13.0, low=6.0, close=7.0))
    sar = TslShadowLab._psar(bars, 0.02, 0.02, 0.20, state)

    # Bearish projection is clamped to the prior two highs (14), with no reversal.
    assert sar == 14.0
    assert state["psar_bull"] is False
    assert state["psar_ep"] == 6.0
    assert state["psar_af"] == 0.04
