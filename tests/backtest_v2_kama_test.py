"""Controlled Backtest Engine V2 + KAMA test."""

from backtest.engine import (
    BacktestEntry,
    run_bar_by_bar_backtest,
)
from backtest.models import (
    BacktestBar,
    ExitReason,
)
from strategies.exits.kama_exit import (
    KAMAExitEvaluator,
)


class FakeKAMA:
    """Test-only indicator result exposing a KAMA value."""

    def __init__(self, kama: float):
        self.kama = kama


def main() -> None:

    # =============================================================
    # HISTORICAL BARS
    # =============================================================

    bars = [
        BacktestBar(
            timestamp=1,
            open=100,
            high=101,
            low=99,
            close=100,
        ),
        BacktestBar(
            timestamp=2,
            open=100,
            high=103,
            low=99,
            close=102,
        ),
        BacktestBar(
            timestamp=3,
            open=102,
            high=103,
            low=97,
            close=98,
        ),
        BacktestBar(
            timestamp=4,
            open=98,
            high=100,
            low=96,
            close=97,
        ),
    ]

    # =============================================================
    # ENTRY
    # =============================================================

    entries = [
        BacktestEntry(
            timestamp=1,
            direction="LONG",
            price=100,
            quantity=10,
            strategy_id="KAMA_TEST",
            config_version="V2",
        )
    ]

    # =============================================================
    # KAMA VALUES
    # =============================================================

    # Candle 1:
    #
    # Close = 100
    # KAMA  = 99
    #
    # This is the ENTRY candle.
    # Exit MUST NOT be evaluated here.
    #
    #
    # Candle 2:
    #
    # Close = 102
    # KAMA  = 101
    #
    # 102 > 101
    # Therefore HOLD.
    #
    #
    # Candle 3:
    #
    # Close = 98
    # KAMA  = 100
    #
    # 98 < 100
    # Therefore LONG EXIT.
    #
    #
    # Candle 4:
    #
    # Position should already be closed.
    #

    indicator_data = [
        FakeKAMA(99),
        FakeKAMA(101),
        FakeKAMA(100),
        FakeKAMA(100),
    ]

    # =============================================================
    # RUN
    # =============================================================

    result = run_bar_by_bar_backtest(
        bars=bars,
        entries=entries,
        exit_evaluator=KAMAExitEvaluator(),
        indicator_data=indicator_data,
        initial_capital=100_000,
    )

    # =============================================================
    # VALIDATION
    # =============================================================

    assert result.trade_count == 1

    trade = result.trades[0]

    # Entry
    assert trade.direction == "LONG"
    assert trade.entry_timestamp == 1
    assert trade.entry_price == 100

    # Exit
    assert trade.exit_timestamp == 3
    assert trade.exit_price == 98

    # Quantity
    assert trade.quantity == 10

    # P&L:
    #
    # (98 - 100) × 10
    # = -20
    #
    assert trade.pnl == -20

    # KAMA exit reason
    assert (
        trade.exit_reason
        == ExitReason.KAMA_LONG_CLOSE_BELOW
    )

    # Candle 2 and candle 3 were processed
    # after the entry candle.
    assert trade.holding_bars == 2

    # Final equity
    assert result.final_equity == 99_980

    # =============================================================
    # OUTPUT
    # =============================================================

    print()
    print("=" * 60)
    print("BACKTEST V2 KAMA TEST")
    print("=" * 60)

    print("PASS trade count")
    print("PASS entry timestamp")
    print("PASS entry price")
    print("PASS next-bar-only exit evaluation")
    print("PASS KAMA exit")
    print("PASS exit timestamp")
    print("PASS exit price")
    print("PASS quantity")
    print("PASS P&L")
    print("PASS exit reason")
    print("PASS holding bars")
    print("PASS final equity")

    print()
    print(
        "Entry:",
        trade.entry_timestamp,
        trade.entry_price,
    )

    print(
        "Exit:",
        trade.exit_timestamp,
        trade.exit_price,
    )

    print(
        "P&L:",
        trade.pnl,
    )

    print(
        "Reason:",
        trade.exit_reason,
    )

    print(
        "Holding bars:",
        trade.holding_bars,
    )

    print()
    print("ALL BACKTEST V2 KAMA TESTS PASSED")


if __name__ == "__main__":
    main()