from datetime import date

from backtest.broker_cost_model import (
    calculate_options_trade_costs,
    fyers_options_profile,
)


def test_pre_2026_stt_regime():
    assert fyers_options_profile(date(2025, 10, 15)).stt_sell_rate == 0.0010


def test_april_2026_stt_regime():
    assert fyers_options_profile(date(2026, 4, 1)).stt_sell_rate == 0.0015


def test_options_cost_breakdown():
    result = calculate_options_trade_costs(
        entry_price=173.25,
        exit_price=151.25,
        quantity=65,
        profile=fyers_options_profile(date(2025, 10, 15)),
        gross_pnl=-1430.0,
    )

    assert result.buy_turnover == 11261.25
    assert result.sell_turnover == 9831.25
    assert result.brokerage == 40.0
    assert result.stt == 9.83125
    assert result.total_cost > result.brokerage
    assert result.net_pnl < -1430.0


def test_historical_options_ipft_regime():
    profile = fyers_options_profile(date(2025, 10, 15))
    assert profile.ipft_rate == 50.0 / 10_000_000.0


def test_cost_components_are_explicit():
    result = calculate_options_trade_costs(
        entry_price=100.0,
        exit_price=90.0,
        quantity=65,
        profile=fyers_options_profile(date(2025, 10, 15)),
        gross_pnl=-650.0,
    )

    assert result.exchange_transaction == (100.0 * 65 + 90.0 * 65) * 0.000355299
    assert result.stt == 90.0 * 65 * 0.001
    assert result.sebi == (100.0 * 65 + 90.0 * 65) * (10.0 / 10_000_000.0)
    assert result.stamp_duty == 100.0 * 65 * 0.00003
    assert result.ipft == (100.0 * 65 + 90.0 * 65) * (50.0 / 10_000_000.0)
    assert result.gst == 0.18 * (
        result.brokerage + result.exchange_transaction + result.sebi + result.ipft
    )
    assert result.total_cost == (
        result.brokerage
        + result.exchange_transaction
        + result.stt
        + result.sebi
        + result.stamp_duty
        + result.ipft
        + result.gst
    )
