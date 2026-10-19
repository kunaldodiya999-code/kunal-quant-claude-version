"""
KTMI Universal validation test.

Uses real NIFTY OHLC data from the Kunal Quant database.

Database relationship:
    instruments.id
        ↓
    candles.instrument_id
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from indicators.ktmi.config import KTMIConfig, MomentumConfig
from indicators.ktmi.signals import calculate_signals
from indicators.ktmi.universal import OHLCData, calculate_ktmi


DATABASE_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "database"
    / "kunal_quant.db"
)

NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"


def find_instrument_id(
    connection: sqlite3.Connection,
    symbol: str,
) -> int:
    """Find the instrument ID for a symbol."""

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
    limit: int = 1000,
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


def main() -> None:
    print("=" * 70)
    print("KTMI UNIVERSAL VALIDATION")
    print("=" * 70)

    print()
    print(f"Database : {DATABASE_PATH}")
    print(f"Symbol   : {NIFTY_SYMBOL}")

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

        print(f"Instrument ID: {instrument_id}")

        bars = load_nifty_data(
            connection,
            instrument_id,
        )

    finally:
        connection.close()

    print(f"Bars loaded: {len(bars)}")

    if not bars:
        raise RuntimeError(
            "No 1-minute NIFTY candles found."
        )

    # ------------------------------------------------------------------
    # KTMI CONFIGURATION
    # ------------------------------------------------------------------

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
        momentum_buy_trigger=1.0,
        momentum_sell_trigger=-1.0,
        long_buy_trigger=1.0,
        long_sell_trigger=-1.0,
        short_buy_trigger=1.0,
        short_sell_trigger=-1.0,
    )

    # ------------------------------------------------------------------
    # KTMI CALCULATION
    # ------------------------------------------------------------------

    results = calculate_ktmi(
        bars,
        config,
    )

    signals = calculate_signals(
        results,
        config,
    )

    print()
    print("-" * 70)
    print("CALCULATION RESULTS")
    print("-" * 70)

    print(f"OHLC bars       : {len(bars)}")
    print(f"KTMI results    : {len(results)}")
    print(f"Signal results  : {len(signals)}")

    assert len(results) == len(bars)
    assert len(signals) == len(bars)

    # ------------------------------------------------------------------
    # FIND LAST FULLY CALCULATED BAR
    # ------------------------------------------------------------------

    valid_index = None

    for index in range(len(results) - 1, -1, -1):

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
            "No fully populated KTMI result found."
        )

    result = results[valid_index]
    signal = signals[valid_index]
    bar = bars[valid_index]

    # ------------------------------------------------------------------
    # OUTPUT
    # ------------------------------------------------------------------

    print()
    print(f"Last valid bar index: {valid_index}")

    print()
    print("OHLC")
    print(f"  Open : {bar.open}")
    print(f"  High : {bar.high}")
    print(f"  Low  : {bar.low}")
    print(f"  Close: {bar.close}")

    print()
    print("MOMENTUM")
    print(f"  Speed : {result.momentum.speed}")
    print(f"  Signal: {result.momentum.signal}")

    print()
    print("LONG MOMENTUM")
    print(f"  Speed : {result.long_momentum.speed}")
    print(f"  Signal: {result.long_momentum.signal}")

    print()
    print("SHORT MOMENTUM")
    print(f"  Speed : {result.short_momentum.speed}")
    print(f"  Signal: {result.short_momentum.signal}")

    print()
    print("SIGNALS")
    print(f"  Momentum Buy : {signal.momentum_buy}")
    print(f"  Momentum Sell: {signal.momentum_sell}")
    print(f"  Long Buy     : {signal.long_buy}")
    print(f"  Long Sell    : {signal.long_sell}")
    print(f"  Short Buy    : {signal.short_buy}")
    print(f"  Short Sell   : {signal.short_sell}")

    print()
    print("CONFLUENCE")
    print(f"  Bullish: {signal.bullish_confluence}")
    print(f"  Bearish: {signal.bearish_confluence}")

    # ------------------------------------------------------------------
    # BASIC VALIDATION
    # ------------------------------------------------------------------

    print()
    print("-" * 70)
    print("BASIC VALIDATION")
    print("-" * 70)

    assert len(results) == len(bars)
    print("PASS: KTMI result count matches OHLC count")

    assert len(signals) == len(bars)
    print("PASS: signal count matches OHLC count")

    assert result.momentum.speed is not None
    assert result.momentum.signal is not None
    print("PASS: Momentum values populated")

    assert result.long_momentum.speed is not None
    assert result.long_momentum.signal is not None
    print("PASS: Long Momentum values populated")

    assert result.short_momentum.speed is not None
    assert result.short_momentum.signal is not None
    print("PASS: Short Momentum values populated")

    print()
    print("=" * 70)
    print("KTMI UNIVERSAL VALIDATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()