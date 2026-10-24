"""Tests for Kunal Quant economic cost framework V1."""

from __future__ import annotations

from backtest.economic_costs import (
    EconomicCostConfig,
    EconomicCostModel,
)


def main() -> None:
    model = EconomicCostModel(
        EconomicCostConfig(
            slippage_pct=0.0025,
            fixed_entry_charge=25.0,
            fixed_exit_charge=25.0,
        )
    )

    buy = model.calculate_order_cost(
        side="BUY",
        reference_price=100.0,
        quantity=65,
    )
    assert buy.execution_price == 100.25
    assert buy.slippage_cost == 16.25
    assert buy.fixed_charge == 25.0
    assert buy.total_cost == 41.25

    sell = model.calculate_order_cost(
        side="SELL",
        reference_price=100.0,
        quantity=65,
    )
    assert sell.execution_price == 99.75
    assert sell.slippage_cost == 16.25
    assert sell.fixed_charge == 25.0
    assert sell.total_cost == 41.25

    long_result = model.calculate_trade_net_pnl(
        direction="LONG",
        entry_price=100.0,
        entry_quantity=130,
        exits=[
            {"price": 110.0, "quantity": 65},
            {"price": 105.0, "quantity": 65},
        ],
        gross_pnl=975.0,
    )

    assert round(long_result.total_slippage, 10) == 67.4375
    assert long_result.total_fixed_charges == 75.0
    assert round(long_result.total_cost, 10) == 142.4375
    assert round(long_result.net_pnl, 10) == 832.5625

    short_result = model.calculate_trade_net_pnl(
        direction="SHORT",
        entry_price=100.0,
        entry_quantity=65,
        exits=[
            {"price": 90.0, "quantity": 65},
        ],
        gross_pnl=650.0,
    )

    assert round(short_result.total_slippage, 10) == 30.875
    assert short_result.total_fixed_charges == 50.0
    assert round(short_result.total_cost, 10) == 80.875
    assert round(short_result.net_pnl, 10) == 569.125

    checks = [
        ("BUY execution price", buy.execution_price == 100.25),
        ("SELL execution price", sell.execution_price == 99.75),
        ("slippage calculation", buy.slippage_cost == 16.25),
        ("fixed charge calculation", buy.fixed_charge == 25.0),
        ("LONG net P&L", round(long_result.net_pnl, 10) == 832.5625),
        ("SHORT net P&L", round(short_result.net_pnl, 10) == 569.125),
    ]

    for name, passed in checks:
        assert passed
        print(f"PASS | {name}")

    print()
    print("ALL ECONOMIC COST V1 TESTS PASSED")


if __name__ == "__main__":
    main()
