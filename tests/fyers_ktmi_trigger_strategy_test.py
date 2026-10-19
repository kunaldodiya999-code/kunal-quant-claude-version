"""
Kunal Quant — Real FYERS KTMI Trigger Strategy Test

Pipeline:

    FYERS historical database
            ↓
    KTMI Universal calculation
            ↓
    KTMI Speed values
            ↓
    Strategy A + Strategy B
            ↓
    Historical trigger events

IMPORTANT:
    This test does NOT modify the KTMI calculation.
    It does NOT modify the existing KTMI signal engine.
    It only evaluates the new trigger-strategy layer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.models import BacktestBar

from indicators.ktmi.config import (
    KTMIConfig,
    MomentumConfig,
)

from indicators.ktmi.universal import (
    OHLCData,
    calculate_ktmi,
)

from strategies.ktmi_trigger_strategy import (
    DEFAULT_KTMI_TRIGGER_CONFIG,
    KTMITriggerEvent,
    evaluate_ktmi_trigger_strategies,
)


# =====================================================================
# CONFIGURATION
# =====================================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATABASE_PATH = (
    PROJECT_ROOT
    / "data"
    / "database"
    / "kunal_quant.db"
)

INSTRUMENT_ID = 572021

SYMBOL = "NSE:NIFTY50-INDEX"

TIMEFRAME = "1"

BAR_COUNT = 1000


# =====================================================================
# LOAD FYERS DATA
# =====================================================================


def load_bars() -> list[BacktestBar]:
    """
    Load historical FYERS OHLC bars from SQLite.
    """

    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"Database not found:\n{DATABASE_PATH}"
        )

    connection = sqlite3.connect(DATABASE_PATH)

    try:

        rows = connection.execute(
            """
            SELECT
                timestamp,
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
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
        )
        for row in rows
    ]


# =====================================================================
# KTMI CONFIG
# =====================================================================


def build_ktmi_config() -> KTMIConfig:
    """
    Use the previously validated KTMI configuration.

    TRIX
    EMA
    Speed = 5
    Signal = 9
    """

    return KTMIConfig(

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

        momentum_buy_trigger=None,
        momentum_sell_trigger=None,

        long_buy_trigger=None,
        long_sell_trigger=None,

        short_buy_trigger=None,
        short_sell_trigger=None,
    )


# =====================================================================
# KTMI CALCULATION
# =====================================================================


