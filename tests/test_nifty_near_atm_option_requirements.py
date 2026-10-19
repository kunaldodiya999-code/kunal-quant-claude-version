from scripts.plan_nifty_near_atm_option_requirements import (
    nearest_expiry,
    select_strikes,
)


def test_select_strikes_uses_actual_ladder_and_returns_atm_plus_minus_five():
    strikes = [24000 + 50 * i for i in range(21)]
    selected = select_strikes(strikes, 24510, radius=5)
    assert selected == [24250, 24300, 24350, 24400, 24450, 24500, 24550, 24600, 24650, 24700, 24750]


def test_select_strikes_does_not_assume_strike_spacing():
    strikes = [100, 125, 160, 200, 250, 310, 380, 460]
    selected = select_strikes(strikes, 215, radius=2)
    assert selected == [125, 160, 200, 250, 310]


def test_nearest_expiry_never_selects_an_expiry_before_trade_date():
    assert nearest_expiry(["2024-01-04", "2024-01-11"], "2024-01-05") == "2024-01-11"
    assert nearest_expiry(["2024-01-04"], "2024-01-05") is None


def test_nearest_expiry_rejects_unreasonably_distant_future_metadata():
    assert nearest_expiry(["2024-11-21"], "2024-01-01", max_days=90) is None
    assert nearest_expiry(["2024-01-01"], "2024-01-01", max_days=90) == "2024-01-01"
