"""
KTMI Universal calculation matrix validation.

Tests every supported calculation method against every supported
smoothing method using real NIFTY OHLC data.

Matrix:

             EMA   SMA   WMA   RMA   HMA
ROC           X     X     X     X     X
TRIX          X     X     X     X     X
MACD          X     X     X     X     X

This test validates the Python engine internally.

It does NOT claim TradingView numerical parity.
TradingView parity will be tested separately.
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path

from indicators.ktmi.config import (
    CALCULATION_OPTIONS,
    KTMIConfig,
    MomentumConfig,
    SMOOTHING_OPTIONS,
)
from indicators.ktmi.universal import OHLCData, calculate_ktmi


DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "database"
    / "kunal_quant.db"
)

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"

BAR_LIMIT = 1000


def find_instrument_id(
    connection: sqlite3.Connection,
    symbol: str,
) -> int:
    """Find instrument ID from the instrument master."""

    row = connection.execute(
        """
        SELECT id
        FROM instruments
        WHERE symbol = ?
        LIMIT 1
        """,
        (symbol,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Instrument not found: {symbol}"
        )

    return int(row[0])


def load_nifty_data(
    connection: sqlite3.Connection,
    instrument_id: int,
    limit: int,
) -> list[OHLCData]:
    """Load NIFTY OHLC candles."""

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
        (instrument_id, limit),
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


def assert_finite(
    value: float | None,
    label: str,
) -> None:
    """Reject NaN and infinity."""

    if value is None:
        return

    if not math.isfinite(value):
        raise AssertionError(
            f"{label} produced non-finite value: {value}"
        )


def validate_module(
    result,
    label: str,
) -> None:
    """Validate one KTMI module result."""

    assert_finite(
        result.speed,
        f"{label}.speed",
    )

    assert_finite(
        result.signal,
        f"{label}.signal",
    )

    assert_finite(
        result.speed_raw,
        f"{label}.speed_raw",
    )

    assert_finite(
        result.signal_raw,
        f"{label}.signal_raw",
    )


def main() -> None:
    print("=" * 78)
    print("KTMI UNIVERSAL CALCULATION MATRIX TEST")
    print("=" * 78)

    print()
    print(f"Database : {DATABASE_PATH}")
    print(f"Symbol   : {NIFTY_SYMBOL}")
    print(f"Bars     : {BAR_LIMIT}")

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {DATABASE_PATH}"
        )

    connection = sqlite3.connect(DATABASE_PATH)

    try:
        instrument_id = find_instrument_id(
            connection,
            NIFTY_SYMBOL,
        )

        bars = load_nifty_data(
            connection,
            instrument_id,
            BAR_LIMIT,
        )

    finally:
        connection.close()

    if not bars:
        raise RuntimeError(
            "No NIFTY candles were loaded."
        )

    print(f"Instrument ID: {instrument_id}")
    print(f"Bars loaded  : {len(bars)}")

    print()
    print("-" * 78)
    print("SUPPORTED MATRIX")
    print("-" * 78)

    print()
    print("             EMA   SMA   WMA   RMA   HMA")
    print("ROC          X     X     X     X     X")
    print("TRIX         X     X     X     X     X")
    print("MACD         X     X     X     X     X")

    total_tests = 0
    passed_tests = 0

    print()
    print("-" * 78)
    print("RUNNING MATRIX")
    print("-" * 78)

    for calculation in CALCULATION_OPTIONS:

        for smoothing in SMOOTHING_OPTIONS:

            total_tests += 1

            config = KTMIConfig(
                momentum=MomentumConfig(
                    source="Close",
                    speed_length=5,
                    signal_length=9,
                    smoothing=smoothing,
                    enabled=True,
                    calculation=calculation,
                ),
                long_momentum=MomentumConfig(
                    source="Close",
                    speed_length=5,
                    signal_length=9,
                    smoothing=smoothing,
                    enabled=True,
                    calculation=calculation,
                ),
                short_momentum=MomentumConfig(
                    source="Low",
                    speed_length=5,
                    signal_length=9,
                    smoothing=smoothing,
                    enabled=True,
                    calculation=calculation,
                ),
            )

            results = calculate_ktmi(
                bars,
                config,
            )

            assert len(results) == len(bars), (
                f"{calculation}/{smoothing}: "
                "result count mismatch"
            )

            # Find the final fully populated result.
            valid_index = None

            for index in range(
                len(results) - 1,
                -1,
                -1,
            ):
                result = results[index]

                if (
                    result.momentum.speed is not None
                    and result.momentum.signal is not None
                    and result.long_momentum.speed is not None
                    and result.long_momentum.signal is not None
                    and result.short_momentum.speed is not None
                    and result.short_momentum.signal is not None
                ):
                    valid_index = index
                    break

            if valid_index is None:
                raise AssertionError(
                    f"{calculation}/{smoothing}: "
                    "no fully populated result"
                )

            result = results[valid_index]

            # Validate all three modules.
            validate_module(
                result.momentum,
                "momentum",
            )

            validate_module(
                result.long_momentum,
                "long_momentum",
            )

            validate_module(
                result.short_momentum,
                "short_momentum",
            )

            # ----------------------------------------------------------
            # SHORT INVERSION CHECK
            # ----------------------------------------------------------
            #
            # Pine:
            #
            # shortSpeedRaw = -shortSpeedUnreversed
            #
            # Our result.speed_raw should therefore be the negative
            # of the unreversed calculation.
            #
            # We cannot independently reconstruct the unreversed value
            # from the result object, so this test only verifies that
            # the short module is producing a valid directional output.
            #
            # A dedicated source-level inversion test will follow.
            # ----------------------------------------------------------

            assert result.short_momentum.speed is not None
            assert result.short_momentum.signal is not None

            passed_tests += 1

            print(
                f"PASS  {calculation:<5} + {smoothing:<3} "
                f"| index={valid_index:<4} "
                f"| speed={result.momentum.speed:>12.6f} "
                f"| short={result.short_momentum.speed:>12.6f}"
            )

    print()
    print("-" * 78)
    print("MATRIX SUMMARY")
    print("-" * 78)

    print(f"Total combinations : {total_tests}")
    print(f"Passed             : {passed_tests}")
    print(f"Failed             : {total_tests - passed_tests}")

    assert total_tests == 15
    assert passed_tests == 15

    print()
    print("PASS: All 15 calculation/smoothing combinations executed.")
    print("PASS: All three KTMI modules produced valid final values.")
    print("PASS: No NaN or infinite final values detected.")

    print()
    print("=" * 78)
    print("KTMI CALCULATION MATRIX TEST COMPLETE")
    print("=" * 78)
    print()
    print(
        "IMPORTANT: This validates the Python implementation internally."
    )
    print(
        "It does not yet establish TradingView numerical parity."
    )


if __name__ == "__main__":
    main()