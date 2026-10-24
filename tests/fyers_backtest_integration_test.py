"""
Kunal Quant — FYERS Backtest Integration V1.

Purpose:
    Validate the complete historical pipeline:

        FYERS database
            ↓
        Historical OHLC bars
            ↓
        KTMI Universal
            ↓
        KTMI Signals
            ↓
        Strategy Engine
            ↓
        Direction Filter
            ↓
        Risk Engine
            ↓
        Backtest Engine
            ↓
        Historical trades / P&L

This is an infrastructure/integration test.

IMPORTANT:
    Final SL / Target / Trailing SL logic is intentionally NOT implemented here.
    Entries are generated from the real strategy pipeline.
    A controlled one-bar exit is used only to validate the complete pipeline.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.engine import (
    BacktestEntry,
    BacktestExit,
    run_controlled_backtest,
)
from backtest.models import BacktestBar, ExitReason
from indicators.ktmi.config import DEFAULT_KTMI_CONFIG
from indicators.ktmi.signals import calculate_signals
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from risk.risk_engine import (
    RiskMethod,
    RiskRequest,
    calculate_position_size,
)
from strategies.direction_filter import Direction
from strategies.ktmi_strategy import (
    KTMIEntryConfig,
    evaluate_ktmi_entry,
)


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "database"
    / "kunal_quant.db"
)

SYMBOL = "NSE:NIFTY50-INDEX"

TIMEFRAME = "1"

BAR_LIMIT = 1000

STARTING_CAPITAL = 100_000.0

FIXED_RISK_PER_TRADE = 2_500.0

LOT_SIZE = 65

STRATEGY_ID = "KTMI_V1"

CONFIG_VERSION = "1.0"


# ---------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------


def load_fyers_bars() -> list[BacktestBar]:
    """
    Load historical FYERS candles for the NIFTY index.

    The candles table contains the broker-sourced historical data.
    """

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found:\n{DATABASE_PATH}"
        )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                c.timestamp,
                c.open,
                c.high,
                c.low,
                c.close,
                c.volume
            FROM candles c
            JOIN instruments i
                ON c.instrument_id = i.id
            WHERE i.symbol = ?
              AND c.resolution = ?
              AND c.source = 'FYERS_HISTORY'
            ORDER BY c.timestamp ASC
            LIMIT ?
            """,
            (
                SYMBOL,
                TIMEFRAME,
                BAR_LIMIT,
            ),
        )

        rows = cursor.fetchall()

    finally:

        connection.close()

    bars: list[BacktestBar] = []

    for row in rows:

        timestamp = int(row[0])

        open_price = float(row[1])
        high_price = float(row[2])
        low_price = float(row[3])
        close_price = float(row[4])

        volume = (
            int(row[5])
            if row[5] is not None
            else 0
        )

        bars.append(
            BacktestBar(
                timestamp=timestamp,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=volume,
            )
        )

    return bars


# ---------------------------------------------------------------------
# KTMI calculation
# ---------------------------------------------------------------------


