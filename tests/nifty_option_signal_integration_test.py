"""
KUNAL QUANT
REAL NIFTY -> OPTION CANDLE INTEGRATION TEST V1

Uses the EXACT already-validated KTMI pipeline.

Pipeline:

FYERS NIFTY
    ↓
Existing KTMI Universal
    ↓
Existing Strategy A/B
    ↓
Option Contract Resolver V2
    ↓
Actual FYERS option candles
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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

from strategies.option_contract_resolver import (
    OptionContractResolver,
)
from backtest.position_lifecycle import (
    ActivePosition,
    PositionLifecycleConfig,
    SignalAction,
    evaluate_signal,
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

TIMEZONE = ZoneInfo("Asia/Kolkata")


# =====================================================================
# LOAD NIFTY
# =====================================================================

def load_bars() -> list[BacktestBar]:

    if not DATABASE_PATH.exists():

        raise FileNotFoundError(
            f"Database not found:\n{DATABASE_PATH}"
        )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

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
# EXISTING KTMI CONFIGURATION
# =====================================================================

def build_ktmi_config() -> KTMIConfig:

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
# EXISTING KTMI CALCULATION
# =====================================================================

def calculate_ktmi_results(
    bars: list[BacktestBar],
):

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
# OPTION CANDLES
# =====================================================================

def load_option_candles(
    instrument_id: int,
    timestamp: int,
) -> list[dict]:

    # One hour around the signal.
    start_timestamp = timestamp - 3600
    end_timestamp = timestamp + 3600

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    try:

        rows = connection.execute(
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
              AND source = 'FYERS_FNO_HISTORY'
              AND timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
            """,
            (
                instrument_id,
                TIMEFRAME,
                start_timestamp,
                end_timestamp,
            ),
        ).fetchall()

    finally:

        connection.close()

    return [

        {
            "timestamp": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": row[5],
            "open_interest": row[6],
        }

        for row in rows
    ]


# =====================================================================
# MAIN
# =====================================================================