def calculate_ktmi_results(
    bars: list[BacktestBar],
):
    """
    Calculate KTMI using the existing Universal engine.
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
        bars=ohlc_bars,
        config=build_ktmi_config(),
    )


# =====================================================================
# PRINT EVENT
# =====================================================================


def print_event(
    event: KTMITriggerEvent,
    bars: list[BacktestBar],
) -> None:

    timestamp = event.timestamp

    print(
        f"{timestamp}"
        f" | {event.strategy_id.value:24s}"
        f" | {event.direction.value:5s}"
        f" | Prev={event.previous_value: .6f}"
        f" | Curr={event.current_value: .6f}"
        f" | Trigger={event.trigger_value: .2f}"
    )


# =====================================================================
# MAIN
# =====================================================================


def main() -> None:

    print()
    print("=" * 110)
    print("KUNAL QUANT — REAL FYERS KTMI TRIGGER STRATEGY TEST")
    print("=" * 110)

    # ---------------------------------------------------------------
    # 1. FYERS DATA
    # ---------------------------------------------------------------

    bars = load_bars()

    print()
    print("FYERS DATA")
    print("-" * 110)

    print(f"Database       : {DATABASE_PATH}")
    print(f"Symbol         : {SYMBOL}")
    print(f"Instrument ID  : {INSTRUMENT_ID}")
    print(f"Timeframe      : {TIMEFRAME}")
    print(f"Bars           : {len(bars)}")

    print(
        f"First          : {bars[0].timestamp}"
        f" | Close={bars[0].close}"
    )

    print(
        f"Last           : {bars[-1].timestamp}"
        f" | Close={bars[-1].close}"
    )

    # ---------------------------------------------------------------
    # 2. KTMI
    # ---------------------------------------------------------------

    ktmi_results = calculate_ktmi_results(
        bars
    )

    assert len(ktmi_results) == len(bars)

    print()
    print("KTMI")
    print("-" * 110)

    print("Calculation    : TRIX")
    print("Smoothing      : EMA")
    print("Speed Length   : 5")
    print("Signal Length  : 9")

    print(
        f"KTMI Results   : {len(ktmi_results)}"
    )

    # ---------------------------------------------------------------
    # 3. TRIGGER STRATEGIES
    # ---------------------------------------------------------------

    events: list[KTMITriggerEvent] = []

    for index in range(1, len(ktmi_results)):

        previous = ktmi_results[index - 1]
        current = ktmi_results[index]

        previous_momentum = previous.momentum.speed
        current_momentum = current.momentum.speed

        previous_long = previous.long_momentum.speed
        current_long = current.long_momentum.speed

        previous_short = previous.short_momentum.speed
        current_short = current.short_momentum.speed

        current_timestamp = bars[index].timestamp

        current_events = evaluate_ktmi_trigger_strategies(

            previous_momentum_speed=previous_momentum,
            current_momentum_speed=current_momentum,

            previous_long_speed=previous_long,
            current_long_speed=current_long,

            previous_short_speed=previous_short,
            current_short_speed=current_short,

            config=DEFAULT_KTMI_TRIGGER_CONFIG,

            index=index,

            timestamp=current_timestamp,
        )

        events.extend(current_events)

    # ---------------------------------------------------------------
    # 4. SEPARATE RESULTS
    # ---------------------------------------------------------------

    strategy_a = [
        event
        for event in events
        if event.strategy_id.value
        == "KTMI_LONG_SHORT_SPEED"
    ]

    strategy_b = [
        event
        for event in events
        if event.strategy_id.value
        == "KTMI_MOMENTUM_ONLY"
    ]

    a_long = [
        event
        for event in strategy_a
        if event.direction.value == "LONG"
    ]

    a_short = [
        event
        for event in strategy_a
        if event.direction.value == "SHORT"
    ]

    b_long = [
        event
        for event in strategy_b
        if event.direction.value == "LONG"
    ]

    b_short = [
        event
        for event in strategy_b
        if event.direction.value == "SHORT"
    ]

    # ---------------------------------------------------------------
    # 5. REPORT
    # ---------------------------------------------------------------

    print()
    print("STRATEGY RESULTS")
    print("-" * 110)

    print()
    print("STRATEGY A — KTMI_LONG_SHORT_SPEED")

    print(
        f"LONG signals  : {len(a_long)}"
    )

    print(
        f"SHORT signals : {len(a_short)}"
    )

    print(
        f"TOTAL         : {len(strategy_a)}"
    )

    print()
    print("STRATEGY B — KTMI_MOMENTUM_ONLY")

    print(
        f"LONG signals  : {len(b_long)}"
    )

    print(
        f"SHORT signals : {len(b_short)}"
    )

    print(
        f"TOTAL         : {len(strategy_b)}"
    )

    print()
    print(
        f"ALL EVENTS    : {len(events)}"
    )

    # ---------------------------------------------------------------
    # 6. FIRST EVENTS
    # ---------------------------------------------------------------

    print()
    print("FIRST 20 TRIGGER EVENTS")
    print("-" * 110)

    for event in events[:20]:

        print_event(
            event,
            bars,
        )

    # ---------------------------------------------------------------
    # 7. STRUCTURAL VALIDATION
    # ---------------------------------------------------------------

    assert len(events) >= 0

    for event in events:

        assert event.direction.value in {
            "LONG",
            "SHORT",
        }

        assert event.strategy_id.value in {
            "KTMI_LONG_SHORT_SPEED",
            "KTMI_MOMENTUM_ONLY",
        }

        assert event.previous_value is not None
        assert event.current_value is not None
        assert event.trigger_value is not None

    # ---------------------------------------------------------------
    # 8. FINAL
    # ---------------------------------------------------------------

    print()
    print("=" * 110)
    print("REAL FYERS → KTMI → STRATEGY A/B TEST PASSED")
    print("=" * 110)


if __name__ == "__main__":
    main()
    