def calculate_ktmi_series(
    bars: list[BacktestBar],
):
    """
    Calculate KTMI across the complete historical series.

    The KTMI Universal engine expects a Sequence of individual
    OHLCData bars, one object per historical candle.
    """

    ohlc_bars = [
        OHLCData(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]

    return calculate_ktmi(
        ohlc_bars,
        DEFAULT_KTMI_CONFIG,
    )


# ---------------------------------------------------------------------
# Signal calculation
# ---------------------------------------------------------------------


def calculate_signal_series(
    ktmi_results,
):
    """
    Calculate KTMI signals across the complete KTMI series.

    The existing KTMI signal engine handles previous-bar
    information internally, so the complete KTMI result
    sequence is passed directly to calculate_signals().
    """

    return calculate_signals(
        results=ktmi_results,
        config=DEFAULT_KTMI_CONFIG,
    )


# ---------------------------------------------------------------------
# Main integration test
# ---------------------------------------------------------------------


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — FYERS BACKTEST INTEGRATION V1")
    print("=" * 78)

    # -------------------------------------------------------------
    # Step 1 — Load FYERS data
    # -------------------------------------------------------------

    bars = load_fyers_bars()

    assert len(bars) > 0

    print()
    print("STEP 1 — FYERS HISTORICAL DATA")
    print("-" * 78)

    print("Database :", DATABASE_PATH)
    print("Symbol   :", SYMBOL)
    print("Timeframe:", TIMEFRAME)
    print("Bars     :", len(bars))

    print(
        "First    :",
        bars[0].timestamp,
        bars[0].close,
    )

    print(
        "Last     :",
        bars[-1].timestamp,
        bars[-1].close,
    )

    # -------------------------------------------------------------
    # Step 2 — Calculate KTMI
    # -------------------------------------------------------------

    ktmi_results = calculate_ktmi_series(
        bars
    )

    assert len(ktmi_results) == len(bars)

    print()
    print("STEP 2 — KTMI UNIVERSAL")
    print("-" * 78)

    print(
        "KTMI results:",
        len(ktmi_results),
    )

    # -------------------------------------------------------------
    # Step 3 — Calculate signals
    # -------------------------------------------------------------

    signal_results = calculate_signal_series(
        ktmi_results
    )

    assert len(signal_results) == len(bars)

    print()
    print("STEP 3 — KTMI SIGNAL ENGINE")
    print("-" * 78)

    print(
        "Signal results:",
        len(signal_results),
    )

    # -------------------------------------------------------------
    # Step 4 — Strategy decisions
    # -------------------------------------------------------------

    strategy_config = KTMIEntryConfig(
        require_bullish_confluence=False,
        require_bearish_confluence=False,
        allow_module_signals=True,
        allow_confluence_signals=True,
    )

    strategy_decisions = []

    long_count = 0
    short_count = 0
    no_entry_count = 0

    for signal in signal_results:

        decision = evaluate_ktmi_entry(
            signals=signal,
            strategy_config=strategy_config,
            ktmi_config=DEFAULT_KTMI_CONFIG,
        )

        strategy_decisions.append(
            decision
        )

        if decision.action.value == "LONG":
            long_count += 1

        elif decision.action.value == "SHORT":
            short_count += 1

        else:
            no_entry_count += 1

    assert len(strategy_decisions) == len(bars)

    print()
    print("STEP 4 — STRATEGY ENGINE")
    print("-" * 78)

    print("LONG entries :", long_count)
    print("SHORT entries:", short_count)
    print("NO ENTRY     :", no_entry_count)

    # -------------------------------------------------------------
    # Step 5 — Convert strategy signals into entries
    # -------------------------------------------------------------

    entries: list[BacktestEntry] = []

    for index, decision in enumerate(
        strategy_decisions
    ):

        if decision.action.value not in (
            "LONG",
            "SHORT",
        ):
            continue

        bar = bars[index]

        if decision.action.value == "LONG":

            direction = Direction.LONG

        else:

            direction = Direction.SHORT

        # ---------------------------------------------------------
        # Controlled risk test
        #
        # We deliberately use a simple fixed price distance.
        # This is NOT the final Kunal Quant SL model.
        #
        # It exists only so Risk Engine V1 can produce a quantity.
        # ---------------------------------------------------------

        if direction == Direction.LONG:

            stop_loss = bar.close - 10.0

        else:

            stop_loss = bar.close + 10.0

        risk_request = RiskRequest(
            capital=STARTING_CAPITAL,
            entry_price=bar.close,
            stop_loss_price=stop_loss,
            lot_size=LOT_SIZE,
            method=RiskMethod.FIXED_AMOUNT,
            fixed_risk_amount=FIXED_RISK_PER_TRADE,
        )

        risk_result = calculate_position_size(
            risk_request
        )

        if risk_result.quantity <= 0:
            continue

        entries.append(
            BacktestEntry(
                direction=direction,
                timestamp=bar.timestamp,
                price=bar.close,
                quantity=risk_result.quantity,
                lot_size=LOT_SIZE,
                strategy_id=STRATEGY_ID,
                config_version=CONFIG_VERSION,
            )
        )

    print()
    print("STEP 5 — RISK ENGINE")
    print("-" * 78)

    print(
        "Tradable entries:",
        len(entries),
    )

    # -------------------------------------------------------------
    # Step 6 — Controlled exits
    # -------------------------------------------------------------

    entry_exit_pairs = []

    for entry in entries:

        entry_index = next(
            (
                i
                for i, bar in enumerate(bars)
                if bar.timestamp == entry.timestamp
            ),
            None,
        )

        if entry_index is None:
            continue

        exit_index = entry_index + 1

        if exit_index >= len(bars):
            continue

        exit_bar = bars[exit_index]

        entry_exit_pairs.append(
            (
                entry,
                BacktestExit(
                    timestamp=exit_bar.timestamp,
                    price=exit_bar.close,
                    reason=ExitReason.TIME_EXIT,
                ),
            )
        )

    # -------------------------------------------------------------
    # Step 7 — Run Backtest Engine
    # -------------------------------------------------------------

    result = run_controlled_backtest(
        starting_capital=STARTING_CAPITAL,
        entries_and_exits=entry_exit_pairs,
    )

    print()
    print("STEP 6 — BACKTEST ENGINE")
    print("-" * 78)

    print(
        "Completed trades:",
        result.trade_count,
    )

    print(
        "Starting capital :",
        result.starting_capital,
    )

    print(
        "Total P&L        :",
        result.total_pnl,
    )

    print(
        "Final equity     :",
        result.final_equity,
    )

    # -------------------------------------------------------------
    # Step 8 — Show sample trades
    # -------------------------------------------------------------

    print()
    print("STEP 7 — SAMPLE TRADES")
    print("-" * 78)

    for number, trade in enumerate(
        result.trades[:10],
        start=1,
    ):

        print(
            f"{number:02d} | "
            f"{trade.direction.value:<5} | "
            f"Entry {trade.entry_price:<10.2f} | "
            f"Exit {trade.exit_price:<10.2f} | "
            f"Qty {trade.quantity:<5} | "
            f"P&L {trade.gross_pnl:>10.2f} | "
            f"{trade.exit_reason.value}"
        )

    # -------------------------------------------------------------
    # Final validation
    # -------------------------------------------------------------

    assert len(ktmi_results) == len(bars)

    assert len(signal_results) == len(bars)

    assert len(strategy_decisions) == len(bars)

    assert result.final_equity == (
        result.starting_capital
        + result.total_pnl
    )

    print()
    print("=" * 78)
    print("FYERS → KTMI → STRATEGY → RISK → BACKTEST")
    print("INTEGRATION PIPELINE PASSED")
    print("=" * 78)


if __name__ == "__main__":
    main()