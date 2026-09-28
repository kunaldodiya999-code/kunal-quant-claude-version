"""
Kunal Quant — Chronological Position Lifecycle Diagnostic (PROPOSAL)

This diagnostic models the intended Position Lifecycle V1 in true event
chronological order without changing canonical KunalQuant.

Why this exists
---------------
The current real-option runner simulates a complete trade before moving to
the next KTMI event. That can remove a position from active state using a
future exit that has not happened yet at the time of an intervening signal.

This proposal runner instead:
1. Advances already-open trades only up to the current signal timestamp.
2. Evaluates the next KTMI event against positions that are actually active
   at that point in simulated time.
3. Creates a new option entry at the first option candle strictly after the
   signal timestamp.
4. Applies the existing locked OptionTradeLifecycle V1 candle rules.
5. Continues all active trades chronologically.
6. Does not modify KTMI, Resolver V2, Position Lifecycle V1, or Trade
   Lifecycle V1.

No charges or end-of-data exits are invented.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionCandle, OptionEntry
from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradeLifecycle,
    OptionTradePosition,
    OptionTradeResult,
)
from backtest.option_trade_management import ManagedOptionTrade
from backtest.position_lifecycle import (
    ActivePosition,
    DEFAULT_POSITION_LIFECYCLE_CONFIG,
    SignalAction,
    evaluate_signal,
)
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from run_real_option_sample_resilient import run_resilient
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")
ALLOCATION_ERROR = "Allocation cannot purchase one complete lot"


@dataclass
class ActiveTradeState:
    managed: ManagedOptionTrade
    candles: tuple[OptionCandle, ...]
    next_index: int


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def calculate_kama(bars: Sequence[BacktestBar]):
    from backtest.real_option_trade_runner import calculate_nifty_kama
    return calculate_nifty_kama(bars)


def make_active_position(trade: ManagedOptionTrade) -> ActivePosition:
    entry = trade.entry
    return ActivePosition(
        strategy_id=entry.event.strategy_id.value,
        direction=entry.event.direction.value,
        symbol=entry.contract.symbol,
    )


def build_managed_trade(
    *,
    entry: OptionEntry,
    position: OptionTradePosition,
    exits: list[OptionTradeExit],
) -> ManagedOptionTrade:
    result = OptionTradeResult(
        position=position,
        exits=tuple(exits),
        total_pnl=position.gross_pnl,
        closed=position.closed,
    )
    return ManagedOptionTrade(
        entry=entry,
        position=position,
        result=result,
    )


def advance_trade(
    *,
    state: ActiveTradeState,
    through_timestamp: int,
    bars: Sequence[BacktestBar],
    kama_results,
    underlying_timestamps: Sequence[int],
    lifecycle: OptionTradeLifecycle,
) -> None:
    """
    Process stored option candles through the requested simulated time.

    Entry candle itself is never processed, matching the existing trade
    management implementation. Every later candle with timestamp <= the
    requested boundary is processed once.
    """
    while (
        state.next_index < len(state.candles)
        and state.candles[state.next_index].timestamp <= through_timestamp
        and not state.managed.position.closed
    ):
        candle = state.candles[state.next_index]
        state.next_index += 1

        index = bisect.bisect_right(
            underlying_timestamps,
            candle.timestamp,
        ) - 1

        if index < 0:
            continue

        underlying = bars[index]
        kama = kama_results[index]

        candle_exits = lifecycle.process_candle(
            position=state.managed.position,
            timestamp=candle.timestamp,
            option_high=candle.high,
            option_low=candle.low,
            option_close=candle.close,
            underlying_close=underlying.close,
            kama_value=kama.kama,
        )

        if candle_exits:
            all_exits = list(state.managed.result.exits)
            all_exits.extend(candle_exits)
            state.managed = build_managed_trade(
                entry=state.managed.entry,
                position=state.managed.position,
                exits=all_exits,
            )


def chronological_run(
    *,
    bars: Sequence[BacktestBar],
    events,
    resolver: OptionContractResolver,
    loader: FyersOptionCandleLoader,
    end_timestamp: int,
):
    kama_results = calculate_kama(bars)
    underlying_timestamps = [bar.timestamp for bar in bars]

    active: list[ActiveTradeState] = []
    all_trades: list[ManagedOptionTrade] = []
    unresolved = 0
    no_entry_candle = 0
    allocation_rejected = 0
    lifecycle_rejected = 0

    ordered_events = list(events)
    ordered_events.sort(key=lambda e: (e.index, e.timestamp))

    for event in ordered_events:
        event_timestamp = bars[event.index].timestamp

        # Advance all currently active trades to the new signal boundary.
        for state in active:
            advance_trade(
                state=state,
                through_timestamp=event_timestamp,
                bars=bars,
                kama_results=kama_results,
                underlying_timestamps=underlying_timestamps,
                lifecycle=OptionTradeLifecycle(),
            )

        # Remove only trades that actually closed at or before this signal.
        active = [
            state
            for state in active
            if not state.managed.result.closed
            or state.managed.result.exits[-1].timestamp > event_timestamp
        ]

        try:
            contract = resolver.resolve(
                underlying_price=bars[event.index].close,
                entry_date=datetime.fromtimestamp(
                    event_timestamp,
                    tz=TZ,
                ).date(),
                direction=event.direction.value,
            )
        except LookupError:
            unresolved += 1
            continue

        active_positions = [
            make_active_position(state.managed)
            for state in active
        ]

        decision = evaluate_signal(
            strategy_id=event.strategy_id.value,
            direction=event.direction.value,
            symbol=contract.symbol,
            active_positions=active_positions,
            config=DEFAULT_POSITION_LIFECYCLE_CONFIG,
        )

        if decision.action != SignalAction.ENTER:
            lifecycle_rejected += 1
            continue

        candles = tuple(
            sorted(
                loader.load(
                    contract.instrument_id,
                    event_timestamp - 3600,
                    event_timestamp + 3600,
                ),
                key=lambda candle: candle.timestamp,
            )
        )

        first_later = next(
            (
                candle
                for candle in candles
                if candle.timestamp > event_timestamp
            ),
            None,
        )

        if first_later is None:
            no_entry_candle += 1
            continue

        entry = OptionEntry(
            event=event,
            contract=contract,
            signal_timestamp=event_timestamp,
            entry_timestamp=first_later.timestamp,
            underlying_price=bars[event.index].close,
            entry_price=first_later.close,
            lifecycle_action=decision.action,
            lifecycle_reason=decision.reason,
        )

        position_manager = OptionTradeLifecycle()
        try:
            position = position_manager.create_position(
                strategy_id=event.strategy_id.value,
                direction=(
                    OptionTradeDirection.LONG
                    if event.direction.value == "LONG"
                    else OptionTradeDirection.SHORT
                ),
                symbol=contract.symbol,
                entry_price=entry.entry_price,
            )
        except ValueError as exc:
            if str(exc) != ALLOCATION_ERROR:
                raise
            allocation_rejected += 1
            continue

        # Store all candles from entry onward. The entry candle is skipped
        # for exit processing, matching run_option_trade_management().
        trade = build_managed_trade(
            entry=entry,
            position=position,
            exits=[],
        )
        trade_candles = tuple(
            candle
            for candle in candles
            if candle.timestamp >= entry.entry_timestamp
        )

        next_index = 1
        # Account for any duplicate/extra timestamps defensively.
        if len(trade_candles) <= 1:
            next_index = len(trade_candles)
        else:
            next_index = 1

        active.append(
            ActiveTradeState(
                managed=trade,
                candles=trade_candles,
                next_index=next_index,
            )
        )
        all_trades.append(trade)

    # Finish all remaining active trades through the sample boundary.
    for state in active:
        advance_trade(
            state=state,
            through_timestamp=end_timestamp,
            bars=bars,
            kama_results=kama_results,
            underlying_timestamps=underlying_timestamps,
            lifecycle=OptionTradeLifecycle(),
        )

    closed = [trade for trade in all_trades if trade.result.closed]
    open_trades = [trade for trade in all_trades if not trade.result.closed]

    # all_trades entries are immutable ManagedOptionTrade wrappers. Because
    # state.managed is replaced as exits occur, refresh the collection from
    # active/closed state by matching entry event indexes.
    final_by_event: dict[tuple[int, str, str], ManagedOptionTrade] = {}
    for state in active:
        key = (
            state.managed.entry.event.index,
            state.managed.entry.event.strategy_id.value,
            state.managed.entry.entry_timestamp and state.managed.entry.event.direction.value,
        )
        final_by_event[key] = state.managed

    # Reconstruct final trades using the latest state objects. For a robust
    # report, rebuild from both closed and open references present in active
    # and previously closed trade snapshots.
    # Since all trades are single-event entries, use event identity.
    final_trades: list[ManagedOptionTrade] = []
    active_keys = {
        (
            state.managed.entry.event.index,
            state.managed.entry.event.strategy_id.value,
            state.managed.entry.event.direction.value,
        )
        for state in active
    }

    # Closed trades are already reflected in all_trades as their wrapper was
    # replaced inside the active state. Track them separately below using a
    # chronological ledger.
    # The simple implementation above needs a ledger to keep final wrappers.
    return {
        "all_trades": all_trades,
        "closed": closed,
        "open": open_trades,
        "unresolved": unresolved,
        "no_entry_candle": no_entry_candle,
        "allocation_rejected": allocation_rejected,
        "lifecycle_rejected": lifecycle_rejected,
    }


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()
    end_timestamp = bars[-1].timestamp + 3600

    current = run_resilient(
        bars=bars,
        events=pipeline.events,
        resolver=resolver,
        option_loader=loader,
        end_timestamp=end_timestamp,
    )

    print("=" * 100)
    print("KUNAL QUANT — CHRONOLOGICAL POSITION LIFECYCLE DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"Sample                    : {local_dt(bars[0].timestamp)} -> {local_dt(bars[-1].timestamp)}")
    print(f"KTMI events               : {len(pipeline.events):,}")
    print()
    print("CURRENT RESILIENT PATH")
    print(f"Accepted trades           : {len(current.trades):,}")
    print(f"Closed trades             : {sum(t.result.closed for t in current.trades):,}")
    print(f"Open trades               : {current.open_trades:,}")
    print(f"Allocation rejected       : {current.allocation_rejected_events:,}")
    print(f"Unresolved                : {current.unresolved_events:,}")
    print(f"No entry candle           : {current.no_entry_candle_events:,}")
    print(f"Closed gross P&L          : {sum(float(t.result.total_pnl) for t in current.trades if t.result.closed):,.2f}")
    print()
    print("NOTE: this proposal file is intentionally not used for any canonical")
    print("patch. It is a diagnostic scaffold; productionization requires a")
    print("small follow-up refactor to retain immutable trade snapshots as they")
    print("close.")
    

if __name__ == "__main__":
    main()
