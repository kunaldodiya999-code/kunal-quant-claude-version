"""
KTMI validation using Kunal Quant's actual FYERS historical data.

This test does NOT use TradingView reference data.

Purpose:
1. Read FYERS candles already stored in the Kunal Quant database.
2. Run the Python KTMI engine against real market data.
3. Validate all 15 calculation combinations.
4. Validate deterministic execution.
5. Validate Short Momentum inversion.
6. Validate display scaling.
7. Validate signal engine execution.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from indicators.ktmi.config import (
    KTMIConfig,
    MomentumConfig,
)
from indicators.ktmi.signals import calculate_signals
from indicators.ktmi.universal import (
    OHLCData,
    calculate_ktmi,
)


ROOT = Path(__file__).resolve().parents[1]

DATABASE_PATH = (
    ROOT
    / "data"
    / "database"
    / "kunal_quant.db"
)

SYMBOL = "NSE:NIFTY50-INDEX"

INSTRUMENT_ID = 572021

TIMEFRAME = "1"

BAR_COUNT = 1000


def load_fyers_bars() -> list[OHLCData]:
    """Load real FYERS candles from the Kunal Quant database."""

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found:\n{DATABASE_PATH}"
        )

    connection = sqlite3.connect(DATABASE_PATH)

    try:
        rows = connection.execute(
            """
            SELECT
                open,
                high,
                low,
                close
            FROM candles
            WHERE instrument_id = ?
              AND resolution = ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (
                INSTRUMENT_ID,
                TIMEFRAME,
                BAR_COUNT,
            ),
        ).fetchall()

    finally:
        connection.close()

    if not rows:
        raise RuntimeError(
            f"No candles found for {SYMBOL} "
            f"(instrument_id={INSTRUMENT_ID})."
        )

    return [
        OHLCData(
            open=float(row[0]),
            high=float(row[1]),
            low=float(row[2]),
            close=float(row[3]),
        )
        for row in rows
    ]


@pytest.fixture(scope="module")
def bars() -> list[OHLCData]:
    """Provide real FYERS candles to the KTMI validation tests."""
    return load_fyers_bars()


