"""Tests for trade-level economic accounting V1."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.economic_accounting import (
    EconomicTradeSummary,
    calculate_economic_totals,
    calculate_economic_trade,
)
from backtest.economic_costs import EconomicCostConfig, EconomicCostModel
from backtest.trade_audit import TradeAuditExit, TradeAuditSummary


def make_summary(
    *,
    key: int,
    direction: str,
    gross_pnl: float,
) -> TradeAuditSummary:
    return TradeAuditSummary(
        trade_key=key,
        strategy_id="TEST",
        symbol="NSE:TEST",
        direction=direction,
        entry_price=100.0,
        entry_quantity=130,
        exit_quantity=130,
        exit_count=2,
        partial_exit_count=1,
        total_pnl=gross_pnl,
        position_gross_pnl=gross_pnl,
        quantity_balanced=True,
        pnl_balanced=True,
        final_exit_reason="KAMA_EXIT",
        first_exit_timestamp=100,
        final_exit_timestamp=110,
        exits=(
            TradeAuditExit(
                exit_number=1,
                timestamp=100,
                quantity=65,
                price=110.0,
                pnl=650.0,
                reason="TARGET_3R",
                remaining_quantity=65,
                remaining_lots=1,
            ),
            TradeAuditExit(
                exit_number=2,
                timestamp=110,
                quantity=65,
                price=105.0,
                pnl=325.0,
                reason="KAMA_EXIT",
                remaining_quantity=0,
                remaining_lots=0,
            ),
        ),
    )


def main() -> None:
    model = EconomicCostModel(
        EconomicCostConfig(
            slippage_pct=0.0025,
            fixed_entry_charge=25.0,
            fixed_exit_charge=25.0,
        )
    )

    summary = make_summary(
        key=1,
        direction="LONG",
        gross_pnl=975.0,
    )

    result = calculate_economic_trade(
        summary,
        model=model,
    )

    assert result.gross_pnl == 975.0
    assert round(result.slippage_cost, 10) == 67.4375
    assert result.fixed_charges == 75.0
    assert round(result.total_cost, 10) == 142.4375
    assert round(result.net_pnl, 10) == 832.5625

    rows = [
        result,
        calculate_economic_trade(
            make_summary(
                key=2,
                direction="SHORT",
                gross_pnl=975.0,
            ),
            model=model,
        ),
    ]

    totals = calculate_economic_totals(rows)

    assert totals.trades == 2
    assert totals.gross_pnl == 1950.0
    assert round(totals.slippage_cost, 10) == 134.875
    assert totals.fixed_charges == 150.0
    assert round(totals.total_cost, 10) == 284.875
    assert round(totals.net_pnl, 10) == 1665.125

    checks = [
        ("economic trade conversion", isinstance(result, EconomicTradeSummary)),
        ("gross P&L preserved", result.gross_pnl == 975.0),
        ("slippage applied", round(result.slippage_cost, 10) == 67.4375),
        ("fixed charges applied", result.fixed_charges == 75.0),
        ("net P&L calculated", round(result.net_pnl, 10) == 832.5625),
        ("economic totals", totals.trades == 2),
    ]

    for name, passed in checks:
        assert passed
        print(f"PASS | {name}")

    print()
    print("ALL ECONOMIC ACCOUNTING V1 TESTS PASSED")


if __name__ == "__main__":
    main()
