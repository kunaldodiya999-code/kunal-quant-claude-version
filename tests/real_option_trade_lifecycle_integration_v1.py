"""
KUNAL QUANT — REAL OPTION TRADE LIFECYCLE INTEGRATION V1

Pipeline:

    Real FYERS NIFTY 1m candles
        ↓
    KTMI Universal
        ↓
    Strategy A + Strategy B
        ↓
    Option Contract Resolver V2
        ↓
    Position Lifecycle V1
        ↓
    Next-bar OPEN option entry
        ↓
    Option Trade Lifecycle V1
        ↓
    Stop / 3R partial / KAMA exit
        ↓
    Gross trade P&L

IMPORTANT:
- Does not modify KTMI.
- Does not modify Strategy A/B.
- Does not modify Option Resolver.
- Does not modify Position Lifecycle.
- Does not modify Option Trade Lifecycle.
- This is an integration test, not the final 5-year economic backtest.
- Entry is explicitly NEXT_BAR_OPEN.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.models import BacktestBar
from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
    OptionTradeLifecycle,
    OptionTradeLifecycleConfig,
    OptionTradePosition,
)
from backtest.trade_audit import (
    build_trade_audit,
    calculate_audit_totals,
    find_unbalanced_trades,
)
from backtest.economic_accounting import (
    DEFAULT_ECONOMIC_MODEL,
    calculate_economic_trade,
    calculate_economic_totals,
)
from backtest.performance_attribution import (
    calculate_max_drawdown,
    group_attribution,
)
from backtest.position_lifecycle import (
    ActivePosition,
    PositionLifecycleConfig,
    SignalAction,
    evaluate_signal,
)
from indicators.kama_trend_follower.config import DEFAULT_KAMA_CONFIG
from indicators.kama_trend_follower.universal import (
    KAMABar,
    calculate_kama_trend,
)
from indicators.ktmi.config import KTMIConfig, MomentumConfig
from indicators.ktmi.universal import OHLCData, calculate_ktmi
from strategies.ktmi_trigger_strategy import (
    DEFAULT_KTMI_TRIGGER_CONFIG,
    KTMITriggerEvent,
    evaluate_ktmi_trigger_strategies,
)
from strategies.option_contract_resolver import (
    OptionContractResolver,
    OptionResolverConfig,
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

NIFTY_INSTRUMENT_ID = 572021
NIFTY_SYMBOL = "NSE:NIFTY50-INDEX"

TIMEFRAME = "1"
BAR_COUNT = 1000

OPTION_SOURCE = "FYERS_FNO_HISTORY"
OPTION_TIMEFRAME = "1"

TIMEZONE = ZoneInfo("Asia/Kolkata")

ENTRY_MODE = "NEXT_BAR_OPEN"

INITIAL_CAPITAL = 100_000.0


# =====================================================================
# ACTIVE TRADE WRAPPER
# =====================================================================

@dataclass
class ActiveRealOptionTrade:
    event: KTMITriggerEvent
    contract: object
    position: OptionTradePosition
    signal_timestamp: int
    entry_timestamp: int
    last_processed_timestamp: int


# =====================================================================
# LOAD NIFTY
# =====================================================================

def load_nifty_bars() -> list[BacktestBar]:
    connection = sqlite3.connect(DATABASE_PATH)

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
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (
                NIFTY_INSTRUMENT_ID,
                TIMEFRAME,
                "FYERS_HISTORY",
                BAR_COUNT,
            ),
        ).fetchall()
    finally:
        connection.close()

    if not rows:
        raise RuntimeError("No NIFTY FYERS candles found.")

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


# =====================================================================
# KTMI
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


def calculate_ktmi_results(
    bars: list[BacktestBar],
):
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
        config=build_ktmi_config(),
    )


# =====================================================================
# KAMA
# =====================================================================

def calculate_kama_results(
    bars: list[BacktestBar],
):
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


# =====================================================================
# OPTION CANDLES
# =====================================================================

def load_option_candles(
    instrument_id: int,
    after_timestamp: int,
) -> list[dict]:
    connection = sqlite3.connect(DATABASE_PATH)

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
              AND timestamp > ?
            ORDER BY timestamp ASC
            """,
            (
                instrument_id,
                OPTION_TIMEFRAME,
                OPTION_SOURCE,
                after_timestamp,
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
            "volume": int(row[5] or 0),
            "open_interest": (
                int(row[6])
                if row[6] is not None
                else None
            ),
        }
        for row in rows
    ]


