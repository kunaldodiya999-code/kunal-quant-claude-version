"""Tests for the reusable trade-audit layer."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.trade_audit import (
    build_trade_audit,
    calculate_audit_totals,
    find_unbalanced_trades,
)


@dataclass
class Exit:
    timestamp: int
    quantity: int
    pnl: float
    price: float
    reason: str
    remaining_quantity: int


@dataclass
class Position:
    strategy_id: str
    symbol: str
    direction: str
    entry_price: float
    quantity: int
    remaining_quantity: int
    gross_pnl: float


@dataclass
class Contract:
    symbol: str


@dataclass
class Trade:
    position: Position
    contract: Contract


def make_trade() -> dict:
    position = Position(
        strategy_id="KTMI_LONG_SHORT_SPEED",
        symbol="NSE:NIFTY24N2123350CE",
        direction="LONG",
        entry_price=21.0,
        quantity=325,
        remaining_quantity=0,
        gross_pnl=780.0,
    )

    trade = Trade(
        position=position,
        contract=Contract(
            symbol=position.symbol,
        ),
    )

    return {
        "trade": trade,
        "exits": [
            Exit(
                timestamp=100,
                quantity=130,
                pnl=520.0,
                price=25.0,
                reason="TARGET_3R",
                remaining_quantity=195,
            ),
            Exit(
                timestamp=110,
                quantity=195,
                pnl=260.0,
                price=22.3333333333,
                reason="KAMA_EXIT",
                remaining_quantity=0,
            ),
        ],
    }


def main() -> None:
    summaries = build_trade_audit([make_trade()])

    assert len(summaries) == 1
    row = summaries[0]

    assert row.entry_quantity == 325
    assert row.exit_quantity == 325
    assert row.exit_count == 2
    assert row.partial_exit_count == 1
    assert row.total_pnl == 780.0
    assert row.position_gross_pnl == 780.0
    assert row.quantity_balanced is True
    assert row.pnl_balanced is True
    assert row.final_exit_reason == "KAMA_EXIT"
    assert len(row.exits) == 2
    assert row.exits[0].exit_number == 1
    assert row.exits[0].quantity == 130
    assert row.exits[0].price == 25.0
    assert row.exits[0].reason == "TARGET_3R"
    assert row.exits[1].exit_number == 2
    assert row.exits[1].quantity == 195
    assert row.exits[1].reason == "KAMA_EXIT"

    totals = calculate_audit_totals(summaries)

    assert totals.trades == 1
    assert totals.balanced_quantity == 1
    assert totals.balanced_pnl == 1
    assert totals.total_exit_events == 2
    assert totals.partial_exit_events == 1
    assert totals.gross_pnl == 780.0

    assert find_unbalanced_trades(summaries) == []

    print("PASS | trade grouping")
    print("PASS | quantity balance")
    print("PASS | P&L balance")
    print("PASS | partial exit detection")
    print("PASS | exit reason detection")
    print("PASS | audit totals")
    print("PASS | unbalanced trade detection")
    print()
    print("ALL TRADE AUDIT V1 TESTS PASSED")


if __name__ == "__main__":
    main()
