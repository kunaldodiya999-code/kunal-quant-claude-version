"""Tests for performance analytics V1."""

from __future__ import annotations

from dataclasses import dataclass

from backtest.performance_analytics import calculate_performance


@dataclass
class EconomicRow:
    net_pnl: float
    gross_pnl: float
    total_cost: float


@dataclass
class AuditRow:
    entry_quantity: int
    exit_count: int
    final_exit_reason: str
    partial_exit_count: int


def main() -> None:
    economic = [
        EconomicRow(100.0, 120.0, 20.0),
        EconomicRow(-50.0, -40.0, 10.0),
        EconomicRow(25.0, 30.0, 5.0),
        EconomicRow(-25.0, -20.0, 5.0),
    ]

    audits = [
        AuditRow(65, 1, "KAMA_EXIT", 0),
        AuditRow(130, 1, "STOP_LOSS", 0),
        AuditRow(65, 2, "KAMA_EXIT", 1),
        AuditRow(65, 1, "END_OF_DATA", 0),
    ]

    metrics = calculate_performance(
        economic_rows=economic,
        audit_rows=audits,
    )

    assert metrics.trades == 4
    assert metrics.wins == 2
    assert metrics.losses == 2
    assert metrics.breakeven == 0
    assert metrics.win_rate_pct == 50.0
    assert metrics.gross_pnl == 90.0
    assert metrics.average_trade_pnl == 12.5
    assert metrics.average_win == 62.5
    assert metrics.average_loss == -37.5
    assert metrics.profit_factor == 125.0 / 75.0
    assert metrics.largest_win == 100.0
    assert metrics.largest_loss == -50.0
    assert metrics.total_cost == 40.0
    assert metrics.net_pnl == 50.0
    assert metrics.total_exit_events == 5
    assert metrics.total_quantity == 325
    assert metrics.stop_exits == 1
    assert metrics.target_partial_exits == 1
    assert metrics.kama_exits == 2
    assert metrics.end_of_data_exits == 1

    print("PASS | trade counts")
    print("PASS | win rate")
    print("PASS | gross P&L")
    print("PASS | average win/loss")
    print("PASS | profit factor")
    print("PASS | extremes")
    print("PASS | cost and net P&L")
    print("PASS | exit attribution")
    print()
    print("ALL PERFORMANCE ANALYTICS V1 TESTS PASSED")


if __name__ == "__main__":
    main()