# =====================================================================
# KAMA LOOKUP
# =====================================================================

def build_kama_lookup(
    bars: list[BacktestBar],
    kama_results,
) -> dict[int, float | None]:
    return {
        bar.timestamp: result.kama
        for bar, result in zip(bars, kama_results)
    }


# =====================================================================
# TRIGGER EVENTS
# =====================================================================

def calculate_trigger_events(
    bars: list[BacktestBar],
    ktmi_results,
) -> list[KTMITriggerEvent]:

    events: list[KTMITriggerEvent] = []

    for index in range(1, len(ktmi_results)):
        previous = ktmi_results[index - 1]
        current = ktmi_results[index]

        events.extend(
            evaluate_ktmi_trigger_strategies(
                previous_momentum_speed=previous.momentum.speed,
                current_momentum_speed=current.momentum.speed,
                previous_long_speed=previous.long_momentum.speed,
                current_long_speed=current.long_momentum.speed,
                previous_short_speed=previous.short_momentum.speed,
                current_short_speed=current.short_momentum.speed,
                config=DEFAULT_KTMI_TRIGGER_CONFIG,
                index=index,
                timestamp=bars[index].timestamp,
            )
        )

    return events


# =====================================================================
# OPTION CANDLE PROCESSING
# =====================================================================

def process_trade_until(
    trade: ActiveRealOptionTrade,
    candles: list[dict],
    kama_lookup: dict[int, float | None],
    until_timestamp: int,
) -> list:
    exits = []

    for candle in candles:
        timestamp = candle["timestamp"]

        if timestamp <= trade.last_processed_timestamp:
            continue

        if timestamp > until_timestamp:
            break

        kama_value = kama_lookup.get(timestamp)

        candle_exits = lifecycle.process_candle(
            position=trade.position,
            timestamp=timestamp,
            option_high=candle["high"],
            option_low=candle["low"],
            option_close=candle["close"],
            underlying_close=underlying_close_lookup.get(timestamp),
            kama_value=kama_value,
        )

        trade.last_processed_timestamp = timestamp

        if candle_exits:
            exits.extend(candle_exits)

            if trade.position.closed:
                break

    return exits


# =====================================================================
# MAIN
# =====================================================================

