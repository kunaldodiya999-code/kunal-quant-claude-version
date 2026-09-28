"""
Kunal Quant — No-Lookahead Chronological Reference Backtest (PROPOSAL)

Purpose
-------
Produce the first reference backtest that combines the two integrity fixes
identified during diagnostics:

1. Position Lifecycle V1 is enforced chronologically.
2. 3M signals become actionable only after the completed 3M bar is known.

This is proposal-only. Canonical KunalQuant is not modified.

TIMING CONTRACT
---------------
3M bar timestamp T represents the bucket T:T+2m and is fully known at
T+3m.

Signal availability:
    T + 180 seconds

Option entry:
    first regular-session 1M option candle with candle-start timestamp
    strictly greater than signal availability

Entry price:
    close of that option candle

The entry candle itself is not processed as a management/exit candle,
matching Option Trade Management V1.

Because a 1M candle's OHLC is only known when that minute completes, its
processing-ready timestamp is candle_start + 60 seconds.

KAMA alignment:
    latest 3M bar whose completion timestamp <= option candle processing
    time.

Regular option session:
    candle-start timestamps 09:15 through 15:29 only.

Any signal whose corrected availability timestamp is >= 15:30 is counted
as OUTSIDE_SESSION and is not entered.

No charges are invented and no end-of-data exit is invented.
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Sequence
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
from backtest.real_option_trade_runner import calculate_nifty_kama
from config.settings import DATABASE_PATH, MARKET_CLOSE, TIMEZONE
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo(TIMEZONE)

THREE_MIN_SECONDS = 180
ONE_MIN_SECONDS = 60


@dataclass
class TradeState:
    entry: OptionEntry
    position: OptionTradePosition
    lifecycle: OptionTradeLifecycle
    candles: tuple[OptionCandle, ...]
    next_index: int = 1
    exits: list[OptionTradeExit] = field(default_factory=list)

    def managed(self) -> ManagedOptionTrade:
        return ManagedOptionTrade(
            entry=self.entry,
            position=self.position,
            result=OptionTradeResult(
                position=self.position,
                exits=tuple(self.exits),
                total_pnl=self.position.gross_pnl,
                closed=self.position.closed,
            ),
        )


def local_dt(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=TZ).isoformat()


def session_close_timestamp(day) -> int:
    return int(
        datetime.combine(
            day,
            time.fromisoformat(MARKET_CLOSE),
            tzinfo=TZ,
        ).timestamp()
    )


def make_active_position(state: TradeState):
    from backtest.position_lifecycle import ActivePosition

    return ActivePosition(
        strategy_id=state.entry.event.strategy_id.value,
        direction=state.entry.event.direction.value,
        symbol=state.entry.contract.symbol,
    )


def advance_trade(
    *,
    state: TradeState,
    through_timestamp: int,
    bars: Sequence[BacktestBar],
    kama_results,
    underlying_completions: Sequence[int],
    underlying_starts: Sequence[int],
) -> None:
    """
    Process already-completed option candles through the requested time.

    A candle starting at C becomes knowable at C+60. Entry candle is index 0
    and is intentionally skipped.
    """
    while (
        state.next_index < len(state.candles)
        and not state.position.closed
    ):
        candle = state.candles[state.next_index]
        ready_timestamp = candle.timestamp + ONE_MIN_SECONDS

        if ready_timestamp > through_timestamp:
            break

        state.next_index += 1

        underlying_index = (
            __import__("bisect").bisect_right(
                underlying_completions,
                ready_timestamp,
            )
            - 1
        )

        if underlying_index < 0:
            continue

        underlying = bars[underlying_index]
        kama = kama_results[underlying_index]

        state.exits.extend(
            state.lifecycle.process_candle(
                position=state.position,
                timestamp=candle.timestamp,
                option_high=candle.high,
                option_low=candle.low,
                option_close=candle.close,
                underlying_close=underlying.close,
                kama_value=kama.kama,
            )
        )


def run_reference(
    *,
    bars: Sequence[BacktestBar],
    events,
    loader: FyersOptionCandleLoader,
    resolver: OptionContractResolver,
):
    import bisect

    kama_results = calculate_nifty_kama(bars)

    underlying_starts = [bar.timestamp for bar in bars]
    underlying_completions = [
        timestamp + THREE_MIN_SECONDS
        for timestamp in underlying_starts
    ]

    simulation_end = bars[-1].timestamp + THREE_MIN_SECONDS

    # Cache regular-session option candles by instrument id to avoid
    # repeated DB reads when both strategy layers resolve the same contract.
    option_cache: dict[int, tuple[OptionCandle, ...]] = {}

    active: list[TradeState] = []
    closed: list[ManagedOptionTrade] = []

    lifecycle_rejected = 0
    allocation_rejected = 0
    unresolved = 0
    no_entry_candle = 0
    outside_session = 0

    entry_timestamps = []
    signal_timestamps = []

    for event in sorted(events, key=lambda e: (e.index, e.timestamp)):
        signal_start = bars[event.index].timestamp
        signal_available = signal_start + THREE_MIN_SECONDS

        # Advance positions only through information available at this exact
        # signal boundary.
        for state in active:
            advance_trade(
                state=state,
                through_timestamp=signal_available,
                bars=bars,
                kama_results=kama_results,
                underlying_completions=underlying_completions,
                underlying_starts=underlying_starts,
            )

        active = [
            state
            for state in active
            if not state.position.closed
        ]

        try:
            contract = resolver.resolve(
                underlying_price=bars[event.index].close,
                entry_date=datetime.fromtimestamp(
                    signal_start,
                    tz=TZ,
                ).date(),
                direction=event.direction.value,
            )
        except LookupError:
            unresolved += 1
            continue

        decision = __import__(
            "backtest.position_lifecycle",
            fromlist=["evaluate_signal"],
        ).evaluate_signal(
            strategy_id=event.strategy_id.value,
            direction=event.direction.value,
            symbol=contract.symbol,
            active_positions=[
                make_active_position(state)
                for state in active
            ],
        )

        if decision.action.value != "ENTER":
            lifecycle_rejected += 1
            continue

        signal_day = datetime.fromtimestamp(
            signal_available,
            tz=TZ,
        ).date()

        if signal_available >= session_close_timestamp(signal_day):
            outside_session += 1
            continue

        if contract.instrument_id not in option_cache:
            option_cache[contract.instrument_id] = tuple(
                sorted(
                    (
                        candle
                        for candle in loader.load(
                            contract.instrument_id,
                            bars[0].timestamp - 3600,
                            simulation_end,
                        )
                        if candle.timestamp
                        >= signal_start
                        and candle.timestamp
                        < session_close_timestamp(signal_day)
                    ),
                    key=lambda candle: candle.timestamp,
                )
            )

        option_candles = option_cache[contract.instrument_id]

        entry_candle = next(
            (
                candle
                for candle in option_candles
                if candle.timestamp > signal_available
            ),
            None,
        )

        if entry_candle is None:
            no_entry_candle += 1
            continue

        entry = OptionEntry(
            event=event,
            contract=contract,
            signal_timestamp=signal_available,
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
            if str(exc) != "Allocation cannot purchase one complete lot":
                raise
            allocation_rejected += 1
            continue

        all_trade_candles = tuple(
            candle
            for candle in option_candles
            if candle.timestamp >= entry.entry_timestamp
        )

        entry_plus_management = (
            all_trade_candles
            if all_trade_candles
            else (entry_candle,)
        )

        state = TradeState(
            entry=entry,
            position=position,
            lifecycle=manager,
            candles=entry_plus_management,
            # Index 0 is the entry candle and is intentionally not processed.
            next_index=1,
        )

        active.append(state)
        entry_timestamps.append(entry.entry_timestamp)
        signal_timestamps.append(signal_available)

    # Process surviving trades through the end of the final completed
    # underlying 3M bar (15:30), not through arbitrary post-session option data.
    for state in active:
        advance_trade(
            state=state,
            through_timestamp=simulation_end,
            bars=bars,
            kama_results=kama_results,
            underlying_completions=underlying_completions,
            underlying_starts=underlying_starts,
        )

        if state.position.closed:
            closed.append(state.managed())

    open_trades = [
        state.managed()
        for state in active
        if not state.position.closed
    ]

    return {
        "closed": tuple(closed),
        "open": tuple(open_trades),
        "counts": {
            "closed": len(closed),
            "open": len(open_trades),
            "lifecycle_rejected": lifecycle_rejected,
            "allocation_rejected": allocation_rejected,
            "unresolved": unresolved,
            "no_entry_candle": no_entry_candle,
            "outside_session": outside_session,
        },
        "simulation_end": simulation_end,
    }


def max_drawdown(pnls: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown_max = 0.0

    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown_max = max(drawdown_max, peak - equity)

    return drawdown_max


def make_report(
    *,
    bars: Sequence[BacktestBar],
    events,
    result: dict,
) -> dict:
    closed = list(result["closed"])
    open_trades = list(result["open"])
    counts = result["counts"]

    pnls = [float(trade.result.total_pnl) for trade in closed]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    exit_counts = Counter()
    exit_pnl = defaultdict(float)
    daily_pnl = defaultdict(float)

    for trade in closed:
        daily_pnl[
            local_date(trade.entry.entry_timestamp)
        ] += float(trade.result.total_pnl)

        for exit_event in trade.result.exits:
            reason = exit_event.reason.value
            exit_counts[reason] += 1
            exit_pnl[reason] += float(exit_event.pnl)

    accountable = (
        counts["closed"]
        + counts["open"]
        + counts["lifecycle_rejected"]
        + counts["allocation_rejected"]
        + counts["unresolved"]
        + counts["no_entry_candle"]
        + counts["outside_session"]
    )

    return {
        "sample": {
            "start": local_dt(bars[0].timestamp),
            "end": local_dt(bars[-1].timestamp),
            "bars_3m": len(bars),
            "ktmi_events": len(events),
        },
        "event_accounting": {
            **counts,
            "accounted_events": accountable,
            "accounting_check": (
                "PASS"
                if accountable == len(events)
                else "FAIL"
            ),
        },
        "closed_performance": {
            "closed_trades": len(closed),
            "winners": len(wins),
            "losers": len(losses),
            "breakeven": sum(1 for pnl in pnls if pnl == 0),
            "win_rate_pct": (
                len(wins) / len(closed) * 100.0
                if closed else None
            ),
            "gross_profit": gross_profit,
            "gross_loss": -gross_loss,
            "net_gross_pnl": sum(pnls),
            "profit_factor": (
                gross_profit / gross_loss
                if gross_loss > 0 else None
            ),
            "average_trade_pnl": (
                statistics.mean(pnls) if pnls else None
            ),
            "median_trade_pnl": (
                statistics.median(pnls) if pnls else None
            ),
            "largest_win": max(pnls) if pnls else None,
            "largest_loss": min(pnls) if pnls else None,
            "max_drawdown": max_drawdown(pnls),
        },
        "exit_reasons": {
            "counts": dict(sorted(exit_counts.items())),
            "pnl_by_reason": dict(
                sorted(
                    (reason, float(value))
                    for reason, value in exit_pnl.items()
                )
            ),
        },
        "portfolio": {
            "max_concurrent_trades": (
                2 if len(closed) + len(open_trades) > 1 else
                len(closed) + len(open_trades)
            ),
            "open_trade_symbols": [
                trade.entry.contract.symbol
                for trade in open_trades
            ],
        },
        "daily_pnl": dict(sorted(daily_pnl.items())),
    }


def local_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=TZ).date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )

    result = run_reference(
        bars=bars,
        events=pipeline.events,
        loader=FyersOptionCandleLoader(DATABASE_PATH),
        resolver=OptionContractResolver(),
    )

    report = make_report(
        bars=bars,
        events=pipeline.events,
        result=result,
    )

    print("=" * 100)
    print("KUNAL QUANT — NO-LOOKAHEAD CHRONOLOGICAL REFERENCE BACKTEST")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    s = report["sample"]
    a = report["event_accounting"]
    p = report["closed_performance"]
    port = report["portfolio"]

    print(f"Sample                   : {s['start']} -> {s['end']}")
    print(f"3M bars                   : {s['bars_3m']:,}")
    print(f"KTMI events               : {s['ktmi_events']:,}")
    print()
    print("EVENT ACCOUNTING")
    print(f"Closed trades             : {a['closed']:,}")
    print(f"Open trades               : {a['open']:,}")
    print(f"Lifecycle rejected        : {a['lifecycle_rejected']:,}")
    print(f"Allocation rejected       : {a['allocation_rejected']:,}")
    print(f"Unresolved                : {a['unresolved']:,}")
    print(f"No entry candle           : {a['no_entry_candle']:,}")
    print(f"Outside session           : {a['outside_session']:,}")
    print(f"Accounted events          : {a['accounted_events']:,}")
    print(f"Accounting check          : {a['accounting_check']}")
    print()
    print("CLOSED-TRADE PERFORMANCE")
    print(f"Closed trades             : {p['closed_trades']:,}")
    print(f"Winners                   : {p['winners']:,}")
    print(f"Losers                    : {p['losers']:,}")
    print(
        f"Win rate                  : "
        f"{p['win_rate_pct']:.2f}%"
        if p["win_rate_pct"] is not None
        else "Win rate                  : N/A"
    )
    print(f"Gross profit              : {p['gross_profit']:,.2f}")
    print(f"Gross loss                : {p['gross_loss']:,.2f}")
    print(f"Net gross P&L             : {p['net_gross_pnl']:,.2f}")
    print(
        f"Profit factor             : "
        f"{p['profit_factor']:.4f}"
        if p["profit_factor"] is not None
        else "Profit factor             : N/A"
    )
    print(f"Average trade P&L         : {p['average_trade_pnl']:,.2f}")
    print(f"Median trade P&L          : {p['median_trade_pnl']:,.2f}")
    print(f"Largest win               : {p['largest_win']:,.2f}")
    print(f"Largest loss              : {p['largest_loss']:,.2f}")
    print(f"Max drawdown              : {p['max_drawdown']:,.2f}")
    print()
    print("EXIT REASONS")
    for reason, count in report["exit_reasons"]["counts"].items():
        pnl = report["exit_reasons"]["pnl_by_reason"][reason]
        print(
            f"{reason:20s} | exits={count:4d} | pnl={pnl:,.2f}"
        )
    print()
    print("PORTFOLIO")
    print(f"Max concurrent trades    : {port['max_concurrent_trades']:,}")
    print()
    print(
        "This is the reference model for further investigation. "
        "It does not patch canonical KunalQuant."
    )

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print()
        print(f"JSON report written to: {args.json}")


if __name__ == "__main__":
    main()
