"""
Kunal Quant — KTMI Strategy Parity Test V1.

Purpose:
    Verify that the KTMI signal engine and strategy engine
    preserve the expected signal/confluence behavior on the
    same FYERS historical data.

This test does NOT modify:
    - KTMI Universal
    - KTMI defaults
    - Strategy rules
    - Risk rules
    - Backtest rules

It is a diagnostic/parity test only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from indicators.ktmi.config import DEFAULT_KTMI_CONFIG
from indicators.ktmi.signals import calculate_signals
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from strategies.ktmi_strategy import (
    KTMIEntryConfig,
    evaluate_ktmi_entry,
)


DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "database"
    / "kunal_quant.db"
)

SYMBOL = "NSE:NIFTY50-INDEX"
TIMEFRAME = "1"
BAR_LIMIT = 1000


def load_bars() -> list[OHLCData]:

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                c.open,
                c.high,
                c.low,
                c.close
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

    return [
        OHLCData(
            open=float(row[0]),
            high=float(row[1]),
            low=float(row[2]),
            close=float(row[3]),
        )
        for row in rows
    ]


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — KTMI STRATEGY PARITY TEST V1")
    print("=" * 78)

    # -------------------------------------------------------------
    # Step 1 — Load FYERS bars
    # -------------------------------------------------------------

    bars = load_bars()

    assert len(bars) == BAR_LIMIT

    print()
    print("STEP 1 — FYERS DATA")
    print("-" * 78)
    print("Bars:", len(bars))

    # -------------------------------------------------------------
    # Step 2 — KTMI
    # -------------------------------------------------------------

    ktmi_results = calculate_ktmi(
        bars,
        DEFAULT_KTMI_CONFIG,
    )

    assert len(ktmi_results) == len(bars)

    print()
    print("STEP 2 — KTMI UNIVERSAL")
    print("-" * 78)
    print("Results:", len(ktmi_results))

    # -------------------------------------------------------------
    # Step 3 — Signals
    # -------------------------------------------------------------

    signals = calculate_signals(
        results=ktmi_results,
        config=DEFAULT_KTMI_CONFIG,
    )

    assert len(signals) == len(bars)

    momentum_buy = sum(
        1 for item in signals
        if item.momentum_buy
    )

    momentum_sell = sum(
        1 for item in signals
        if item.momentum_sell
    )

    long_buy = sum(
        1 for item in signals
        if item.long_buy
    )

    long_sell = sum(
        1 for item in signals
        if item.long_sell
    )

    short_buy = sum(
        1 for item in signals
        if item.short_buy
    )

    short_sell = sum(
        1 for item in signals
        if item.short_sell
    )

    bullish_confluence = sum(
        1 for item in signals
        if item.bullish_confluence
    )

    bearish_confluence = sum(
        1 for item in signals
        if item.bearish_confluence
    )

    print()
    print("STEP 3 — SIGNAL COUNTS")
    print("-" * 78)

    print(
        "Momentum Buy        :",
        momentum_buy,
    )

    print(
        "Momentum Sell       :",
        momentum_sell,
    )

    print(
        "Long Buy            :",
        long_buy,
    )

    print(
        "Long Sell           :",
        long_sell,
    )

    print(
        "Short Buy           :",
        short_buy,
    )

    print(
        "Short Sell          :",
        short_sell,
    )

    print(
        "Bullish Confluence  :",
        bullish_confluence,
    )

    print(
        "Bearish Confluence  :",
        bearish_confluence,
    )

    # -------------------------------------------------------------
    # Step 4 — Strategy configuration
    # -------------------------------------------------------------

    strategy_config = KTMIEntryConfig(
        require_bullish_confluence=False,
        require_bearish_confluence=False,
        allow_module_signals=True,
        allow_confluence_signals=True,
    )

    decisions = [
        evaluate_ktmi_entry(
            signals=item,
            strategy_config=strategy_config,
            ktmi_config=DEFAULT_KTMI_CONFIG,
        )
        for item in signals
    ]

    long_entries = sum(
        1 for item in decisions
        if item.action.value == "LONG"
    )

    short_entries = sum(
        1 for item in decisions
        if item.action.value == "SHORT"
    )

    no_entries = sum(
        1 for item in decisions
        if item.action.value == "NO_ENTRY"
    )

    multiple_direction = sum(
        1 for item in decisions
        if item.reason.value == "MULTIPLE_DIRECTION_SIGNALS"
    )

    print()
    print("STEP 4 — STRATEGY RESULTS")
    print("-" * 78)

    print(
        "LONG entries             :",
        long_entries,
    )

    print(
        "SHORT entries            :",
        short_entries,
    )

    print(
        "NO ENTRY                 :",
        no_entries,
    )

    print(
        "Multiple direction cases:",
        multiple_direction,
    )

    # -------------------------------------------------------------
    # Step 5 — Configuration explanation
    # -------------------------------------------------------------

    enabled_modules = 0

    if DEFAULT_KTMI_CONFIG.momentum.enabled:
        enabled_modules += 1

    if DEFAULT_KTMI_CONFIG.long_momentum.enabled:
        enabled_modules += 1

    if DEFAULT_KTMI_CONFIG.short_momentum.enabled:
        enabled_modules += 1

    print()
    print("STEP 5 — ACTIVE KTMI CONFIGURATION")
    print("-" * 78)

    print(
        "Momentum enabled      :",
        DEFAULT_KTMI_CONFIG.momentum.enabled,
    )

    print(
        "Long Momentum enabled :",
        DEFAULT_KTMI_CONFIG.long_momentum.enabled,
    )

    print(
        "Short Momentum enabled:",
        DEFAULT_KTMI_CONFIG.short_momentum.enabled,
    )

    print(
        "Enabled module count  :",
        enabled_modules,
    )

    print(
        "Momentum Buy Trigger  :",
        DEFAULT_KTMI_CONFIG.momentum_buy_trigger,
    )

    print(
        "Momentum Sell Trigger :",
        DEFAULT_KTMI_CONFIG.momentum_sell_trigger,
    )

    print(
        "Long Buy Trigger      :",
        DEFAULT_KTMI_CONFIG.long_buy_trigger,
    )

    print(
        "Long Sell Trigger     :",
        DEFAULT_KTMI_CONFIG.long_sell_trigger,
    )

    print(
        "Short Buy Trigger     :",
        DEFAULT_KTMI_CONFIG.short_buy_trigger,
    )

    print(
        "Short Sell Trigger    :",
        DEFAULT_KTMI_CONFIG.short_sell_trigger,
    )

    # -------------------------------------------------------------
    # Step 6 — Internal consistency
    # -------------------------------------------------------------

    assert (
        long_entries
        + short_entries
        + no_entries
        == len(decisions)
    )

    assert (
        momentum_buy == 0
    )

    assert (
        momentum_sell == 0
    )

    assert (
        long_buy == 0
    )

    assert (
        long_sell == 0
    )

    assert (
        short_buy == 0
    )

    assert (
        short_sell == 0
    )

    # With the current default configuration only one module
    # is enabled. Pine confluence requires >1 enabled modules.
    assert enabled_modules == 1

    assert bullish_confluence == 0

    assert bearish_confluence == 0

    assert long_entries == 0

    assert short_entries == 0

    print()
    print("=" * 78)
    print("KTMI → STRATEGY DEFAULT-CONFIG PARITY PASSED")
    print("=" * 78)


if __name__ == "__main__":
    main()