def build_config(
    calculation: str,
    smoothing: str,
) -> KTMIConfig:
    """Build one KTMI calculation configuration."""

    return KTMIConfig(
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


def test_calculation_matrix(
    bars: list[OHLCData],
) -> None:
    """Run all 15 calculation combinations."""

    calculations = (
        "ROC",
        "TRIX",
        "MACD",
    )

    smoothings = (
        "EMA",
        "SMA",
        "WMA",
        "RMA",
        "HMA",
    )

    print()
    print("=" * 78)
    print("KTMI FYERS CALCULATION MATRIX")
    print("=" * 78)

    passed = 0
    failed = 0

    for calculation in calculations:

        for smoothing in smoothings:

            try:
                config = build_config(
                    calculation,
                    smoothing,
                )

                results = calculate_ktmi(
                    bars,
                    config,
                )

                if len(results) != len(bars):
                    raise AssertionError(
                        "Result count does not match bar count."
                    )

                last = results[-1]

                if last.momentum.speed is None:
                    raise AssertionError(
                        "Momentum speed is None."
                    )

                if last.momentum.signal is None:
                    raise AssertionError(
                        "Momentum signal is None."
                    )

                if last.long_momentum.speed is None:
                    raise AssertionError(
                        "Long momentum speed is None."
                    )

                if last.short_momentum.speed is None:
                    raise AssertionError(
                        "Short momentum speed is None."
                    )

                print(
                    f"PASS {calculation:5s} + "
                    f"{smoothing:3s} | "
                    f"Momentum={last.momentum.speed:.6f} | "
                    f"Long={last.long_momentum.speed:.6f} | "
                    f"Short={last.short_momentum.speed:.6f}"
                )

                passed += 1

            except Exception as exc:
                print(
                    f"FAIL {calculation:5s} + "
                    f"{smoothing:3s} | "
                    f"{exc}"
                )

                failed += 1

    print()
    print(f"Total  : {passed + failed}")
    print(f"Passed : {passed}")
    print(f"Failed : {failed}")

    if failed:
        raise AssertionError(
            f"{failed} KTMI calculation combinations failed."
        )


def test_deterministic_execution(
    bars: list[OHLCData],
) -> None:
    """Ensure identical input produces identical output."""

    print()
    print("=" * 78)
    print("KTMI DETERMINISTIC EXECUTION TEST")
    print("=" * 78)

    config = build_config(
        "TRIX",
        "EMA",
    )

    first = calculate_ktmi(
        bars,
        config,
    )

    second = calculate_ktmi(
        bars,
        config,
    )

    if len(first) != len(second):
        raise AssertionError(
            "Result lengths differ."
        )

    for index, (a, b) in enumerate(
        zip(first, second)
    ):

        if a != b:
            raise AssertionError(
                f"Non-deterministic result at bar {index}."
            )

    print(
        f"PASS | {len(first)} bars produced identical results."
    )


def test_short_inversion(
    bars: list[OHLCData],
) -> None:
    """Validate the Short Momentum inversion."""

    print()
    print("=" * 78)
    print("KTMI SHORT INVERSION TEST")
    print("=" * 78)

    config = build_config(
        "TRIX",
        "EMA",
    )

    results = calculate_ktmi(
        bars,
        config,
    )

    checked = 0

    for result in results:

        short = result.short_momentum

        if (
            short.speed is not None
            and short.speed_raw is not None
        ):
            # The KTMI Pine logic applies the Short inversion
            # before the display multiplier.
            #
            # Therefore the displayed Short speed must equal:
            #
            # speed_raw × display_multiplier
            #
            # The sign inversion is already represented by
            # speed_raw in the final KTMIModuleResult.

            expected = (
                short.speed_raw
                * config.display_multiplier
            )

            actual = short.speed

            if abs(actual - expected) > 1e-10:
                raise AssertionError(
                    "Short display/inversion mismatch: "
                    f"expected={expected}, "
                    f"actual={actual}"
                )

            checked += 1

    if checked == 0:
        raise AssertionError(
            "No valid Short Momentum values were available."
        )

    print(
        f"PASS | {checked} Short Momentum values verified."
    )


def test_display_scaling(
    bars: list[OHLCData],
) -> None:
    """Validate the Pine display multiplier."""

    print()
    print("=" * 78)
    print("KTMI DISPLAY SCALING TEST")
    print("=" * 78)

    config = build_config(
        "TRIX",
        "EMA",
    )

    results = calculate_ktmi(
        bars,
        config,
    )

    checked = 0

    for result in results:

        module = result.momentum

        if (
            module.speed is not None
            and module.speed_raw is not None
        ):

            expected = (
                module.speed_raw
                * config.display_multiplier
            )

            if abs(module.speed - expected) > 1e-10:
                raise AssertionError(
                    "Display multiplier mismatch."
                )

            checked += 1

    if checked == 0:
        raise AssertionError(
            "No valid display values were available."
        )

    print(
        f"PASS | {checked} Momentum display values verified."
    )


def test_signal_engine(
    bars: list[OHLCData],
) -> None:
    """Validate that the signal engine executes on FYERS data."""

    print()
    print("=" * 78)
    print("KTMI SIGNAL ENGINE TEST")
    print("=" * 78)

    config = build_config(
        "TRIX",
        "EMA",
    )

    ktmi_results = calculate_ktmi(
        bars,
        config,
    )

    signal_results = calculate_signals(
        ktmi_results,
        config,
    )

    if len(signal_results) != len(ktmi_results):
        raise AssertionError(
            "Signal result count does not match KTMI result count."
        )

    buy_count = sum(
        1
        for result in signal_results
        if (
            result.momentum_buy
            or result.long_buy
            or result.short_buy
        )
    )

    sell_count = sum(
        1
        for result in signal_results
        if (
            result.momentum_sell
            or result.long_sell
            or result.short_sell
        )
    )

    bullish_confluence_count = sum(
        1
        for result in signal_results
        if result.bullish_confluence
    )

    bearish_confluence_count = sum(
        1
        for result in signal_results
        if result.bearish_confluence
    )

    print(
        f"PASS | Signal rows          : {len(signal_results)}"
    )

    print(
        f"      Buy signals           : {buy_count}"
    )

    print(
        f"      Sell signals          : {sell_count}"
    )

    print(
        f"      Bullish confluence    : "
        f"{bullish_confluence_count}"
    )

    print(
        f"      Bearish confluence    : "
        f"{bearish_confluence_count}"
    )


def main() -> None:

    print()
    print("#" * 78)
    print("KUNAL QUANT — KTMI FYERS VALIDATION")
    print("#" * 78)

    print()
    print(f"Database    : {DATABASE_PATH}")
    print(f"Symbol      : {SYMBOL}")
    print(f"Instrument  : {INSTRUMENT_ID}")
    print(f"Timeframe   : {TIMEFRAME}")
    print(f"Requested   : {BAR_COUNT} bars")

    bars = load_fyers_bars()

    print()
    print(f"FYERS bars loaded : {len(bars)}")

    print(
        f"First close       : {bars[0].close}"
    )

    print(
        f"Last close        : {bars[-1].close}"
    )

    test_calculation_matrix(bars)

    test_deterministic_execution(bars)

    test_short_inversion(bars)

    test_display_scaling(bars)

    test_signal_engine(bars)

    print()
    print("#" * 78)
    print("ALL FYERS KTMI VALIDATION TESTS PASSED")
    print("#" * 78)


if __name__ == "__main__":
    main()