def main() -> None:
    global lifecycle
    global underlying_close_lookup

    print()
    print("=" * 110)
    print("KUNAL QUANT — REAL NIFTY → OPTION TRADE LIFECYCLE V1")
    print("=" * 110)

    # ---------------------------------------------------------------
    # 1. NIFTY
    # ---------------------------------------------------------------

    bars = load_nifty_bars()

    print()
    print("STEP 1 — REAL FYERS NIFTY DATA")
    print("-" * 110)
    print(f"Database       : {DATABASE_PATH}")
    print(f"Symbol         : {NIFTY_SYMBOL}")
    print(f"Instrument ID  : {NIFTY_INSTRUMENT_ID}")
    print(f"Bars           : {len(bars)}")
    print(f"First close    : {bars[0].close}")
    print(f"Last close     : {bars[-1].close}")

    assert len(bars) > 0

    # ---------------------------------------------------------------
    # 2. KTMI
    # ---------------------------------------------------------------

    ktmi_results = calculate_ktmi_results(bars)

    assert len(ktmi_results) == len(bars)

    print()
    print("STEP 2 — KTMI")
    print("-" * 110)
    print("Calculation    : TRIX")
    print("Smoothing      : EMA")
    print("Speed          : 5")
    print("Signal         : 9")
    print(f"KTMI results   : {len(ktmi_results)}")

    # ---------------------------------------------------------------
    # 3. KAMA
    # ---------------------------------------------------------------

    kama_results = calculate_kama_results(bars)

    assert len(kama_results) == len(bars)

    valid_kama = sum(
        1
        for result in kama_results
        if result.kama is not None
    )

    kama_lookup = build_kama_lookup(
        bars,
        kama_results,
    )

    underlying_close_lookup = {
        bar.timestamp: bar.close
        for bar in bars
    }

    print()
    print("STEP 3 — KAMA")
    print("-" * 110)
    print(f"KAMA results   : {len(kama_results)}")
    print(f"Valid KAMA     : {valid_kama}")

    assert valid_kama > 0

    # ---------------------------------------------------------------
    # 4. STRATEGY A/B
    # ---------------------------------------------------------------

    events = calculate_trigger_events(
        bars,
        ktmi_results,
    )

    print()
    print("STEP 4 — STRATEGY A / B")
    print("-" * 110)
    print(f"Strategy events: {len(events)}")

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

    print(f"Strategy A     : {len(strategy_a)}")
    print(f"Strategy B     : {len(strategy_b)}")

    assert len(events) > 0

    # ---------------------------------------------------------------
    # 5. RESOLVER
    # ---------------------------------------------------------------

    connection = sqlite3.connect(DATABASE_PATH)

    try:
        resolver = OptionContractResolver(
            database_path=DATABASE_PATH,
            config=OptionResolverConfig(
                strike_step=50
            ),
        )

        # -----------------------------------------------------------
        # 6. LIFECYCLE CONFIG
        # -----------------------------------------------------------

        position_config = PositionLifecycleConfig(
            one_position_per_strategy=True,
            allow_same_strategy_reentry=False,
            allow_different_strategy_positions=True,
            allow_same_strategy_reversal=False,
        )

        lifecycle_config = OptionTradeLifecycleConfig(
            allocation=15_000.0,
            lot_size=65,
            stop_loss_pct=0.20,
            target_rr=3.0,
            partial_exit_fraction=0.50,
            target_enabled=True,
        )

        lifecycle = OptionTradeLifecycle(
            config=lifecycle_config,
        )

        active_positions: list[ActivePosition] = []
        active_trades: list[ActiveRealOptionTrade] = []

        all_trade_records: list[dict] = []

        resolved_count = 0
        missing_contracts = 0
        option_candles_found = 0
        next_bar_entries = 0
        next_bar_missing = 0
        accepted_entries = 0
        ignored_signals = 0

        # -----------------------------------------------------------
        # OPTION CANDLE CACHE
        # -----------------------------------------------------------

        option_cache: dict[int, list[dict]] = {}

        def get_option_candles(
            instrument_id: int,
            after_timestamp: int,
        ) -> list[dict]:

            key = instrument_id

            if key not in option_cache:
                option_cache[key] = load_option_candles(
                    instrument_id=instrument_id,
                    after_timestamp=after_timestamp,
                )

            return option_cache[key]

        # -----------------------------------------------------------
        # PROCESS EVENTS CHRONOLOGICALLY
        # -----------------------------------------------------------

        for event in events:

            signal_timestamp = event.timestamp

            # -------------------------------------------------------
            # First process already-open trades through the signal
            # candle. This allows a position to close before a new
            # signal is evaluated.
            # -------------------------------------------------------

            still_active: list[ActiveRealOptionTrade] = []

            for trade in active_trades:

                candles = get_option_candles(
                    trade.contract.instrument_id,
                    trade.signal_timestamp,
                )

                exits = []

                for candle in candles:
                    if candle["timestamp"] <= trade.last_processed_timestamp:
                        continue

                    if candle["timestamp"] > signal_timestamp:
                        break

                    kama_value = kama_lookup.get(
                        candle["timestamp"]
                    )

                    underlying_close = (
                        underlying_close_lookup.get(
                            candle["timestamp"]
                        )
                    )

                    if underlying_close is None:
                        continue

                    candle_exits = lifecycle.process_candle(
                        position=trade.position,
                        timestamp=candle["timestamp"],
                        option_high=candle["high"],
                        option_low=candle["low"],
                        option_close=candle["close"],
                        underlying_close=underlying_close,
                        kama_value=kama_value,
                    )

                    trade.last_processed_timestamp = (
                        candle["timestamp"]
                    )

                    if candle_exits:
                        exits.extend(candle_exits)

                        for exit_event in candle_exits:
                            all_trade_records.append(
                                {
                                    "trade": trade,
                                    "exit": exit_event,
                                }
                            )

                    if trade.position.closed:
                        break

                if not trade.position.closed:
                    still_active.append(trade)

                else:
                    active_positions = [
                        p
                        for p in active_positions
                        if not (
                            p.strategy_id
                            == trade.position.strategy_id
                            and p.symbol
                            == trade.position.symbol
                        )
                    ]

            active_trades = still_active

            # -------------------------------------------------------
            # Resolve option contract
            # -------------------------------------------------------

            signal_date = datetime.fromtimestamp(
                signal_timestamp,
                tz=TIMEZONE,
            ).date()

            direction = event.direction.value
            strategy_id = event.strategy_id.value

            try:
                contract = resolver.resolve(
                    underlying_price=bars[event.index].close,
                    entry_date=signal_date,
                    direction=direction,
                )
            except LookupError:
                missing_contracts += 1
                continue

            resolved_count += 1

            # -------------------------------------------------------
            # Position lifecycle
            # -------------------------------------------------------

            decision = evaluate_signal(
                strategy_id=strategy_id,
                direction=direction,
                symbol=contract.symbol,
                active_positions=active_positions,
                config=position_config,
            )

            if decision.action != SignalAction.ENTER:
                ignored_signals += 1
                continue

            # -------------------------------------------------------
            # Next-bar OPEN entry
            # -------------------------------------------------------

            option_candles = get_option_candles(
                contract.instrument_id,
                signal_timestamp,
            )

            option_candles_found += len(option_candles)

            next_candle = next(
                (
                    candle
                    for candle in option_candles
                    if candle["timestamp"] > signal_timestamp
                ),
                None,
            )

            if next_candle is None:
                next_bar_missing += 1
                continue

            next_bar_entries += 1

            trade_direction = (
                OptionTradeDirection.LONG
                if direction == "LONG"
                else OptionTradeDirection.SHORT
            )

            position = lifecycle.create_position(
                strategy_id=strategy_id,
                direction=trade_direction,
                symbol=contract.symbol,
                entry_price=next_candle["open"],
            )

            active_positions.append(
                ActivePosition(
                    strategy_id=strategy_id,
                    direction=direction,
                    symbol=contract.symbol,
                )
            )

            active_trades.append(
                ActiveRealOptionTrade(
                    event=event,
                    contract=contract,
                    position=position,
                    signal_timestamp=signal_timestamp,
                    entry_timestamp=next_candle["timestamp"],
                    last_processed_timestamp=next_candle["timestamp"],
                )
            )

            accepted_entries += 1

        # -----------------------------------------------------------
        # END OF DATA
        # -----------------------------------------------------------

        for trade in active_trades:

            candles = get_option_candles(
                trade.contract.instrument_id,
                trade.last_processed_timestamp,
            )

            final_candle = None

            for candle in candles:
                if candle["timestamp"] > trade.last_processed_timestamp:
                    final_candle = candle

            if final_candle is None:
                continue

            final_price = final_candle["close"]

            quantity = trade.position.remaining_quantity
            lots = trade.position.remaining_lots

            if quantity <= 0:
                continue

            pnl = lifecycle.calculate_pnl(
                direction=trade.position.direction,
                entry_price=trade.position.entry_price,
                exit_price=final_price,
                quantity=quantity,
            )

            trade.position.gross_pnl += pnl
            trade.position.remaining_quantity = 0
            trade.position.remaining_lots = 0
            trade.position.closed = True

            from backtest.option_trade_lifecycle import OptionTradeExit

            exit_event = OptionTradeExit(
                timestamp=final_candle["timestamp"],
                reason=OptionExitReason.END_OF_DATA,
                price=final_price,
                quantity=quantity,
                lots=lots,
                pnl=pnl,
                remaining_quantity=0,
                remaining_lots=0,
            )

            all_trade_records.append(
                {
                    "trade": trade,
                    "exit": exit_event,
                }
            )

    finally:
        connection.close()

    # =================================================================
    # REPORT
    # =================================================================

    target_exits = sum(
        1
        for record in all_trade_records
        if record["exit"].reason
        == OptionExitReason.TARGET_3R
    )

    stop_exits = sum(
        1
        for record in all_trade_records
        if record["exit"].reason
        == OptionExitReason.STOP_LOSS
    )

    kama_exits = sum(
        1
        for record in all_trade_records
        if record["exit"].reason
        == OptionExitReason.KAMA_EXIT
    )

    eod_exits = sum(
        1
        for record in all_trade_records
        if record["exit"].reason
        == OptionExitReason.END_OF_DATA
    )

    # One trade can have a partial target plus a final KAMA/stop exit.
    completed_trade_groups = {}

    for record in all_trade_records:
        trade = record["trade"]
        key = id(trade)
        completed_trade_groups.setdefault(
            key,
            {
                "trade": trade,
                "exits": [],
            },
        )
        completed_trade_groups[key]["exits"].append(
            record["exit"]
        )

    completed_trades = list(
        completed_trade_groups.values()
    )

    total_pnl = sum(
        trade["trade"].position.gross_pnl
        for trade in completed_trades
    )

    # ---------------------------------------------------------------
    # TRADE ACCOUNTING AUDIT
    # ---------------------------------------------------------------

    audit_summaries = build_trade_audit(completed_trades)
    audit_totals = calculate_audit_totals(audit_summaries)
    unbalanced_trades = find_unbalanced_trades(audit_summaries)

    print()
    print("TRADE ACCOUNTING AUDIT")
    print("-" * 110)
    print(
        f"Quantity-balanced : "
        f"{audit_totals.balanced_quantity}/"
        f"{audit_totals.trades}"
    )
    print(
        f"P&L-balanced      : "
        f"{audit_totals.balanced_pnl}/"
        f"{audit_totals.trades}"
    )
    print(f"Exit events       : {audit_totals.total_exit_events}")
    print(f"Partial exits     : {audit_totals.partial_exit_events}")
    print(f"Audited gross P&L : ₹{audit_totals.gross_pnl:,.2f}")

    assert not unbalanced_trades, (
        "Trade accounting audit failed: "
        f"{len(unbalanced_trades)} unbalanced trades."
    )
    assert abs(audit_totals.gross_pnl - total_pnl) < 1e-9, (
        "Audit gross P&L does not match integration gross P&L."
    )

    # ---------------------------------------------------------------
    # ECONOMIC ACCOUNTING
    # ---------------------------------------------------------------

    economic_summaries = [
        calculate_economic_trade(
            summary,
            model=DEFAULT_ECONOMIC_MODEL,
        )
        for summary in audit_summaries
    ]
    economic_totals = calculate_economic_totals(
        economic_summaries
    )

    print()
    print("ECONOMIC ACCOUNTING")
    print("-" * 110)
    print(f"Gross P&L         : ₹{economic_totals.gross_pnl:,.2f}")
    print(f"Slippage cost     : ₹{economic_totals.slippage_cost:,.2f}")
    print(f"Fixed charges     : ₹{economic_totals.fixed_charges:,.2f}")
    print(f"Total costs       : ₹{economic_totals.total_cost:,.2f}")
    print(f"Net P&L           : ₹{economic_totals.net_pnl:,.2f}")

    assert economic_totals.trades == audit_totals.trades
    assert abs(
        economic_totals.gross_pnl - audit_totals.gross_pnl
    ) < 1e-9
    assert abs(
        economic_totals.net_pnl
        - (
            economic_totals.gross_pnl
            - economic_totals.total_cost
        )
    ) < 1e-9

    # ---------------------------------------------------------------
    # PERFORMANCE ATTRIBUTION
    # ---------------------------------------------------------------

    attribution = group_attribution(
        economic_rows=economic_summaries,
        audit_rows=audit_summaries,
    )

    drawdown = calculate_max_drawdown(
        starting_capital=INITIAL_CAPITAL,
        economic_rows=economic_summaries,
    )

    print()
    print("PERFORMANCE ATTRIBUTION")
    print("-" * 110)

    for group_name, title in (
        ("strategy", "BY STRATEGY"),
        ("direction", "BY DIRECTION"),
        ("final_exit_reason", "BY FINAL EXIT REASON"),
    ):
        print()
        print(title)
        print(
            f"{'Key':24s} {'Trades':>6s} {'Gross':>12s} "
            f"{'Costs':>12s} {'Net':>12s} {'Win%':>8s} "
            f"{'PF':>8s}"
        )
        for row in attribution[group_name]:
            profit_factor = (
                f"{row.profit_factor:.2f}"
                if row.profit_factor is not None
                else "N/A"
            )
            print(
                f"{row.key:24s} "
                f"{row.trades:6d} "
                f"₹{row.gross_pnl:10,.2f} "
                f"₹{row.total_cost:10,.2f} "
                f"₹{row.net_pnl:10,.2f} "
                f"{row.win_rate_pct:7.2f}% "
                f"{profit_factor:>8s}"
            )

    print()
    print("DRAWDOWN")
    print("-" * 110)
    print(f"Starting capital : ₹{INITIAL_CAPITAL:,.2f}")
    print(f"Peak equity      : ₹{drawdown.peak_equity:,.2f}")
    print(f"Max drawdown     : ₹{drawdown.max_drawdown:,.2f}")
    print(f"Max drawdown %   : {drawdown.max_drawdown_pct:.2f}%")
    print(f"DD trough equity : ₹{drawdown.trough_equity:,.2f}")

    print()
    print("STEP 5 — REAL OPTION LIFECYCLE")
    print("-" * 110)
    print(f"Contracts resolved : {resolved_count}")
    print(f"Missing contracts  : {missing_contracts}")
    print(f"Option candles     : {option_candles_found}")
    print(f"Next-bar entries   : {next_bar_entries}")
    print(f"Next-bar missing   : {next_bar_missing}")
    print(f"Accepted entries   : {accepted_entries}")
    print(f"Ignored signals    : {ignored_signals}")

    print()
    print("EXIT EVENTS")
    print("-" * 110)
    print(f"3R partial exits   : {target_exits}")
    print(f"Stop exits         : {stop_exits}")
    print(f"KAMA exits         : {kama_exits}")
    print(f"End-of-data exits  : {eod_exits}")

    print()
    print("TRADE SUMMARY")
    print("-" * 110)
    print(f"Completed positions: {len(completed_trades)}")
    print(f"Gross P&L          : ₹{total_pnl:,.2f}")

    print()
    print("FIRST 20 TRADE EXIT EVENTS")
    print("-" * 110)

    for number, record in enumerate(
        all_trade_records[:20],
        start=1,
    ):
        trade = record["trade"]
        exit_event = record["exit"]

        print(
            f"{number:02d} | "
            f"{trade.position.strategy_id:24s} | "
            f"{trade.position.direction.value:5s} | "
            f"{trade.contract.symbol:30s} | "
            f"Entry {trade.position.entry_price:8.2f} | "
            f"Exit {exit_event.price:8.2f} | "
            f"Qty {exit_event.quantity:3d} | "
            f"P&L {exit_event.pnl:9.2f} | "
            f"{exit_event.reason.value}"
        )

    # =================================================================
    # VALIDATION
    # =================================================================

    assert len(ktmi_results) == len(bars)
    assert len(kama_results) == len(bars)
    assert len(events) > 0
    assert resolved_count > 0
    assert next_bar_entries > 0

    print()
    print("=" * 110)
    print("REAL NIFTY → KTMI → STRATEGY A/B → OPTION RESOLVER")
    print("→ POSITION LIFECYCLE → NEXT-BAR OPEN → OPTION TRADE LIFECYCLE")
    print("INTEGRATION TEST PASSED")
    print("=" * 110)


if __name__ == "__main__":
    main()
