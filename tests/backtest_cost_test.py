"""Trading cost and slippage engine test."""

from backtest.costs import (
    CostConfig,
    calculate_entry_execution,
    calculate_exit_execution,
    calculate_trade_costs,
)


def main() -> None:

    config = CostConfig(
        enabled=True,
        entry_slippage_percent=0.25,
        exit_slippage_percent=0.25,
        entry_fixed_charge=25.0,
        exit_fixed_charge=25.0,
    )

    # ============================================================
    # LONG ENTRY
    # ============================================================

    entry = calculate_entry_execution(
        direction="LONG",
        reference_price=100.0,
        config=config,
    )

    assert entry.execution_price == 100.25

    print("PASS LONG entry slippage")

    # ============================================================
    # LONG EXIT
    # ============================================================

    exit_result = calculate_exit_execution(
        direction="LONG",
        reference_price=100.0,
        config=config,
    )

    assert exit_result.execution_price == 99.75

    print("PASS LONG exit slippage")

    # ============================================================
    # SHORT ENTRY
    # ============================================================

    short_entry = calculate_entry_execution(
        direction="SHORT",
        reference_price=100.0,
        config=config,
    )

    assert short_entry.execution_price == 99.75

    print("PASS SHORT entry slippage")

    # ============================================================
    # SHORT EXIT
    # ============================================================

    short_exit = calculate_exit_execution(
        direction="SHORT",
        reference_price=100.0,
        config=config,
    )

    assert short_exit.execution_price == 100.25

    print("PASS SHORT exit slippage")

    # ============================================================
    # TOTAL COST
    # ============================================================

    costs = calculate_trade_costs(
        entry_price=100.0,
        exit_price=110.0,
        quantity=10,
        direction="LONG",
        config=config,
    )

    # Entry slippage:
    # 100 × 0.25% × 10 = 2.50
    #
    # Exit slippage:
    # 110 × 0.25% × 10 = 2.75
    #
    # Fixed:
    # 25 + 25 = 50
    #
    # Total:
    # 55.25

    assert abs(
        costs.total_cost - 55.25
    ) < 0.000001

    print("PASS total transaction cost")

    print()
    print("ALL BACKTEST COST TESTS PASSED")


if __name__ == "__main__":
    main()