"""Real FYERS -> KTMI -> Strategy -> Risk -> KAMA -> Backtest V2.

This is the first full strategy integration test.

Pipeline:

    FYERS historical candles
        ↓
    KTMI Universal
        ↓
    KTMI Signals
        ↓
    KTMI Strategy
        ↓
    Risk Engine
        ↓
    Backtest V2
        ↓
    KAMA Exit
        ↓
    Completed Trades

This test deliberately uses the previously validated explicit
TRIX + EMA configuration with all three KTMI modules enabled.

It does NOT modify the KTMI Universal calculation.
It does NOT introduce arbitrary entry thresholds.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from backtest.engine import (
    BacktestEntry,
    run_bar_by_bar_backtest,
)
from backtest.models import BacktestBar

from backtest.costs import CostConfig

from indicators.ktmi.config import (
    KTMIConfig,
    MomentumConfig,
)
from indicators.ktmi.universal import (
    OHLCData,
    calculate_ktmi,
)
from indicators.ktmi.signals import (
    calculate_signals,
)

from indicators.kama_trend_follower.config import (
    DEFAULT_KAMA_CONFIG,
)
from indicators.kama_trend_follower.universal import (
    KAMABar,
    calculate_kama_trend,
)

from strategies.ktmi_strategy import (
    KTMIEntryConfig,
    evaluate_ktmi_entry,
)

from strategies.exits.kama_exit import (
    KAMAExitEvaluator,
)

from risk.risk_engine import (
    RiskMethod,
    RiskRequest,
    calculate_position_size,
)


# ================================================================
# CONFIGURATION
# ================================================================

DB_PATH = Path(
    "data/database/kunal_quant.db"
)

INSTRUMENT_ID = 572021

SYMBOL = "NSE:NIFTY50-INDEX"

BAR_LIMIT = 1000

INITIAL_CAPITAL = 100_000.0

# Controlled test assumption.
# NIFTY index itself is not directly tradable.
# We use quantity 1 here only to validate the pipeline.
LOT_SIZE = 1

# Fixed monetary risk for this integration test.
RISK_PER_TRADE = 1_000.0


# ================================================================
# LOAD FYERS DATA
# ================================================================

def load_bars() -> list[BacktestBar]:
    """Load real FYERS NIFTY 1-minute candles."""

    connection = sqlite3.connect(DB_PATH)

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
              AND source = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (
                INSTRUMENT_ID,
                "1",
                "FYERS_HISTORY",
                BAR_LIMIT,
            ),
        ).fetchall()

    finally:
        connection.close()

    rows.reverse()

    return [
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=int(row[5] or 0),
            open_interest=(
                int(row[6])
                if row[6] is not None
                else None
            ),
        )
        for row in rows
    ]


# ================================================================
# BUILD KTMI CONFIG
# ================================================================

def build_ktmi_config() -> KTMIConfig:
    """Build the previously validated active configuration."""

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

        # The previous validated test did not define
        # trigger values.
        momentum_buy_trigger=None,
        momentum_sell_trigger=None,

        long_buy_trigger=None,
        long_sell_trigger=None,

        short_buy_trigger=None,
        short_sell_trigger=None,
    )


# ================================================================
# KTMI CALCULATION
# ================================================================

def calculate_ktmi_results(
    bars: list[BacktestBar],
    config: KTMIConfig,
):
    """Calculate real KTMI results."""

    ohlc = [
        OHLCData(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]

    return calculate_ktmi(
        bars=ohlc,
        config=config,
    )


# ================================================================
# KAMA
# ================================================================

def calculate_kama_results(
    bars: list[BacktestBar],
):
    """Calculate real KAMA results."""

    kama_bars = [
        KAMABar(
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )
        for bar in bars
    ]

    return calculate_kama_trend(
        bars=kama_bars,
        config=DEFAULT_KAMA_CONFIG,
    )


# ================================================================
# MAIN
# ================================================================

def main() -> None:

    print()
    print("=" * 75)
    print("REAL FYERS -> KTMI -> RISK -> KAMA -> BACKTEST V2")
    print("=" * 75)

    # ============================================================
    # 1. FYERS
    # ============================================================

    bars = load_bars()

    assert len(bars) > 0

    print()
    print("FYERS")
    print("-" * 55)
    print(f"Symbol          : {SYMBOL}")
    print(f"Instrument ID   : {INSTRUMENT_ID}")
    print(f"Bars            : {len(bars)}")

    # ============================================================
    # 2. KTMI
    # ============================================================

    ktmi_config = build_ktmi_config()

    ktmi_results = calculate_ktmi_results(
        bars,
        ktmi_config,
    )

    assert len(ktmi_results) == len(bars)

    print()
    print("KTMI")
    print("-" * 55)
    print(f"Results         : {len(ktmi_results)}")
    print("Calculation     : TRIX")
    print("Smoothing       : EMA")
    print("Speed           : 5")
    print("Signal          : 9")
    print("Momentum        : ENABLED")
    print("Long Momentum   : ENABLED")
    print("Short Momentum  : ENABLED")

    # ============================================================
    # 3. KTMI SIGNALS
    # ============================================================

    signals = calculate_signals(
        results=ktmi_results,
        config=ktmi_config,
    )

    assert len(signals) == len(bars)

    momentum_buy = sum(
        1 for signal in signals
        if signal.momentum_buy
    )

    momentum_sell = sum(
        1 for signal in signals
        if signal.momentum_sell
    )

    long_buy = sum(
        1 for signal in signals
        if signal.long_buy
    )

    long_sell = sum(
        1 for signal in signals
        if signal.long_sell
    )

    short_buy = sum(
        1 for signal in signals
        if signal.short_buy
    )

    short_sell = sum(
        1 for signal in signals
        if signal.short_sell
    )

    bullish_confluence = sum(
        1 for signal in signals
        if signal.bullish_confluence
    )

    bearish_confluence = sum(
        1 for signal in signals
        if signal.bearish_confluence
    )

    print()
    print("KTMI SIGNALS")
    print("-" * 55)
    print(f"Momentum Buy   : {momentum_buy}")
    print(f"Momentum Sell  : {momentum_sell}")
    print(f"Long Buy       : {long_buy}")
    print(f"Long Sell      : {long_sell}")
    print(f"Short Buy      : {short_buy}")
    print(f"Short Sell     : {short_sell}")
    print(f"Bullish Conf.  : {bullish_confluence}")
    print(f"Bearish Conf.  : {bearish_confluence}")

    # ============================================================
    # 4. STRATEGY
    # ============================================================

    strategy_config = KTMIEntryConfig(
        require_bullish_confluence=False,
        require_bearish_confluence=False,
        allow_module_signals=True,
        allow_confluence_signals=True,
    )

    decisions = [
        evaluate_ktmi_entry(
            signals=signal,
            strategy_config=strategy_config,
            ktmi_config=ktmi_config,
        )
        for signal in signals
    ]

    long_entries = sum(
        1 for decision in decisions
        if decision.action.value == "LONG"
    )

    short_entries = sum(
        1 for decision in decisions
        if decision.action.value == "SHORT"
    )

    no_entries = sum(
        1 for decision in decisions
        if decision.action.value == "NO_ENTRY"
    )

    print()
    print("STRATEGY")
    print("-" * 55)
    print(f"LONG decisions  : {long_entries}")
    print(f"SHORT decisions : {short_entries}")
    print(f"NO ENTRY        : {no_entries}")

    # ============================================================
    # 5. KAMA
    # ============================================================

    kama_results = calculate_kama_results(
        bars
    )

    assert len(kama_results) == len(bars)

    valid_kama = sum(
        1
        for result in kama_results
        if result.kama is not None
    )

    print()
    print("KAMA")
    print("-" * 55)
    print(f"Results         : {len(kama_results)}")
    print(f"Valid KAMA      : {valid_kama}")

    # ============================================================
    # 6. CREATE ENTRIES
    # ============================================================

    entries: list[BacktestEntry] = []

    for index, decision in enumerate(decisions):

        action = decision.action.value

        if action not in {"LONG", "SHORT"}:
            continue

        bar = bars[index]

        # --------------------------------------------------------
        # Controlled risk sizing.
        #
        # For this first integration:
        #
        # entry = candle close
        # stop = candle low for LONG
        # stop = candle high for SHORT
        #
        # This is ONLY a pipeline test.
        # It is NOT our final stop-loss model.
        # --------------------------------------------------------

        if action == "LONG":

            stop_loss = bar.low

        else:

            stop_loss = bar.high

        if stop_loss <= 0:
            continue

        if stop_loss == bar.close:
            continue

        risk_request = RiskRequest(
            capital=INITIAL_CAPITAL,
            entry_price=bar.close,
            stop_loss_price=stop_loss,
            lot_size=LOT_SIZE,
            risk_method=RiskMethod.FIXED_AMOUNT,
            fixed_risk_amount=RISK_PER_TRADE,
        )

        risk_result = calculate_position_size(
            risk_request
        )

        if risk_result.quantity <= 0:
            continue

        entries.append(
            BacktestEntry(
                timestamp=bar.timestamp,
                direction=action,
                price=bar.close,
                quantity=risk_result.quantity,
                strategy_id="KTMI_KAMA_V2_TEST",
                config_version="1.0",
            )
        )

    print()
    print("RISK / ENTRIES")
    print("-" * 55)
    print(f"Backtest entries: {len(entries)}")

    # ============================================================
    # 7. RUN BACKTEST
    # ============================================================

    cost_config = CostConfig(
        enabled=True,
        entry_slippage_percent=0.25,
        exit_slippage_percent=0.25,
        entry_fixed_charge=25.0,
        exit_fixed_charge=25.0,
    )

    result = run_bar_by_bar_backtest(
        bars=bars,
        entries=entries,
        exit_evaluator=KAMAExitEvaluator(),
        indicator_data=kama_results,
        initial_capital=INITIAL_CAPITAL,
        cost_config=cost_config,
    )

    # ============================================================
    # 8. REPORT
    # ============================================================

    print()
    print("BACKTEST V2")
    print("-" * 55)
    print(f"Trades          : {result.trade_count}")
    print(f"Initial capital : {result.initial_capital}")
    print(f"Final equity    : {result.final_equity}")
    print(f"Gross P&L       : {result.gross_pnl}")
    print(f"Total costs     : {result.total_cost}")
    print(f"Net P&L         : {result.total_pnl}")
    print(f"Final equity    : {result.final_equity}")
    print(f"Win rate        : {result.win_rate:.2f}%")
    print(f"Winners         : {result.winning_trades}")
    print(f"Losers          : {result.losing_trades}")

    for number, trade in enumerate(
        result.trades[:10],
        start=1,
    ):

        print()
        print(f"TRADE {number}")
        print(f"  Direction     : {trade.direction}")
        print(f"  Entry         : {trade.entry_price}")
        print(f"  Exit          : {trade.exit_price}")
        print(f"  Quantity      : {trade.quantity}")
        print(f"  P&L           : {trade.pnl}")
        print(f"  Exit reason   : {trade.exit_reason}")
        print(f"  Holding bars  : {trade.holding_bars}")

    # ============================================================
    # 9. STRUCTURAL VALIDATION
    # ============================================================

    assert result.final_equity == (
        INITIAL_CAPITAL + result.total_pnl
    )

    for trade in result.trades:

        assert trade.entry_timestamp <= (
            trade.exit_timestamp
        )

        assert trade.entry_price > 0
        assert trade.exit_price > 0
        assert trade.quantity > 0

    print()
    print("=" * 75)
    print("FULL KTMI -> RISK -> KAMA -> BACKTEST V2 PIPELINE PASSED")
    print("=" * 75)


if __name__ == "__main__":
    main()