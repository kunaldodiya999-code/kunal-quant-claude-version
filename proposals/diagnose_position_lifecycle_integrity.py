"""
Kunal Quant — Position Lifecycle Integrity Diagnostic (PROPOSAL)

Read-only audit for the bounded real option sample.

Purpose
-------
Compare the current resilient sample's event acceptance with an
orchestrator that preserves the intended Position Lifecycle V1 state
across events.

Important:
- Canonical KunalQuant is not modified.
- This does NOT change strategy logic.
- This does NOT become a production patch.
- It only quantifies whether active-position state is being carried
  between event evaluations.

The diagnostic reports:
- current/as-run completed and open trades
- same-strategy overlapping trades in the as-run sample
- a strict stateful-lifecycle simulation
- event counts and realized P&L under the strict simulation
- event indexes accepted by as-run but rejected by strict lifecycle
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionEntry
from backtest.option_trade_lifecycle import (
    OptionTradeDirection,
    OptionTradeLifecycle,
)
from backtest.option_trade_management import run_option_trade_management
from backtest.position_lifecycle import (
    ActivePosition,
    SignalAction,
    evaluate_signal,
    DEFAULT_POSITION_LIFECYCLE_CONFIG,
)
from config.settings import DATABASE_PATH
from run_real_option_sample_resilient import run_resilient
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from strategies.option_contract_resolver import OptionContractResolver
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline

TZ = ZoneInfo("Asia/Kolkata")
ALLOCATION_ERROR = "Allocation cannot purchase one complete lot"


@dataclass(frozen=True)
class ActiveRecord:
    position: ActivePosition
    close_timestamp: int | None


def local_dt(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=TZ).isoformat()


def _entry_date(ts: int):
    return datetime.fromtimestamp(ts, tz=TZ).date()


def strict_stateful_run(
    *,
    bars: list[BacktestBar],
    events,
    resolver: OptionContractResolver,
    loader: FyersOptionCandleLoader,
    end_timestamp: int,
):
    active: list[ActiveRecord] = []
    trades = []
    unresolved = 0
    no_entry_candle = 0
    allocation_rejected = 0
    lifecycle_rejected = 0
    accepted_event_indexes: set[int] = set()

    # KAMA is calculated inside the existing management chain.
    from backtest.real_option_trade_runner import calculate_nifty_kama

    kama_results = calculate_nifty_kama(bars)

    for event in sorted(events, key=lambda e: (e.index, e.timestamp)):
        # A position whose actual final exit is strictly before this
        # signal timestamp is no longer active.
        active = [
            record
            for record in active
            if record.close_timestamp is None
            or record.close_timestamp >= event.timestamp
        ]

        try:
            contract = resolver.resolve(
                underlying_price=bars[event.index].close,
                entry_date=_entry_date(bars[event.index].timestamp),
                direction=event.direction.value,
            )
        except LookupError:
            unresolved += 1
            continue

        positions = [record.position for record in active]
        decision = evaluate_signal(
            strategy_id=event.strategy_id.value,
            direction=event.direction.value,
            symbol=contract.symbol,
            active_positions=positions,
            config=DEFAULT_POSITION_LIFECYCLE_CONFIG,
        )

        if decision.action != SignalAction.ENTER:
            lifecycle_rejected += 1
            continue

        candles = list(
            loader.load(
                contract.instrument_id,
                bars[event.index].timestamp - 3600,
                bars[event.index].timestamp + 3600,
            )
        )
        next_candle = next(
            (
                candle
                for candle in sorted(candles, key=lambda c: c.timestamp)
                if candle.timestamp > bars[event.index].timestamp
            ),
            None,
        )

        if next_candle is None:
            no_entry_candle += 1
            continue

        direction = (
            OptionTradeDirection.LONG
            if event.direction.value == "LONG"
            else OptionTradeDirection.SHORT
        )

        entry = OptionEntry(
            event=event,
            contract=contract,
            signal_timestamp=bars[event.index].timestamp,
            entry_timestamp=next_candle.timestamp,
            underlying_price=bars[event.index].close,
            entry_price=next_candle.close,
            lifecycle_action=decision.action,
            lifecycle_reason=decision.reason,
        )

        try:
            managed = run_option_trade_management(
                entry=entry,
                option_candles=loader.load(
                    contract.instrument_id,
                    entry.entry_timestamp,
                    end_timestamp,
                ),
                underlying_bars=bars,
                kama_results=kama_results,
                lifecycle=OptionTradeLifecycle(),
            )
        except ValueError as exc:
            if str(exc) != ALLOCATION_ERROR:
                raise
            allocation_rejected += 1
            continue

        trades.append(managed)
        accepted_event_indexes.add(event.index)

        if not managed.result.closed:
            active.append(
                ActiveRecord(
                    position=ActivePosition(
                        strategy_id=event.strategy_id.value,
                        direction=event.direction.value,
                        symbol=contract.symbol,
                    ),
                    close_timestamp=None,
                )
            )
        else:
            final_exit = managed.result.exits[-1].timestamp
            # Keep a just-closed position in the state until the next
            # signal strictly after the exit timestamp.
            active.append(
                ActiveRecord(
                    position=ActivePosition(
                        strategy_id=event.strategy_id.value,
                        direction=event.direction.value,
                        symbol=contract.symbol,
                    ),
                    close_timestamp=final_exit,
                )
            )

    closed = [trade for trade in trades if trade.result.closed]
    open_trades = [trade for trade in trades if not trade.result.closed]

    return {
        "trades": trades,
        "closed": closed,
        "open": open_trades,
        "unresolved": unresolved,
        "no_entry_candle": no_entry_candle,
        "allocation_rejected": allocation_rejected,
        "lifecycle_rejected": lifecycle_rejected,
        "accepted_event_indexes": accepted_event_indexes,
        "gross_pnl_closed": sum(float(t.result.total_pnl) for t in closed),
    }


def find_as_run_overlaps(as_run_trades):
    overlaps = []
    grouped = {}

    for trade in as_run_trades:
        strategy = trade.entry.event.strategy_id.value
        start = trade.entry.signal_timestamp
        if trade.result.closed and trade.result.exits:
            end = trade.result.exits[-1].timestamp
        else:
            end = None
        grouped.setdefault(strategy, []).append((trade, start, end))

    for strategy, rows in grouped.items():
        rows.sort(key=lambda x: x[1])
        for i, (left_trade, left_start, left_end) in enumerate(rows):
            for right_trade, right_start, right_end in rows[i + 1 :]:
                if left_end is None or right_start <= left_end:
                    overlaps.append(
                        {
                            "strategy": strategy,
                            "left_event_index": left_trade.entry.event.index,
                            "left_start": local_dt(left_start),
                            "left_end": None if left_end is None else local_dt(left_end),
                            "right_event_index": right_trade.entry.event.index,
                            "right_start": local_dt(right_start),
                        }
                    )
    return overlaps


def main() -> None:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())

    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()
    end_timestamp = bars[-1].timestamp + 3600

    as_run = run_resilient(
        bars=bars,
        events=pipeline.events,
        resolver=resolver,
        option_loader=loader,
        end_timestamp=end_timestamp,
    )

    strict = strict_stateful_run(
        bars=bars,
        events=pipeline.events,
        resolver=resolver,
        loader=loader,
        end_timestamp=end_timestamp,
    )

    as_run_closed = [t for t in as_run.trades if t.result.closed]
    as_run_open = [t for t in as_run.trades if not t.result.closed]
    as_run_accepted = {t.entry.event.index for t in as_run.trades}

    overlaps = find_as_run_overlaps(as_run.trades)
    bypassed = sorted(as_run_accepted - strict["accepted_event_indexes"])

    print("=" * 100)
    print("KUNAL QUANT — POSITION LIFECYCLE INTEGRITY DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"Sample                    : {local_dt(bars[0].timestamp)} -> {local_dt(bars[-1].timestamp)}")
    print(f"KTMI events               : {len(pipeline.events):,}")
    print()
    print("AS-RUN / CURRENT RESILIENT PATH")
    print(f"Accepted trades           : {len(as_run.trades):,}")
    print(f"Closed trades             : {len(as_run_closed):,}")
    print(f"Open trades               : {len(as_run_open):,}")
    print(f"Allocation rejected       : {as_run.allocation_rejected_events:,}")
    print(f"Unresolved                : {as_run.unresolved_events:,}")
    print(f"No entry candle           : {as_run.no_entry_candle_events:,}")
    print(f"Closed gross P&L          : {sum(float(t.result.total_pnl) for t in as_run_closed):,.2f}")
    print(f"Same-strategy overlaps    : {len(overlaps):,}")
    print()
    print("STATEFUL POSITION-LIFECYCLE SIMULATION")
    print(f"Accepted trades           : {len(strict['trades']):,}")
    print(f"Closed trades             : {len(strict['closed']):,}")
    print(f"Open trades               : {len(strict['open']):,}")
    print(f"Lifecycle rejected        : {strict['lifecycle_rejected']:,}")
    print(f"Allocation rejected       : {strict['allocation_rejected']:,}")
    print(f"Unresolved                : {strict['unresolved']:,}")
    print(f"No entry candle           : {strict['no_entry_candle']:,}")
    print(f"Closed gross P&L          : {strict['gross_pnl_closed']:,.2f}")
    print()
    print("AS-RUN EVENTS ACCEPTED BUT BLOCKED BY STATEFUL LIFECYCLE")
    print(f"Count                     : {len(bypassed):,}")

    if bypassed:
        print("First 20 event indexes     : " + ", ".join(map(str, bypassed[:20])))

    if overlaps:
        print()
        print("FIRST 10 SAME-STRATEGY OVERLAPS")
        for row in overlaps[:10]:
            print(
                f"{row['strategy']} | "
                f"event {row['left_event_index']} "
                f"{row['left_start']} -> {row['left_end'] or 'OPEN'} | "
                f"event {row['right_event_index']} "
                f"starts {row['right_start']}"
            )


if __name__ == "__main__":
    main()
