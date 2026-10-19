"""
KTMI Universal Pine parity test.

This compares Python KTMI output against reference values exported
from TradingView.

Reference CSV format:

index,timestamp,open,high,low,close,
momentum_speed,momentum_signal,
long_speed,long_signal,
short_speed,short_signal

The test intentionally does not modify the KTMI engine.
"""

from __future__ import annotations

import csv
import math
import sqlite3
from pathlib import Path

from indicators.ktmi.config import KTMIConfig, MomentumConfig
from indicators.ktmi.universal import OHLCData, calculate_ktmi


ROOT = Path(__file__).resolve().parents[1]

DATABASE_PATH = (
    ROOT
    / "data"
    / "database"
    / "kunal_quant.db"
)

REFERENCE_PATH = (
    ROOT
    / "data"
    / "validation"
    / "ktmi_tradingview_reference.csv"
)

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"

TOLERANCE = 1e-6


def load_reference() -> list[dict]:
    """Load TradingView reference CSV."""

    if not REFERENCE_PATH.exists():
        raise FileNotFoundError(
            f"""
TradingView reference file not found:

{REFERENCE_PATH}

Create/export the TradingView reference CSV first.
"""
        )

    with REFERENCE_PATH.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:

        return list(csv.DictReader(file))


def find_instrument_id(
    connection: sqlite3.Connection,
) -> int:
    """Find NIFTY instrument ID."""

    row = connection.execute(
        """
        SELECT id
        FROM instruments
        WHERE symbol = ?
        LIMIT 1
        """,
        (NIFTY_SYMBOL,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Instrument not found: {NIFTY_SYMBOL}"
        )

    return int(row[0])


def load_python_bars(
    connection: sqlite3.Connection,
    instrument_id: int,
    count: int,
) -> list[OHLCData]:
    """Load the same number of NIFTY candles."""

    rows = connection.execute(
        """
        SELECT
            open,
            high,
            low,
            close
        FROM candles
        WHERE instrument_id = ?
          AND resolution = '1'
        ORDER BY timestamp ASC
        LIMIT ?
        """,
        (instrument_id, count),
    ).fetchall()

    return [
        OHLCData(
            open=float(row[0]),
            high=float(row[1]),
            low=float(row[2]),
            close=float(row[3]),
        )
        for row in rows
    ]


def compare_value(
    name: str,
    python_value: float | None,
    tradingview_value: float | None,
) -> float | None:
    """Compare one numerical value."""

    if python_value is None and tradingview_value is None:
        return None

    if python_value is None or tradingview_value is None:
        raise AssertionError(
            f"{name}: one value is None while the other is not"
        )

    if not math.isfinite(python_value):
        raise AssertionError(
            f"{name}: Python value is not finite: {python_value}"
        )

    difference = abs(
        python_value - tradingview_value
    )

    if difference > TOLERANCE:
        raise AssertionError(
            f"{name}: "
            f"Python={python_value:.12f}, "
            f"TradingView={tradingview_value:.12f}, "
            f"difference={difference:.12f}"
        )

    return difference


def main() -> None:
    print("=" * 78)
    print("KTMI TRADINGVIEW / PYTHON PARITY TEST")
    print("=" * 78)

    reference = load_reference()

    if not reference:
        raise RuntimeError(
            "TradingView reference CSV contains no rows."
        )

    print()
    print(f"Reference rows : {len(reference)}")
    print(f"Tolerance      : {TOLERANCE}")

    connection = sqlite3.connect(DATABASE_PATH)

    try:
        instrument_id = find_instrument_id(connection)

        bars = load_python_bars(
            connection,
            instrument_id,
            len(reference),
        )

    finally:
        connection.close()

    if len(bars) != len(reference):
        raise AssertionError(
            f"Bar count mismatch: "
            f"Python={len(bars)}, "
            f"TradingView={len(reference)}"
        )

    config = KTMIConfig(
        momentum=MomentumConfig(
            source="Close",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
        long_momentum=MomentumConfig(
            source="Close",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
        short_momentum=MomentumConfig(
            source="Low",
            speed_length=5,
            signal_length=9,
            smoothing="EMA",
            enabled=True,
            calculation="TRIX",
        ),
    )

    results = calculate_ktmi(
        bars,
        config,
    )

    checked = 0
    maximum_difference = 0.0

    for index, (reference_row, result) in enumerate(
        zip(reference, results)
    ):

        checks = (
            (
                "momentum_speed",
                result.momentum.speed,
                float(reference_row["momentum_speed"]),
            ),
            (
                "momentum_signal",
                result.momentum.signal,
                float(reference_row["momentum_signal"]),
            ),
            (
                "long_speed",
                result.long_momentum.speed,
                float(reference_row["long_speed"]),
            ),
            (
                "long_signal",
                result.long_momentum.signal,
                float(reference_row["long_signal"]),
            ),
            (
                "short_speed",
                result.short_momentum.speed,
                float(reference_row["short_speed"]),
            ),
            (
                "short_signal",
                result.short_momentum.signal,
                float(reference_row["short_signal"]),
            ),
        )

        for name, python_value, tv_value in checks:

            difference = compare_value(
                f"row={index} {name}",
                python_value,
                tv_value,
            )

            if difference is not None:
                maximum_difference = max(
                    maximum_difference,
                    difference,
                )

            checked += 1

    print()
    print("-" * 78)
    print("PARITY RESULT")
    print("-" * 78)

    print(f"Rows checked       : {len(reference)}")
    print(f"Values checked     : {checked}")
    print(
        f"Maximum difference : "
        f"{maximum_difference:.12f}"
    )

    print()
    print("PASS: TradingView and Python values are within tolerance.")

    print()
    print("=" * 78)
    print("KTMI TRADINGVIEW / PYTHON PARITY TEST COMPLETE")
    print("=" * 78)


if __name__ == "__main__":
    main()