"""Trade Management V1 unit test.

Validates:
    - ₹15,000 allocation
    - NIFTY lot size 65
    - 2 lots / 130 quantity at ₹100
    - 20% stop loss
    - 3R target
    - 50% whole-lot partial exit
    - KAMA exit for remaining position
"""

from backtest.models import BacktestBar
from backtest.trade_management import (
    TradeManagementConfig,
    calculate_position_size,
    run_trade_management,
)


def bar(ts, close, high=None, low=None):
    return BacktestBar(
        timestamp=ts,
        open=close,
        high=high if high is not None else close,
        low=low if low is not None else close,
        close=close,
    )


def main():
    config = TradeManagementConfig(
        initial_capital=100_000,
        allocation_per_trade=15_000,
        lot_size=65,
        stop_loss_enabled=True,
        stop_loss_percent=20,
        target_enabled=True,
        target_rr=3,
        partial_exit_enabled=True,
        partial_exit_percent=50,
        kama_exit_enabled=True,
    )

    # ----------------------------------------------------------
    # Position sizing
    # ----------------------------------------------------------
    sizing = calculate_position_size(
        entry_price=100,
        direction="LONG",
        config=config,
    )

    assert sizing.lots == 2
    assert sizing.quantity == 130
    assert sizing.capital_used == 13_000
    assert sizing.unused_allocation == 2_000
    assert sizing.stop_loss == 80
    assert sizing.target == 160
    assert sizing.planned_risk == 2_600

    print("PASS | 2 lots = 130 quantity")
    print("PASS | ₹13,000 capital used from ₹15,000 allocation")
    print("PASS | 20% LONG stop = ₹80")
    print("PASS | 3R LONG target = ₹160")
    print("PASS | Planned risk = ₹2,600")

    # ----------------------------------------------------------
    # 3R partial then KAMA exit
    # ----------------------------------------------------------
    bars = [
        bar(1, 100),
        bar(2, 110, high=165, low=108),
        bar(3, 150, high=152, low=148),
        bar(4, 140, high=142, low=138),
    ]

    kama = [
        None,
        90,
        145,
        145,
    ]

    trade = run_trade_management(
        bars=bars,
        direction="LONG",
        entry_price=100,
        kama_values=kama,
        config=config,
    )

    assert trade.entry_lots == 2
    assert trade.entry_quantity == 130

    assert trade.partial_exit_lots == 1
    assert trade.partial_exit_quantity == 65

    print()
    print("DEBUG TRADE LEGS")
    print("-" * 50)

    for i, leg in enumerate(trade.legs, start=1):
        print(
            f"LEG {i} | "
            f"Reason={leg.exit_reason} | "
            f"Price={leg.exit_price} | "
            f"Lots={leg.lots} | "
            f"Qty={leg.quantity} | "
            f"P&L={leg.pnl}"
        )

    print(f"DEBUG | Number of legs = {len(trade.legs)}")

    assert len(trade.legs) == 2

    assert trade.legs[0].exit_reason == "TARGET_3R_PARTIAL"
    assert trade.legs[0].lots == 1
    assert trade.legs[0].quantity == 65
    assert trade.legs[0].exit_price == 160

    assert trade.legs[1].exit_reason == "KAMA_LONG_CLOSE_BELOW"
    assert trade.legs[1].lots == 1
    assert trade.legs[1].quantity == 65
    assert trade.legs[1].exit_price == 140

    # First leg: +60 * 65 = 3900
    # Second leg: +40 * 65 = 2600
    assert trade.gross_pnl == 6500

    print("PASS | 50% of 2 lots = 1 whole lot")
    print("PASS | Partial target exits 1 lot / 65 qty")
    print("PASS | Remaining 1 lot trails to KAMA")
    print("PASS | LONG KAMA exit works")
    print("PASS | Gross P&L = ₹6,500")

    print()
    print("=" * 65)
    print("ALL TRADE MANAGEMENT V1 TESTS PASSED")
    print("=" * 65)


if __name__ == "__main__":
    main()
