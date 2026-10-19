from dataclasses import dataclass

from backtest.performance_attribution import (
    calculate_max_drawdown,
    group_attribution,
)


@dataclass
class E:
    strategy_id: str
    direction: str
    net_pnl: float
    gross_pnl: float
    total_cost: float


@dataclass
class A:
    final_exit_reason: str


def main() -> None:
    economic = [
        E("A", "LONG", 100, 110, 10),
        E("A", "SHORT", -50, -40, 10),
        E("B", "LONG", 25, 30, 5),
    ]
    audits = [
        A("KAMA_EXIT"),
        A("STOP_LOSS"),
        A("STOP_LOSS"),
    ]

    groups = group_attribution(
        economic_rows=economic,
        audit_rows=audits,
    )

    strategy = {r.key: r for r in groups["strategy"]}
    direction = {r.key: r for r in groups["direction"]}
    reasons = {r.key: r for r in groups["final_exit_reason"]}

    assert strategy["A"].trades == 2
    assert strategy["A"].net_pnl == 50
    assert strategy["B"].win_rate_pct == 100
    assert direction["LONG"].trades == 2
    assert direction["SHORT"].losses == 1
    assert reasons["STOP_LOSS"].trades == 2

    dd = calculate_max_drawdown(
        starting_capital=1000,
        economic_rows=economic,
    )
    assert dd.max_drawdown == 50
    assert dd.max_drawdown_pct == (50 / 1100) * 100
    assert dd.peak_equity == 1100
    assert dd.trough_equity == 1050

    print("PASS | strategy attribution")
    print("PASS | direction attribution")
    print("PASS | exit attribution")
    print("PASS | max drawdown")
    print()
    print("ALL PERFORMANCE ATTRIBUTION V1 TESTS PASSED")


if __name__ == "__main__":
    main()
