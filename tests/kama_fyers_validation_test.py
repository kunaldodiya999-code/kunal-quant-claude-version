"""
Kunal Quant — KAMA FYERS Validation Test V1.

Purpose:
    Validate the KAMA Trend Follower calculation engine
    against real FYERS historical NIFTY 1-minute data.

This test does NOT:
    - generate trades
    - modify KTMI
    - implement exits
    - modify the backtest engine

It validates only the KAMA indicator calculation pipeline.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from indicators.kama_trend_follower.config import (
    DEFAULT_KAMA_CONFIG,
)
from indicators.kama_trend_follower.universal import (
    KAMABar,
    calculate_kama_trend,
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


def load_fyers_bars() -> list[KAMABar]:
    """Load real FYERS historical NIFTY candles."""

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
        KAMABar(
            open=float(row[0]),
            high=float(row[1]),
            low=float(row[2]),
            close=float(row[3]),
        )
        for row in rows
    ]


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — KAMA FYERS VALIDATION TEST V1")
    print("=" * 78)

    # -------------------------------------------------------------
    # Step 1 — Load FYERS data
    # -------------------------------------------------------------

    bars = load_fyers_bars()

    assert len(bars) == BAR_LIMIT

    print()
    print("STEP 1 — FYERS HISTORICAL DATA")
    print("-" * 78)

    print("Symbol   :", SYMBOL)
    print("Timeframe:", TIMEFRAME)
    print("Bars     :", len(bars))

    print(
        "First close:",
        bars[0].close,
    )

    print(
        "Last close :",
        bars[-1].close,
    )

    # -------------------------------------------------------------
    # Step 2 — Calculate KAMA
    # -------------------------------------------------------------

    results = calculate_kama_trend(
        bars,
        DEFAULT_KAMA_CONFIG,
    )

    assert len(results) == len(bars)

    print()
    print("STEP 2 — KAMA CALCULATION")
    print("-" * 78)

    print(
        "KAMA results:",
        len(results),
    )

    # -------------------------------------------------------------
    # Step 3 — Basic validity
    # -------------------------------------------------------------

    valid_kama = [
        result
        for result in results
        if result.kama is not None
    ]

    assert len(valid_kama) > 0

    print()
    print("STEP 3 — KAMA VALIDITY")
    print("-" * 78)

    print(
        "Valid KAMA values:",
        len(valid_kama),
    )

    print(
        "First KAMA:",
        valid_kama[0].kama,
    )

    print(
        "Last KAMA:",
        valid_kama[-1].kama,
    )

    # -------------------------------------------------------------
    # Step 4 — Trend state counts
    # -------------------------------------------------------------

    bullish = sum(
        1
        for result in results
        if result.kama_bull
    )

    bearish = sum(
        1
        for result in results
        if result.kama_bear
    )

    sideways = sum(
        1
        for result in results
        if result.kama_sideways
    )

    print()
    print("STEP 4 — KAMA TREND STATES")
    print("-" * 78)

    print(
        "Bullish  :",
        bullish,
    )

    print(
        "Bearish  :",
        bearish,
    )

    print(
        "Sideways :",
        sideways,
    )

    assert (
        bullish
        + bearish
        + sideways
        == len(results)
    )

    # -------------------------------------------------------------
    # Step 5 — Direction counts
    # -------------------------------------------------------------

    rising = sum(
        1
        for result in results
        if result.kama_direction == 1
    )

    falling = sum(
        1
        for result in results
        if result.kama_direction == -1
    )

    print()
    print("STEP 5 — KAMA DIRECTION")
    print("-" * 78)

    print(
        "Rising  :",
        rising,
    )

    print(
        "Falling :",
        falling,
    )

    assert (
        rising
        + falling
        == len(results)
    )

    # -------------------------------------------------------------
    # Step 6 — EMA calculations
    # -------------------------------------------------------------

    ma50_valid = sum(
        1
        for result in results
        if result.ma50 is not None
    )

    ma100_valid = sum(
        1
        for result in results
        if result.ma100 is not None
    )

    ma200_valid = sum(
        1
        for result in results
        if result.ma200 is not None
    )

    print()
    print("STEP 6 — EMA CALCULATIONS")
    print("-" * 78)

    print(
        "EMA 50 valid :",
        ma50_valid,
    )

    print(
        "EMA 100 valid:",
        ma100_valid,
    )

    print(
        "EMA 200 valid:",
        ma200_valid,
    )

    assert ma50_valid == len(results)
    assert ma100_valid == len(results)
    assert ma200_valid == len(results)

    # -------------------------------------------------------------
    # Step 7 — Display latest result
    # -------------------------------------------------------------

    latest = results[-1]

    print()
    print("STEP 7 — LATEST KAMA STATE")
    print("-" * 78)

    print(
        "Close              :",
        bars[-1].close,
    )

    print(
        "KAMA               :",
        latest.kama,
    )

    print(
        "Direction          :",
        latest.kama_direction,
    )

    print(
        "Percentage change  :",
        latest.kama_percentage_change,
    )

    print(
        "Bull                :",
        latest.kama_bull,
    )

    print(
        "Bear                :",
        latest.kama_bear,
    )

    print(
        "Sideways            :",
        latest.kama_sideways,
    )

    print(
        "EMA 50              :",
        latest.ma50,
    )

    print(
        "EMA 100             :",
        latest.ma100,
    )

    print(
        "EMA 200             :",
        latest.ma200,
    )

    # -------------------------------------------------------------
    # Final validation
    # -------------------------------------------------------------

    print()
    print("=" * 78)
    print("KAMA FYERS VALIDATION PASSED")
    print("=" * 78)


if __name__ == "__main__":
    main()