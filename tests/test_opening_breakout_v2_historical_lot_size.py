from datetime import date

from backtest.opening_breakout_v2_historical_lot_size import (
    NIFTY_NEW_LOT_SIZE,
    NIFTY_OLD_LOT_SIZE,
    historical_nifty_lot_size,
)


def test_pre_revision_v2_contract_uses_75_lot():
    assert historical_nifty_lot_size(
        signal_date=date(2025, 10, 15),
        expiry_date=date(2025, 10, 23),
    ) == NIFTY_OLD_LOT_SIZE


def test_revision_day_existing_contract_keeps_75_lot():
    assert historical_nifty_lot_size(
        signal_date=date(2025, 10, 28),
        expiry_date=date(2025, 11, 25),
    ) == NIFTY_OLD_LOT_SIZE


def test_post_revision_contract_uses_65_lot():
    assert historical_nifty_lot_size(
        signal_date=date(2025, 10, 29),
        expiry_date=date(2025, 11, 4),
    ) == NIFTY_NEW_LOT_SIZE


def test_revision_day_contract_after_transition_cutoff_uses_new_lot():
    assert historical_nifty_lot_size(
        signal_date=date(2025, 10, 28),
        expiry_date=date(2026, 1, 6),
    ) == NIFTY_NEW_LOT_SIZE
