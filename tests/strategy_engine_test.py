"""
Integration test for the Kunal Quant strategy engine.

Uses the actual FYERS NIFTY 1-minute candles stored in the
Kunal Quant database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from indicators.ktmi.config import (
    KTMIConfig,
    MomentumConfig,
)
from indicators.ktmi.universal import OHLCData
from strategies.direction_filter import DirectionMode
from strategies.ktmi_strategy import KTMIEntryConfig
from strategies.strategy_engine import (
    StrategyEngineConfig,
    evaluate_bar,
    evaluate_series,
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


def load_bars() -> list[OHLCData]:

    connection = sqlite3.connect(
        DATABASE_PATH
    )

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
            "No FYERS candles found."
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


def build_config(
    direction_mode: DirectionMode,
) -> StrategyEngineConfig:

    ktmi_config = KTMIConfig(
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

    entry_config = KTMIEntryConfig(
        allow_module_signals=True,
        allow_confluence_signals=True,
        direction_mode=direction_mode,
    )

    return StrategyEngineConfig(
        ktmi_config=ktmi_config,
        entry_config=entry_config,
        direction_mode=direction_mode,
    )


def main() -> None:

    print("=" * 78)
    print("KUNAL QUANT — STRATEGY ENGINE FYERS TEST")
    print("=" * 78)

    bars = load_bars()

    print()
    print(f"Symbol       : {SYMBOL}")
    print(f"FYERS bars   : {len(bars)}")
    print(f"Timeframe    : {TIMEFRAME}")

    # ---------------------------------------------------------
    # Test 1 — Complete series
    # ---------------------------------------------------------

    config = build_config(
        DirectionMode.BOTH
    )

    results = evaluate_series(
        bars,
        config,
    )

    assert len(results) == len(bars)

    print()
    print(
        f"PASS | Series evaluation: "
        f"{len(results)} results"
    )

    # ---------------------------------------------------------
    # Test 2 — Latest-bar evaluation
    # ---------------------------------------------------------

    latest = evaluate_bar(
        bars,
        config,
    )

    assert latest.ktmi == results[-1].ktmi
    assert latest.signals == results[-1].signals
    assert latest.decision == results[-1].decision

    print(
        "PASS | Latest-bar evaluation matches series evaluation"
    )

    # ---------------------------------------------------------
    # Test 3 — Result structure
    # ---------------------------------------------------------

    assert latest.ktmi is not None
    assert latest.signals is not None
    assert latest.decision is not None

    print(
        "PASS | KTMI → Signals → Strategy decision chain"
    )

    # ---------------------------------------------------------
    # Test 4 — Count strategy decisions
    # ---------------------------------------------------------

    long_entries = sum(
        1
        for result in results
        if result.decision.action.value == "LONG"
    )

    short_entries = sum(
        1
        for result in results
        if result.decision.action.value == "SHORT"
    )

    no_entries = sum(
        1
        for result in results
        if result.decision.action.value == "NO_ENTRY"
    )

    assert (
        long_entries
        + short_entries
        + no_entries
        == len(results)
    )

    print()
    print("STRATEGY DECISION SUMMARY")
    print("-" * 78)
    print(f"LONG entries   : {long_entries}")
    print(f"SHORT entries  : {short_entries}")
    print(f"NO ENTRY       : {no_entries}")
    print(f"TOTAL          : {len(results)}")

    # ---------------------------------------------------------
    # Test 5 — LONG_ONLY
    # ---------------------------------------------------------

    long_only_config = build_config(
        DirectionMode.LONG_ONLY
    )

    long_only_results = evaluate_series(
        bars,
        long_only_config,
    )

    blocked_shorts = sum(
        1
        for result in long_only_results
        if result.decision.reason.value
        == "SHORT_SIGNAL_BLOCKED"
    )

    actual_short_entries = sum(
        1
        for result in long_only_results
        if result.decision.action.value == "SHORT"
    )

    assert actual_short_entries == 0

    print()
    print(
        f"PASS | LONG_ONLY blocked "
        f"{blocked_shorts} SHORT decisions"
    )

    # ---------------------------------------------------------
    # Test 6 — SHORT_ONLY
    # ---------------------------------------------------------

    short_only_config = build_config(
        DirectionMode.SHORT_ONLY
    )

    short_only_results = evaluate_series(
        bars,
        short_only_config,
    )

    blocked_longs = sum(
        1
        for result in short_only_results
        if result.decision.reason.value
        == "LONG_SIGNAL_BLOCKED"
    )

    actual_long_entries = sum(
        1
        for result in short_only_results
        if result.decision.action.value == "LONG"
    )

    assert actual_long_entries == 0

    print(
        f"PASS | SHORT_ONLY blocked "
        f"{blocked_longs} LONG decisions"
    )

    # ---------------------------------------------------------
    # Test 7 — Deterministic engine
    # ---------------------------------------------------------

    results_again = evaluate_series(
        bars,
        config,
    )

    assert results == results_again

    print(
        "PASS | Strategy engine is deterministic"
    )

    print()
    print("=" * 78)
    print("ALL STRATEGY ENGINE FYERS TESTS PASSED")
    print("=" * 78)


if __name__ == "__main__":
    main()