def main():

    print()
    print("=" * 110)

    print(
        "KUNAL QUANT — REAL NIFTY → OPTION CANDLE INTEGRATION V1"
    )

    print("=" * 110)

    # -----------------------------------------------------------------
    # 1. NIFTY DATA
    # -----------------------------------------------------------------

    bars = load_bars()

    print()
    print("FYERS NIFTY DATA")
    print("-" * 110)

    print(
        f"Database       : {DATABASE_PATH}"
    )

    print(
        f"Symbol         : {SYMBOL}"
    )

    print(
        f"Instrument ID  : {INSTRUMENT_ID}"
    )

    print(
        f"Timeframe      : {TIMEFRAME}"
    )

    print(
        f"Bars           : {len(bars)}"
    )

    print(
        f"First          : {bars[0].timestamp}"
        f" | Close={bars[0].close}"
    )

    print(
        f"Last           : {bars[-1].timestamp}"
        f" | Close={bars[-1].close}"
    )

    # -----------------------------------------------------------------
    # 2. KTMI
    # -----------------------------------------------------------------

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

    # -----------------------------------------------------------------
    # 3. STRATEGY A/B
    # -----------------------------------------------------------------

    events: list[KTMITriggerEvent] = []

    for index in range(
        1,
        len(ktmi_results),
    ):

        previous = ktmi_results[
            index - 1
        ]

        current = ktmi_results[
            index
        ]

        current_events = (
            evaluate_ktmi_trigger_strategies(

                previous_momentum_speed=(
                    previous.momentum.speed
                ),

                current_momentum_speed=(
                    current.momentum.speed
                ),

                previous_long_speed=(
                    previous.long_momentum.speed
                ),

                current_long_speed=(
                    current.long_momentum.speed
                ),

                previous_short_speed=(
                    previous.short_momentum.speed
                ),

                current_short_speed=(
                    current.short_momentum.speed
                ),

                config=(
                    DEFAULT_KTMI_TRIGGER_CONFIG
                ),

                index=index,

                timestamp=(
                    bars[index].timestamp
                ),
            )
        )

        events.extend(
            current_events
        )

    print()
    print("STRATEGY EVENTS")
    print("-" * 110)

    print(
        f"Total events   : {len(events)}"
    )

    if not events:

        raise RuntimeError(
            "No KTMI trigger events found."
        )

    # -----------------------------------------------------------------
    # 4. OPTION RESOLVER
    # -----------------------------------------------------------------

    resolver = OptionContractResolver()

    resolved = 0
    candles_found = 0
    missing = 0

    print()
    print("OPTION CONTRACT → REAL CANDLES")
    print("-" * 110)

    print(
        "Timestamp | Strategy | Direction | "
        "NIFTY | Strike | Type | Symbol | "
        "Option Candle"
    )

        # -----------------------------------------------------------------
    # 5. APPLY POSITION LIFECYCLE + MAP ACCEPTED SIGNALS TO OPTIONS
    # -----------------------------------------------------------------

    lifecycle_config = PositionLifecycleConfig(
        one_position_per_strategy=True,
        allow_same_strategy_reentry=False,
        allow_different_strategy_positions=True,
        allow_same_strategy_reversal=False,
    )

    active_positions = []

    accepted = []
    ignored = []

    resolved = 0
    missing = 0
    candles_found = 0
    next_bar_found = 0
    next_bar_missing = 0

    # -----------------------------------------------------------------
    # PROCESS EVERY REAL KTMI EVENT
    # -----------------------------------------------------------------

    for event in events:

        # -------------------------------------------------------------
        # 5A. UNDERLYING SIGNAL INFORMATION
        # -------------------------------------------------------------

        index = event.index

        bar = bars[index]

        timestamp = bar.timestamp

        entry_date = datetime.fromtimestamp(
            timestamp,
            tz=TIMEZONE,
        ).date()

        underlying_price = bar.close

        strategy_id = event.strategy_id.value

        direction = event.direction.value

        # -------------------------------------------------------------
        # 5B. RESOLVE ATM OPTION
        # -------------------------------------------------------------

        try:

            contract = resolver.resolve(
                underlying_price=underlying_price,
                entry_date=entry_date,
                direction=direction,
            )

        except LookupError:

            missing += 1

            continue

        resolved += 1

        # -------------------------------------------------------------
        # 5C. POSITION LIFECYCLE DECISION
        #
        # IMPORTANT:
        # The lifecycle now receives the ACTUAL option symbol.
        # -------------------------------------------------------------

        decision = evaluate_signal(
            strategy_id=strategy_id,
            direction=direction,
            symbol=contract.symbol,
            active_positions=active_positions,
            config=lifecycle_config,
        )

        if decision.action != SignalAction.ENTER:

            ignored.append(
                (event, decision)
            )

            continue

        # -------------------------------------------------------------
        # 5D. LOAD REAL OPTION CANDLES
        # -------------------------------------------------------------

        option_candles = load_option_candles(
            instrument_id=contract.instrument_id,
            timestamp=timestamp,
        )

        if not option_candles:

            next_bar_missing += 1

            continue

        candles_found += len(
            option_candles
        )

        # -------------------------------------------------------------
        # 5E. FIND NEXT OPTION CANDLE
        #
        # The KTMI signal is generated when the NIFTY candle closes.
        # Therefore the option entry must be AFTER the signal candle.
        # This prevents same-candle lookahead.
        # -------------------------------------------------------------

        next_candle = None

        for candle in option_candles:

            candle_timestamp = candle["timestamp"]

            if candle_timestamp > timestamp:

                next_candle = candle

                break

        if next_candle is None:

            next_bar_missing += 1

            continue

        next_bar_found += 1

        # -------------------------------------------------------------
        # 5F. REGISTER ACTIVE POSITION
        # -------------------------------------------------------------

        active_positions.append(
            ActivePosition(
                strategy_id=strategy_id,
                direction=direction,
                symbol=contract.symbol,
            )
        )

        # -------------------------------------------------------------
        # 5G. STORE ACCEPTED POSITION
        # -------------------------------------------------------------

        accepted.append(
            {
                "event": event,
                "decision": decision,
                "contract": contract,
                "signal_timestamp": timestamp,
                "entry_timestamp": next_candle[
                    "timestamp"
                ],
                "underlying_price": underlying_price,
                "entry_price": next_candle[
                    "close"
                ],
            }
        )

        # -------------------------------------------------------------
        # 5H. DISPLAY FIRST 15 ACCEPTED POSITIONS
        # -------------------------------------------------------------

        if len(accepted) <= 15:

            signal_time = datetime.fromtimestamp(
                timestamp,
                tz=TIMEZONE,
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            entry_time = datetime.fromtimestamp(
                next_candle["timestamp"],
                tz=TIMEZONE,
            ).strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            print(
                f"{len(accepted):02d} | "
                f"{signal_time} | "
                f"{entry_time} | "
                f"{strategy_id:<24} | "
                f"{direction:<5} | "
                f"NIFTY {underlying_price:>9.2f} | "
                f"{contract.symbol:<30} | "
                f"ENTRY {next_candle['close']}"
            )
    # -----------------------------------------------------------------
    # 6. RESULTS
    # -----------------------------------------------------------------

    strategy_a_events = [
        event
        for event in events
        if event.strategy_id.value
        == "KTMI_LONG_SHORT_SPEED"
    ]

    strategy_b_events = [
        event
        for event in events
        if event.strategy_id.value
        == "KTMI_MOMENTUM_ONLY"
    ]

    strategy_a_entries = [
        item
        for item in accepted
        if item["event"].strategy_id.value
        == "KTMI_LONG_SHORT_SPEED"
    ]

    strategy_b_entries = [
        item
        for item in accepted
        if item["event"].strategy_id.value
        == "KTMI_MOMENTUM_ONLY"
    ]

    long_entries = [
        item
        for item in accepted
        if item["event"].direction.value
        == "LONG"
    ]

    short_entries = [
        item
        for item in accepted
        if item["event"].direction.value
        == "SHORT"
    ]

    print()
    print("=" * 110)

    print(
        "POSITION LIFECYCLE INTEGRATION RESULTS"
    )

    print("=" * 110)

    print(
        f"KTMI events              : {len(events)}"
    )

    print(
        f"ENTER                    : {len(accepted)}"
    )

    print(
        f"IGNORE                   : {len(ignored)}"
    )

    print()
    print("STRATEGY A")

    print(
        f"  Events                 : "
        f"{len(strategy_a_events)}"
    )

    print(
        f"  Entries                : "
        f"{len(strategy_a_entries)}"
    )

    print(
        f"  Ignored                : "
        f"{len(strategy_a_events) - len(strategy_a_entries)}"
    )

    print()
    print("STRATEGY B")

    print(
        f"  Events                 : "
        f"{len(strategy_b_events)}"
    )

    print(
        f"  Entries                : "
        f"{len(strategy_b_entries)}"
    )

    print(
        f"  Ignored                : "
        f"{len(strategy_b_events) - len(strategy_b_entries)}"
    )

    print()
    print("DIRECTION")

    print(
        f"  LONG entries           : "
        f"{len(long_entries)}"
    )

    print(
        f"  SHORT entries          : "
        f"{len(short_entries)}"
    )

    print()
    print("OPTION RESOLUTION")

    print(
        f"  Contracts resolved     : "
        f"{resolved}"
    )

    print(
        f"  Missing                : "
        f"{missing}"
    )

    print(
        f"  Option candles found  : "
        f"{candles_found}"
    )

    print()
    print("NEXT-BAR ENTRY")

    print(
        f"  Next-bar entries found : "
        f"{next_bar_found}"
    )

    print(
        f"  Next-bar missing       : "
        f"{next_bar_missing}"
    )

    # -----------------------------------------------------------------
    # 7. VALIDATION
    # -----------------------------------------------------------------

    assert len(events) > 0

    assert len(accepted) > 0

    assert len(ignored) > 0

    assert resolved > 0

    assert candles_found > 0

    assert next_bar_found > 0

    # Every accepted position must have a genuinely later
    # option candle than the NIFTY signal candle.

    for item in accepted:

        assert (
            item["entry_timestamp"]
            > item["signal_timestamp"]
        )

    print()
    print("=" * 110)

    print(
        "REAL NIFTY → KTMI → STRATEGY A/B → "
        "POSITION LIFECYCLE → OPTION RESOLVER → "
        "NEXT-BAR OPTION ENTRY TEST PASSED"
    )

    print("=" * 110)


if __name__ == "__main__":

    main()