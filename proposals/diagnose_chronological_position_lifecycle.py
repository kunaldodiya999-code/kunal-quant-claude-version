"""
Kunal Quant — Chronological Position Lifecycle Diagnostic (PROPOSAL)

Read-only diagnostic for the bounded real-data option sample.

The current runner simulates a whole trade before advancing to the next
KTMI event. That means a position can be removed from active state using a
future exit before intervening signals are evaluated.

This proposal simulates the same locked lifecycle rules in chronological
order:
- active trades are advanced only up to the current signal timestamp;
- a new signal is evaluated against positions actually active then;
- a pending accepted signal also occupies its strategy before its first
  option entry candle, matching the existing entry bridge behavior;
- the first option candle strictly after the signal is the entry price and
  is not processed as an exit candle, matching the existing management code;
- later option candles are processed once, in chronological order;
- no new KTMI/resolver/lifecycle rules are invented.

Canonical KunalQuant is not modified.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
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
from config.settings import DATABASE_PATH
from run_real_option_sample_resilient import run_resilient
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")
ALLOCATION_ERROR = "Allocation cannot purchase one complete lot"


@dataclass
class ChronologicalTradeState:
    entry: OptionEntry
    position: OptionTradePosition
    exits: list[OptionTradeExit] = field(default_factory=list)
    candles: tuple[OptionCandle, ...] = ()
    next_index: int = 1

    @property
    def closed(self) -> bool:
        return self.position.closed

    def managed(self) -> ManagedOptionTrade:
        result = OptionTradeResult(
            position=self.position,
            exits=tuple(self.exits),
            total_pnl=self.position.gross_pnl,
            closed=self.position.closed,
        )
        return ManagedOptionTrade(
            entry=self.entry,
            position=self.position,
            result=result,
        )


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def make_active_position(state: ChronologicalTradeState) -> ActivePosition:
    return ActivePosition(
        strategy_id=state.entry.event.strategy_id.value,
        direction=state.entry.event.direction.value,
        symbol=state.entry.contract.symbol,
    )


def calculate_kama(bars: list[BacktestBar]):
    from backtest.real_option_trade_runner import calculate_nifty_kama
    return calculate_nifty_kama(bars)


def advance_trade(
    *,
    state: ChronologicalTradeState,
    through_timestamp: int,
    bars: list[BacktestBar],
    kama_results,
    underlying_timestamps: list[int],
    lifecycle: OptionTradeLifecycle,
) -> None:
    """
    Process option candles strictly after entry and up to the requested time.

    This reproduces the per-candle logic from option_trade_management.py
    without using that module's all-the-way-to-end orchestration.
    """
    while (
        state.next_index < len(state.candles)
        and state.candles[state.next_index].timestamp <= through_timestamp
        and not state.position.closed
    ):
        candle = state.candles[state.next_index]
        state.next_index += 1

        underlying_index = bisect.bisect_right(
            underlying_timestamps,
            candle.timestamp,
        ) - 1

        if underlying_index < 0:
            continue

        underlying = bars[underlying_index]
        kama = kama_results[underlying_index]

        candle_exits = lifecycle.process_candle(
            position=state.position,
            timestamp=candle.timestamp,
            option_high=candle.high,
            option_low=candle.low,
            option_close=candle.close,
            underlying_close=underlying.close,
            kama_value=kama.kama,
        )

        state.exits.extend(candle_exits)


def chronological_run(
    *,
    bars: list[BacktestBar],
    events,
    resolver: OptionContractResolver,
    loader: FyersOptionCandleLoader,
    end_timestamp: int,
):
    kama_results = calculate_kama(bars)
    underlying_timestamps = [bar.timestamp for bar in bars]

    active: list[ChronologicalTradeState] = []
    closed: list[ManagedOptionTrade] = []
    unresolved = 0
    no_entry_candle = 0
    allocation_rejected = 0
    lifecycle_rejected = 0

    ordered_events = sorted(
        list(events),
        key=lambda event: (event.index, event.timestamp),
    )

    for event in ordered_events:
        event_timestamp = bars[event.index].timestamp

        # Bring existing positions up to the exact signal boundary before
        # deciding whether this new signal may enter.
        for state in active:
            advance_trade(
                state=state,
                through_timestamp=event_timestamp,
                bars=bars,
                kama_results=kama_results,
                underlying_timestamps=underlying_timestamps,
                lifecycle=OptionTradeLifecycle(),
            )

        still_active: list[ChronologicalTradeState] = []
        for state in active:
            if state.closed:
                closed.append(state.managed())
            else:
                still_active.append(state)
        active = still_active

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

        decision = evaluate_signal(
            strategy_id=event.strategy_id.value,
            direction=event.direction.value,
            symbol=contract.symbol,
            active_positions=[
                make_active_position(state)
                for state in active
            ],
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

        entry_candle = next(
            (
                candle
                for candle in candles
                if candle.timestamp > event_timestamp
            ),
            None,
        )

        if entry_candle is None:
            no_entry_candle += 1
            continue

        entry = OptionEntry(
            event=event,
            contract=contract,
            signal_timestamp=event_timestamp,
            entry_timestamp=entry_candle.timestamp,
            underlying_price=bars[event.index].close,
            entry_price=entry_candle.close,
            lifecycle_action=decision.action,
            lifecycle_reason=decision.reason,
        )

        manager = OptionTradeLifecycle()
        direction = (
            OptionTradeDirection.LONG
            if event.direction.value == "LONG"
            else OptionTradeDirection.SHORT
        )

        try:
            position = manager.create_position(
                strategy_id=event.strategy_id.value,
                direction=direction,
                symbol=contract.symbol,
                entry_price=entry.entry_price,
            )
        except ValueError as exc:
            if str(exc) != ALLOCATION_ERROR:
                raise
            allocation_rejected += 1
            continue

        entry_plus_candles = tuple(
            candle
            for candle in candles
            if candle.timestamp >= entry.entry_timestamp
        )

        state = ChronologicalTradeState(
            entry=entry,
            position=position,
            exits=[],
            candles=entry_plus_candles,
            next_index=1,
        )

        # Accepted position is active immediately, matching the existing
        # option entry bridge which reserves the strategy before the next
        # event is evaluated.
        active.append(state)

    # Finish all remaining positions through the existing report boundary.
    still_active: list[ChronologicalTradeState] = []
    for state in active:
        advance_trade(
            state=state,
            through_timestamp=end_timestamp,
            bars=bars,
            kama_results=kama_results,
            underlying_timestamps=underlying_timestamps,
            lifecycle=OptionTradeLifecycle(),
        )
        if state.closed:
            closed.append(state.managed())
        else:
            still_active.append(state)

    open_trades = [
        state.managed()
        for state in still_active
    ]

    all_closed_pnl = sum(
        float(trade.result.total_pnl)
        for trade in closed
    )

    return {
        "closed": tuple(closed),
        "open": tuple(open_trades),
        "unresolved": unresolved,
        "no_entry_candle": no_entry_candle,
        "allocation_rejected": allocation_rejected,
        "lifecycle_rejected": lifecycle_rejected,
        "gross_pnl_closed": all_closed_pnl,
    }


def find_overlaps(trades: tuple[ManagedOptionTrade, ...]) -> int:
    overlaps = 0
    by_strategy: dict[str, list[ManagedOptionTrade]] = {}

    for trade in trades:
        by_strategy.setdefault(
            trade.entry.event.strategy_id.value,
            [],
        ).append(trade)

    for strategy_trades in by_strategy.values():
        strategy_trades.sort(
            key=lambda trade: trade.entry.signal_timestamp
        )
        for i, left in enumerate(strategy_trades):
            if not left.result.exits:
                continue
            left_end = left.result.exits[-1].timestamp
            for right in strategy_trades[i + 1:]:
                if right.entry.signal_timestamp <= left_end:
                    overlaps += 1

    return overlaps


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )
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

    chrono = chronological_run(
        bars=bars,
        events=pipeline.events,
        resolver=resolver,
        loader=loader,
        end_timestamp=end_timestamp,
    )

    current_closed = [
        trade for trade in current.trades
        if trade.result.closed
    ]
    chrono_closed = chrono["closed"]

    chrono_all = chrono_closed + chrono["open"]

    print("=" * 100)
    print("KUNAL QUANT — CHRONOLOGICAL POSITION LIFECYCLE DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(
        f"Sample                    : "
        f"{local_dt(bars[0].timestamp)} -> {local_dt(bars[-1].timestamp)}"
    )
    print(f"KTMI events               : {len(pipeline.events):,}")
    print()
    print("CURRENT RESILIENT PATH")
    print(f"Accepted trades           : {len(current.trades):,}")
    print(f"Closed trades             : {len(current_closed):,}")
    print(f"Open trades               : {current.open_trades:,}")
    print(f"Allocation rejected       : {current.allocation_rejected_events:,}")
    print(f"Unresolved                : {current.unresolved_events:,}")
    print(f"No entry candle           : {current.no_entry_candle_events:,}")
    print(
        f"Closed gross P&L          : "
        f"{sum(float(t.result.total_pnl) for t in current_closed):,.2f}"
    )
    print()
    print("CHRONOLOGICAL STATEFUL PATH")
    print(f"Closed trades             : {len(chrono_closed):,}")
    print(f"Open trades               : {len(chrono['open']):,}")
    print(f"Lifecycle rejected        : {chrono['lifecycle_rejected']:,}")
    print(f"Allocation rejected       : {chrono['allocation_rejected']:,}")
    print(f"Unresolved                : {chrono['unresolved']:,}")
    print(f"No entry candle           : {chrono['no_entry_candle']:,}")
    print(f"Closed gross P&L          : {chrono['gross_pnl_closed']:,.2f}")
    print()
    print(
        f"Chronological same-strategy overlaps : "
        f"{find_overlaps(chrono_all):,}"
    )
    print()
    print("This is a behavior diagnostic only. No canonical code was changed.")


if __name__ == "__main__":
    main()
