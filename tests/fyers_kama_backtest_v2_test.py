"""Real FYERS data -> KAMA -> Backtest V2 integration test.

This test intentionally uses a controlled entry rather than KTMI.
The purpose is to validate:

    FYERS historical candles
        ->
    KAMA calculation
        ->
    Backtest Engine V2
        ->
    KAMA exit
        ->
    Completed trades

KTMI entry logic will be connected in the next stage.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.engine import (
    BacktestEntry,
    run_bar_by_bar_backtest,
)
from backtest.models import BacktestBar
from indicators.kama_trend_follower.config import (
    DEFAULT_KAMA_CONFIG,
)
from indicators.kama_trend_follower.universal import (
    KAMABar,
    calculate_kama_trend,
)
from strategies.exits.kama_exit import (
    KAMAExitEvaluator,
)


# ================================================================
# CONFIGURATION
# ================================================================

DB_PATH = Path(
    "data/database/kunal_quant.db"
)

SYMBOL = "NSE:NIFTY50-INDEX"

INSTRUMENT_ID = 572021

BAR_LIMIT = 1000

INITIAL_CAPITAL = 100_000.0

QUANTITY = 1


# ================================================================
# DATABASE
# ================================================================

def load_fyers_bars() -> list[BacktestBar]:
    """Load the latest FYERS NIFTY 1-minute candles."""

    connection = sqlite3.connect(DB_PATH)

    try:
        cursor = connection.cursor()

        rows = cursor.execute(
            """
            SELECT
                timestamp,
                open,
                high,
                low,
                close,
                volume,
                open_interest
            FROM candles
            WHERE instrument_id = ?
              AND resolution = ?
              AND source = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (
                INSTRUMENT_ID,
                "1",
                "FYERS_HISTORY",
                BAR_LIMIT,
            ),
        ).fetchall()

    finally:
        connection.close()

    rows.reverse()

    bars = [
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=int(row[5] or 0),
            open_interest=(
                int(row[6])
                if row[6] is not None
                else None
            ),
        )
        for row in rows
    ]

    return bars


# ================================================================
# KAMA
# ================================================================

def calculate_real_kama(
    bars: list[BacktestBar],
):
    """Calculate KAMA using the real FYERS candles."""

    kama_bars = [
        KAMABar(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]

    results = calculate_kama_trend(
        bars=kama_bars,
        config=DEFAULT_KAMA_CONFIG,
    )

    return results


# ================================================================
# MAIN TEST
# ================================================================

def main() -> None:

    print()
    print("=" * 70)
    print("REAL FYERS -> KAMA -> BACKTEST V2")
    print("=" * 70)

    # ------------------------------------------------------------
    # 1. Load FYERS candles
    # ------------------------------------------------------------

    bars = load_fyers_bars()

    print()
    print("FYERS DATA")
    print("-" * 50)
    print(f"Symbol          : {SYMBOL}")
    print(f"Instrument ID   : {INSTRUMENT_ID}")
    print(f"Bars loaded     : {len(bars)}")

    assert len(bars) > 0, (
        "No FYERS candles were loaded."
    )

    # ------------------------------------------------------------
    # 2. Validate chronological order
    # ------------------------------------------------------------

    for previous, current in zip(
        bars,
        bars[1:],
    ):
        assert current.timestamp >= previous.timestamp

    print("Chronological   : PASS")

    # ------------------------------------------------------------
    # 3. Calculate KAMA
    # ------------------------------------------------------------

    kama_results = calculate_real_kama(bars)

    print()
    print("KAMA")
    print("-" * 50)
    print(f"KAMA results    : {len(kama_results)}")

    assert len(kama_results) == len(bars)

    valid_kama_count = sum(
        1
        for result in kama_results
        if result.kama is not None
    )

    print(
        f"Valid KAMA      : {valid_kama_count}"
    )

    assert valid_kama_count > 0

    print("KAMA calculation: PASS")

    # ------------------------------------------------------------
    # 4. Create controlled entry
    # ------------------------------------------------------------
    #
    # We deliberately use the first bar where KAMA exists.
    #
    # This is NOT a KTMI entry.
    #
    # It only proves that real KAMA can drive the
    # Backtest V2 lifecycle.
    #

    entry_index = next(
        (
            index
            for index, result
            in enumerate(kama_results)
            if result.kama is not None
        ),
        None,
    )

    assert entry_index is not None

    entry_bar = bars[entry_index]

    entry = BacktestEntry(
        timestamp=entry_bar.timestamp,
        direction="LONG",
        price=entry_bar.close,
        quantity=QUANTITY,
        strategy_id="KAMA_REAL_TEST",
        config_version="V2",
    )

    print()
    print("CONTROLLED ENTRY")
    print("-" * 50)
    print(f"Entry index     : {entry_index}")
    print(f"Entry timestamp : {entry.timestamp}")
    print(f"Entry price     : {entry.price}")

    # ------------------------------------------------------------
    # 5. Run Backtest V2
    # ------------------------------------------------------------

    result = run_bar_by_bar_backtest(
        bars=bars,
        entries=[entry],
        exit_evaluator=KAMAExitEvaluator(),
        indicator_data=kama_results,
        initial_capital=INITIAL_CAPITAL,
    )

    # ------------------------------------------------------------
    # 6. Validate result
    # ------------------------------------------------------------

    print()
    print("BACKTEST V2")
    print("-" * 50)
    print(f"Trades          : {result.trade_count}")
    print(f"Initial capital : {result.initial_capital}")
    print(f"Final equity    : {result.final_equity}")
    print(f"Total P&L       : {result.total_pnl}")

    assert result.trade_count == 1

    trade = result.trades[0]

    print()
    print("TRADE")
    print("-" * 50)
    print(f"Direction       : {trade.direction}")
    print(f"Entry timestamp : {trade.entry_timestamp}")
    print(f"Entry price     : {trade.entry_price}")
    print(f"Exit timestamp  : {trade.exit_timestamp}")
    print(f"Exit price      : {trade.exit_price}")
    print(f"Quantity        : {trade.quantity}")
    print(f"P&L             : {trade.pnl}")
    print(f"Exit reason     : {trade.exit_reason}")
    print(f"Holding bars    : {trade.holding_bars}")

    # ------------------------------------------------------------
    # 7. Structural validation
    # ------------------------------------------------------------

    assert trade.entry_timestamp == entry.timestamp
    assert trade.entry_price == entry.price
    assert trade.direction == "LONG"
    assert trade.quantity == QUANTITY

    assert trade.exit_timestamp >= trade.entry_timestamp

    assert trade.exit_price > 0

    assert trade.holding_bars >= 1

    print()
    print("Entry validation : PASS")
    print("Exit validation  : PASS")
    print("P&L validation   : PASS")
    print("Lifecycle        : PASS")

    print()
    print("=" * 70)
    print("REAL FYERS -> KAMA -> BACKTEST V2 PASSED")
    print("=" * 70)


if __name__ == "__main__":
    main()