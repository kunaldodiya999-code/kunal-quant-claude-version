from backtest.engine import (
    BacktestEntry,
    BacktestExit,
    calculate_trade_pnl,
    close_position,
    open_position,
    run_controlled_backtest,
)
from backtest.models import ExitReason
from strategies.direction_filter import Direction


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — BACKTEST ENGINE TEST")
    print("=" * 78)

    passed = 0

    # ---------------------------------------------------------
    # Test 1 — Long P&L
    # ---------------------------------------------------------

    pnl = calculate_trade_pnl(
        direction=Direction.LONG,
        entry_price=100.0,
        exit_price=110.0,
        quantity=10,
    )

    assert pnl == 100.0

    print("PASS | LONG P&L calculation")
    passed += 1

    # ---------------------------------------------------------
    # Test 2 — Short P&L
    # ---------------------------------------------------------

    pnl = calculate_trade_pnl(
        direction=Direction.SHORT,
        entry_price=100.0,
        exit_price=90.0,
        quantity=10,
    )

    assert pnl == 100.0

    print("PASS | SHORT P&L calculation")
    passed += 1

    # ---------------------------------------------------------
    # Test 3 — Long losing trade
    # ---------------------------------------------------------

    pnl = calculate_trade_pnl(
        direction=Direction.LONG,
        entry_price=100.0,
        exit_price=95.0,
        quantity=10,
    )

    assert pnl == -50.0

    print("PASS | LONG loss calculation")
    passed += 1

    # ---------------------------------------------------------
    # Test 4 — Open position
    # ---------------------------------------------------------

    entry = BacktestEntry(
        direction=Direction.LONG,
        timestamp=1000,
        price=150.0,
        quantity=65,
        lot_size=65,
        stop_loss=125.0,
        target=200.0,
    )

    position = open_position(entry)

    assert position.direction == Direction.LONG
    assert position.entry_price == 150.0
    assert position.quantity == 65
    assert position.stop_loss == 125.0
    assert position.target == 200.0

    print("PASS | Position creation")
    passed += 1

    # ---------------------------------------------------------
    # Test 5 — Close position
    # ---------------------------------------------------------

    exit_request = BacktestExit(
        timestamp=1010,
        price=175.0,
        reason=ExitReason.TARGET,
    )

    trade = close_position(
        position,
        exit_request,
    )

    assert trade.gross_pnl == 1625.0
    assert trade.exit_reason == ExitReason.TARGET

    print("PASS | Position close + P&L")
    passed += 1

    # ---------------------------------------------------------
    # Test 6 — Controlled backtest
    # ---------------------------------------------------------

    entry_1 = BacktestEntry(
        direction=Direction.LONG,
        timestamp=1000,
        price=100.0,
        quantity=10,
        lot_size=1,
    )

    exit_1 = BacktestExit(
        timestamp=1010,
        price=110.0,
        reason=ExitReason.TARGET,
    )

    entry_2 = BacktestEntry(
        direction=Direction.SHORT,
        timestamp=1020,
        price=200.0,
        quantity=5,
        lot_size=1,
    )

    exit_2 = BacktestExit(
        timestamp=1030,
        price=190.0,
        reason=ExitReason.STOP_LOSS,
    )

    result = run_controlled_backtest(
        starting_capital=100000.0,
        entries_and_exits=[
            (entry_1, exit_1),
            (entry_2, exit_2),
        ],
    )

    assert result.trade_count == 2
    assert result.total_pnl == 150.0
    assert result.final_equity == 100150.0

    print("PASS | Controlled backtest")
    passed += 1

    # ---------------------------------------------------------
    # Test 7 — Invalid zero quantity
    # ---------------------------------------------------------

    try:

        open_position(
            BacktestEntry(
                direction=Direction.LONG,
                timestamp=1000,
                price=100.0,
                quantity=0,
                lot_size=1,
            )
        )

        raise AssertionError(
            "Zero quantity should fail."
        )

    except ValueError:

        pass

    print("PASS | Zero quantity rejected")
    passed += 1

    # ---------------------------------------------------------
    # Test 8 — Invalid exit timestamp
    # ---------------------------------------------------------

    try:

        close_position(
            position,
            BacktestExit(
                timestamp=999,
                price=175.0,
                reason=ExitReason.MANUAL,
            ),
        )

        raise AssertionError(
            "Exit before entry should fail."
        )

    except ValueError:

        pass

    print("PASS | Exit before entry rejected")
    passed += 1

    print()
    print("Total :", 8)
    print("Passed:", passed)
    print("Failed:", 8 - passed)

    assert passed == 8

    print()
    print("ALL BACKTEST ENGINE TESTS PASSED")


if __name__ == "__main__":
    main()