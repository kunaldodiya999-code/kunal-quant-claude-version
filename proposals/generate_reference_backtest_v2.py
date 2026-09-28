"""
Kunal Quant — Pre-Patch Reference Backtest V2 (PROPOSAL)

This is the proposal-only reference model intended to replace the earlier
diagnostic runners after the identified integrity issues are accounted for.

Canonical KunalQuant is NOT modified.

Key rules
---------
1. Calculate KTMI/KAMA using the full complete 3M history, then restrict
   trade events to the selected backtest window. This preserves recursive
   indicator state at the sample boundary.
2. A 3M bar stamped T contains T,T+1m,T+2m and becomes knowable at T+3m.
3. Signal availability = T+180s.
4. Option entry = first in-session 1M option candle strictly after signal
   availability; entry price = that candle close.
5. A 1M option candle becomes processable at candle_start+60s.
6. KAMA uses the latest underlying 3M bar whose completion <= option-candle
   processing time.
7. Position Lifecycle V1 is enforced chronologically.
8. The strategy is options-buying:
   - signal LONG => BUY CE
   - signal SHORT => BUY PE
   Option premium management is LONG for both; signal direction is retained
   separately for the underlying/KAMA exit condition.
9. 3R target / 20% premium stop / partial-exit behavior remains from the
   existing OptionTradeLifecycle V1.
10. Historical session is date-aware. No underlying bars are fabricated.
11. Every event must be accounted for exactly once.
12. No charges/slippage/end-of-data exits are invented.

This file is deliberately verbose and explicit so its behavior can be
regression-tested before any canonical patch is proposed.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence
from zoneinfo import ZoneInfo

from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.models import BacktestBar
from backtest.option_entry_bridge import OptionCandle, OptionEntry
from backtest.option_trade_lifecycle import (
    OptionExitReason,
    OptionTradeDirection,
    OptionTradeExit,
    OptionTradeLifecycle,
    OptionTradePosition,
    OptionTradeResult,
)
from backtest.option_trade_management import ManagedOptionTrade
from backtest.position_lifecycle import (
    DEFAULT_POSITION_LIFECYCLE_CONFIG,
    ActivePosition,
    SignalAction,
    evaluate_signal,
)
from backtest.real_option_trade_runner import calculate_nifty_kama
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH, TIMEZONE
from scripts.run_real_option_sample import (
    SYMBOL,
    DERIVED_DB,
    build_ktmi_config,
)
from strategies.ktmi_trigger_strategy import KTMITriggerStrategyConfig
from strategies.option_contract_resolver import OptionContractResolver

from session_calendar import (
    is_in_session_candle,
    option_session,
    session_close_timestamp,
)

TZ = ZoneInfo(TIMEZONE)
THREE_MIN_SECONDS = 180
ONE_MIN_SECONDS = 60
DERIVED_SOURCE = "KQ_DERIVED_FROM_FYERS_1M"


@dataclass
class TradeState:
    entry: OptionEntry
    position: OptionTradePosition
    lifecycle: OptionTradeLifecycle
    signal_direction: str
    candles: tuple[OptionCandle, ...]
    next_index: int = 1
    exits: list[OptionTradeExit] = field(default_factory=list)
    audit_id: int | None = None

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


def local_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=TZ).date().isoformat()


def load_all_complete_3m_bars() -> list[BacktestBar]:
    with sqlite3.connect(DERIVED_DB) as connection:
        rows = connection.execute(
            """
            SELECT timestamp, open, high, low, close, volume, open_interest
            FROM derived_candles
            WHERE symbol = ?
              AND resolution = '3'
              AND source = ?
              AND complete = 1
            ORDER BY timestamp
            """,
            (SYMBOL, DERIVED_SOURCE),
        ).fetchall()

    bars = [
        BacktestBar(
            timestamp=int(row[0]),
            open=float(row[1]),
            high=float(row[2]),
            low=float(row[3]),
            close=float(row[4]),
            volume=int(row[5] or 0),
            open_interest=None if row[6] is None else int(row[6]),
        )
        for row in rows
    ]
    if not bars:
        raise RuntimeError("No complete 3M derived bars found.")
    return bars


def select_last_days(
    bars: Sequence[BacktestBar],
    days: int,
) -> list[BacktestBar]:
    if days < 1:
        raise ValueError("days must be >= 1")
    unique_days: list[str] = []
    for bar in bars:
        d = local_date(bar.timestamp)
        if not unique_days or unique_days[-1] != d:
            unique_days.append(d)
    keep = set(unique_days[-days:])
    return [bar for bar in bars if local_date(bar.timestamp) in keep]


def build_trigger_config(args: argparse.Namespace) -> KTMITriggerStrategyConfig:
    return KTMITriggerStrategyConfig(
        long_short_speed_enabled=not args.disable_speed_sources,
        long_speed_trigger=args.long_speed_ce_trigger,
        short_speed_trigger=args.short_speed_pe_trigger,
        momentum_only_enabled=not args.disable_momentum,
        momentum_long_trigger=args.momentum_ce_trigger,
        momentum_short_trigger=args.momentum_pe_trigger,
    )


def process_buy_premium_candle(
    *,
    state: TradeState,
    candle: OptionCandle,
    underlying_close: float,
    kama_value: float | None,
) -> None:
    """
    Preserve V1 stop/target logic and apply KAMA using signal direction.

    Stop/target are calculated by OptionTradeLifecycle using
    OptionTradeDirection.LONG, which is correct for both CE and PE buys.
    The existing lifecycle KAMA branch is suppressed with kama_value=None.
    """
    lifecycle_exits = state.lifecycle.process_candle(
        position=state.position,
        timestamp=candle.timestamp,
        option_high=candle.high,
        option_low=candle.low,
        option_close=candle.close,
        underlying_close=underlying_close,
        kama_value=None,
    )

    state.exits.extend(lifecycle_exits)

    if lifecycle_exits:
        last_reason = lifecycle_exits[-1].reason
        if last_reason in (
            OptionExitReason.STOP_LOSS,
            OptionExitReason.TARGET_3R,
        ):
            return

    if state.position.closed or state.position.remaining_quantity <= 0:
        return

    if kama_value is None:
        return

    if state.signal_direction == "LONG":
        kama_exit = underlying_close < kama_value
    else:
        kama_exit = underlying_close > kama_value

    if not kama_exit:
        return

    pnl = state.lifecycle.calculate_pnl(
        direction=OptionTradeDirection.LONG,
        entry_price=state.position.entry_price,
        exit_price=candle.close,
        quantity=state.position.remaining_quantity,
    )

    exit_event = OptionTradeExit(
        timestamp=candle.timestamp,
        reason=OptionExitReason.KAMA_EXIT,
        price=candle.close,
        quantity=state.position.remaining_quantity,
        lots=state.position.remaining_lots,
        pnl=pnl,
        remaining_quantity=0,
        remaining_lots=0,
    )

    state.position.gross_pnl += pnl
    state.position.remaining_quantity = 0
    state.position.remaining_lots = 0
    state.position.closed = True
    state.exits.append(exit_event)


def advance_trade(
    *,
    state: TradeState,
    through_timestamp: int,
    bars: Sequence[BacktestBar],
    kama_results,
    underlying_completions: Sequence[int],
) -> None:
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
            bisect.bisect_right(
                underlying_completions,
                ready_timestamp,
            )
            - 1
        )
        if underlying_index < 0:
            continue

        underlying = bars[underlying_index]
        kama = kama_results[underlying_index]
        process_buy_premium_candle(
            state=state,
            candle=candle,
            underlying_close=underlying.close,
            kama_value=kama.kama,
        )


def run_reference(
    *,
    all_bars: list[BacktestBar],
    sample_bars: list[BacktestBar],
    trigger_config: KTMITriggerStrategyConfig,
) -> dict:
    pipeline = run_ktmi_trigger_pipeline(
        all_bars,
        build_ktmi_config(),
        trigger_config=trigger_config,
    )

    sample_start = sample_bars[0].timestamp
    sample_end = sample_bars[-1].timestamp
    sample_end_day = datetime.fromtimestamp(
        sample_end,
        tz=TZ,
    ).date()
    simulation_end = session_close_timestamp(sample_end_day)

    kama_results = calculate_nifty_kama(all_bars)
    underlying_completions = [
        bar.timestamp + THREE_MIN_SECONDS
        for bar in all_bars
    ]

    loader = FyersOptionCandleLoader(DATABASE_PATH)
    resolver = OptionContractResolver()

    # Cache full regular-session option history. The same contract can be
    # required on multiple days.
    option_cache: dict[int, tuple[OptionCandle, ...]] = {}

    active: list[TradeState] = []
    closed: list[ManagedOptionTrade] = []

    counts = Counter()
    event_audit: list[dict] = []

    selected_events = [
        event for event in pipeline.events
        if event.timestamp is not None
        and sample_start <= event.timestamp <= sample_end
    ]

    for event in sorted(
        selected_events,
        key=lambda e: (
            e.timestamp,
            0 if e.strategy_id.value == "KTMI_LONG_SHORT_SPEED" else 1,
            0 if e.direction.value == "LONG" else 1,
        ),
    ):
        signal_start = all_bars[event.index].timestamp
        signal_available = signal_start + THREE_MIN_SECONDS
        signal_day = datetime.fromtimestamp(
            signal_start,
            tz=TZ,
        ).date()
        audit_id = len(event_audit)
        event_audit.append({
            "event_index": int(event.index),
            "event_timestamp": int(event.timestamp),
            "event_timestamp_local": local_dt(event.timestamp),
            "strategy_id": event.strategy_id.value,
            "direction": event.direction.value,
            "outcome": None,
        })
        audit = event_audit[audit_id]
        audit["signal_start_timestamp"] = signal_start
        audit["signal_start_local"] = local_dt(signal_start)
        audit["signal_available_timestamp"] = signal_available
        audit["signal_available_local"] = local_dt(signal_available)

        # Advance positions to the exact point where this 3M signal is known.
        for state in active:
            advance_trade(
                state=state,
                through_timestamp=signal_available,
                bars=all_bars,
                kama_results=kama_results,
                underlying_completions=underlying_completions,
            )

        still_active: list[TradeState] = []
        for state in active:
            if state.position.closed:
                trade = state.managed()
                closed.append(trade)
                if state.audit_id is not None:
                    event_audit[state.audit_id]["outcome"] = "closed"
                    event_audit[state.audit_id]["exits"] = [
                        {
                            "timestamp": int(x.timestamp),
                            "timestamp_local": local_dt(x.timestamp),
                            "reason": x.reason.value,
                            "price": float(x.price),
                            "quantity": int(x.quantity),
                            "lots": int(x.lots),
                            "pnl": float(x.pnl),
                        }
                        for x in state.exits
                    ]
                    event_audit[state.audit_id]["total_pnl"] = float(
                        state.position.gross_pnl
                    )
            else:
                still_active.append(state)
        active = still_active

        try:
            contract = resolver.resolve(
                underlying_price=all_bars[event.index].close,
                entry_date=signal_day,
                direction=event.direction.value,
            )
        except LookupError:
            counts["unresolved"] += 1
            audit["outcome"] = "unresolved"
            continue

        decision = evaluate_signal(
            strategy_id=event.strategy_id.value,
            direction=event.direction.value,
            symbol=contract.symbol,
            active_positions=[
                ActivePosition(
                    strategy_id=state.entry.event.strategy_id.value,
                    direction=state.entry.event.direction.value,
                    symbol=state.entry.contract.symbol,
                )
                for state in active
            ],
            config=DEFAULT_POSITION_LIFECYCLE_CONFIG,
        )

        audit["lifecycle_action"] = decision.action.value
        audit["lifecycle_reason"] = decision.reason
        audit["active_positions_at_decision"] = [
            {
                "strategy_id": state.entry.event.strategy_id.value,
                "direction": state.entry.event.direction.value,
                "symbol": state.entry.contract.symbol,
            }
            for state in active
        ]

        if decision.action != SignalAction.ENTER:
            counts["lifecycle_rejected"] += 1
            audit["outcome"] = "lifecycle_rejected"
            continue

        session = option_session(signal_day)
        if signal_available >= session_close_timestamp(signal_day):
            counts["outside_session"] += 1
            audit["outcome"] = "outside_session"
            continue

        if contract.instrument_id not in option_cache:
            option_cache[contract.instrument_id] = tuple(
                sorted(
                    (
                        candle
                        for candle in loader.load(
                            contract.instrument_id,
                            sample_start - 86400,
                            simulation_end,
                        )
                        if is_in_session_candle(candle.timestamp)
                    ),
                    key=lambda candle: candle.timestamp,
                )
            )

        option_candles = option_cache[contract.instrument_id]

        entry_candle = next(
            (
                candle
                for candle in option_candles
                if (
                    candle.timestamp > signal_available
                    and local_date(candle.timestamp) == signal_day.isoformat()
                )
            ),
            None,
        )

        if entry_candle is None:
            counts["no_entry_candle"] += 1
            audit["outcome"] = "no_entry_candle"
            audit["contract"] = {
                "instrument_id": contract.instrument_id,
                "symbol": contract.symbol,
                "expiry_date": str(contract.expiry_date),
                "strike": contract.strike,
                "option_type": contract.option_type,
            }
            continue

        audit["contract"] = {
            "instrument_id": contract.instrument_id,
            "symbol": contract.symbol,
            "expiry_date": str(contract.expiry_date),
            "strike": contract.strike,
            "option_type": contract.option_type,
        }
        audit["entry_timestamp"] = int(entry_candle.timestamp)
        audit["entry_timestamp_local"] = local_dt(entry_candle.timestamp)
        audit["entry_price"] = float(entry_candle.close)

        entry = OptionEntry(
            event=event,
            contract=contract,
            signal_timestamp=signal_available,
            entry_timestamp=entry_candle.timestamp,
            underlying_price=all_bars[event.index].close,
            entry_price=entry_candle.close,
            lifecycle_action=decision.action,
            lifecycle_reason=decision.reason,
        )

        manager = OptionTradeLifecycle()

        try:
            # Both CE buys and PE buys are long option-premium positions.
            position = manager.create_position(
                strategy_id=event.strategy_id.value,
                direction=OptionTradeDirection.LONG,
                symbol=contract.symbol,
                entry_price=entry.entry_price,
            )
        except ValueError as exc:
            if str(exc) != "Allocation cannot purchase one complete lot":
                raise
            counts["allocation_rejected"] += 1
            audit["outcome"] = "allocation_rejected"
            continue

        trade_candles = tuple(
            candle
            for candle in option_candles
            if (
                candle.timestamp >= entry.entry_timestamp
                and candle.timestamp <= simulation_end
            )
        )

        if not trade_candles:
            counts["no_entry_candle"] += 1
            audit["outcome"] = "no_entry_candle"
            continue

        state = TradeState(
            entry=entry,
            position=position,
            lifecycle=manager,
            signal_direction=event.direction.value,
            candles=trade_candles,
            next_index=1,
            audit_id=audit_id,
        )

        audit["outcome"] = "entered"
        active.append(state)

    # Finish active positions through the final sample-day session close.
    for state in active:
        advance_trade(
            state=state,
            through_timestamp=simulation_end,
            bars=all_bars,
            kama_results=kama_results,
            underlying_completions=underlying_completions,
        )
        if state.position.closed:
            closed.append(state.managed())
            if state.audit_id is not None:
                event_audit[state.audit_id]["outcome"] = "closed"
                event_audit[state.audit_id]["exits"] = [
                    {
                        "timestamp": int(x.timestamp),
                        "timestamp_local": local_dt(x.timestamp),
                        "reason": x.reason.value,
                        "price": float(x.price),
                        "quantity": int(x.quantity),
                        "lots": int(x.lots),
                        "pnl": float(x.pnl),
                    }
                    for x in state.exits
                ]
                event_audit[state.audit_id]["total_pnl"] = float(
                    state.position.gross_pnl
                )

    open_trades = [
        state.managed()
        for state in active
        if not state.position.closed
    ]

    for state in active:
        if not state.position.closed and state.audit_id is not None:
            event_audit[state.audit_id]["outcome"] = "open"
            event_audit[state.audit_id]["total_pnl"] = float(state.position.gross_pnl)

    if len(event_audit) != len(selected_events):
        raise RuntimeError("Event audit length does not match selected events.")
    if any(record["outcome"] is None for record in event_audit):
        raise RuntimeError("At least one selected event was not assigned an audit outcome.")

    counts["closed"] = len(closed)
    counts["open"] = len(open_trades)

    return {
        "pipeline": pipeline,
        "selected_events": tuple(selected_events),
        "closed": tuple(closed),
        "open": tuple(open_trades),
        "counts": dict(counts),
        "simulation_end": simulation_end,
        "event_audit": tuple(event_audit),
    }


def max_concurrent_trades(trades: Sequence[ManagedOptionTrade]) -> int:
    timeline: list[tuple[int, int]] = []
    for trade in trades:
        entry_ready = trade.entry.entry_timestamp + ONE_MIN_SECONDS
        timeline.append((entry_ready, 1))
        if trade.result.closed and trade.result.exits:
            exit_ready = trade.result.exits[-1].timestamp + ONE_MIN_SECONDS
            timeline.append((exit_ready, -1))

    timeline.sort(key=lambda item: (item[0], item[1]))

    active = 0
    maximum = 0
    for _, delta in timeline:
        active += delta
        maximum = max(maximum, active)
    return maximum


def max_drawdown_by_exit_time(closed: Sequence[ManagedOptionTrade]) -> float:
    ordered = sorted(
        closed,
        key=lambda trade: (
            trade.result.exits[-1].timestamp
            if trade.result.exits
            else trade.entry.entry_timestamp,
            trade.entry.event.index,
        ),
    )
    equity = 0.0
    peak = 0.0
    maximum = 0.0
    for trade in ordered:
        equity += float(trade.result.total_pnl)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def make_report(
    *,
    all_bars: list[BacktestBar],
    sample_bars: list[BacktestBar],
    trigger_config: KTMITriggerStrategyConfig,
    result: dict,
) -> dict:
    closed = list(result["closed"])
    open_trades = list(result["open"])
    counts = result["counts"]
    pnls = [float(trade.result.total_pnl) for trade in closed]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    exit_counts = Counter()
    exit_pnl = defaultdict(float)
    daily_realized = defaultdict(float)

    for trade in closed:
        for exit_event in trade.result.exits:
            reason = exit_event.reason.value
            exit_counts[reason] += 1
            exit_pnl[reason] += float(exit_event.pnl)
            daily_realized[local_date(exit_event.timestamp)] += float(
                exit_event.pnl
            )

    accounted = (
        counts.get("closed", 0)
        + counts.get("open", 0)
        + counts.get("lifecycle_rejected", 0)
        + counts.get("allocation_rejected", 0)
        + counts.get("unresolved", 0)
        + counts.get("no_entry_candle", 0)
        + counts.get("outside_session", 0)
    )

    return {
        "sample": {
            "start": local_dt(sample_bars[0].timestamp),
            "end": local_dt(sample_bars[-1].timestamp),
            "bars_3m": len(sample_bars),
            "all_complete_3m_bars": len(all_bars),
            "ktmi_events_in_window": len(result["selected_events"]),
        },
        "trigger_config": {
            "momentum_enabled": trigger_config.momentum_only_enabled,
            "momentum_ce_trigger": trigger_config.momentum_long_trigger,
            "momentum_pe_trigger": trigger_config.momentum_short_trigger,
            "speed_sources_enabled": trigger_config.long_short_speed_enabled,
            "long_speed_ce_trigger": trigger_config.long_speed_trigger,
            "short_speed_pe_trigger": trigger_config.short_speed_trigger,
        },
        "event_accounting": {
            **counts,
            "accounted_events": accounted,
            "accounting_check": (
                "PASS"
                if accounted == len(result["selected_events"])
                else "FAIL"
            ),
        },
        "closed_performance": {
            "closed_trades": len(closed),
            "winners": len(wins),
            "losers": len(losses),
            "breakeven": sum(1 for p in pnls if p == 0),
            "win_rate_pct": (
                len(wins) / len(closed) * 100.0
                if closed else None
            ),
            "gross_profit": sum(wins),
            "gross_loss": -abs(sum(losses)),
            "net_gross_pnl": sum(pnls),
            "profit_factor": (
                sum(wins) / abs(sum(losses))
                if losses else None
            ),
            "average_trade_pnl": statistics.mean(pnls) if pnls else None,
            "median_trade_pnl": statistics.median(pnls) if pnls else None,
            "largest_win": max(pnls) if pnls else None,
            "largest_loss": min(pnls) if pnls else None,
            "max_drawdown": max_drawdown_by_exit_time(closed),
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
            "max_concurrent_trades": max_concurrent_trades(
                closed + open_trades
            ),
            "open_trade_symbols": [
                trade.entry.contract.symbol
                for trade in open_trades
            ],
        },
        "daily_realized_pnl": dict(sorted(daily_realized.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--momentum-ce-trigger", type=float, default=0.50)
    parser.add_argument("--momentum-pe-trigger", type=float, default=-0.50)
    parser.add_argument("--long-speed-ce-trigger", type=float, default=0.50)
    parser.add_argument("--short-speed-pe-trigger", type=float, default=0.50)
    parser.add_argument("--disable-momentum", action="store_true")
    parser.add_argument("--disable-speed-sources", action="store_true")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    all_bars = load_all_complete_3m_bars()
    sample_bars = select_last_days(all_bars, args.days)

    trigger_config = build_trigger_config(args)
    result = run_reference(
        all_bars=all_bars,
        sample_bars=sample_bars,
        trigger_config=trigger_config,
    )

    report = make_report(
        all_bars=all_bars,
        sample_bars=sample_bars,
        trigger_config=trigger_config,
        result=result,
    )

    print("=" * 100)
    print("KUNAL QUANT — PRE-PATCH NO-LOOKAHEAD REFERENCE BACKTEST V2")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()

    s = report["sample"]
    a = report["event_accounting"]
    p = report["closed_performance"]
    t = report["trigger_config"]

    print(f"Sample                   : {s['start']} -> {s['end']}")
    print(f"Sample 3M bars            : {s['bars_3m']:,}")
    print(f"All complete 3M bars      : {s['all_complete_3m_bars']:,}")
    print(f"KTMI events in window     : {s['ktmi_events_in_window']:,}")
    print()
    print("TRIGGER CONFIG")
    print(f"Momentum enabled           : {t['momentum_enabled']}")
    print(f"Momentum CE trigger        : {t['momentum_ce_trigger']}")
    print(f"Momentum PE trigger        : {t['momentum_pe_trigger']}")
    print(f"Speed sources enabled      : {t['speed_sources_enabled']}")
    print(f"Long Speed CE trigger      : {t['long_speed_ce_trigger']}")
    print(f"Short Speed PE trigger     : {t['short_speed_pe_trigger']}")
    print()
    print("EVENT ACCOUNTING")
    for label, key in (
        ("Closed trades", "closed"),
        ("Open trades", "open"),
        ("Lifecycle rejected", "lifecycle_rejected"),
        ("Allocation rejected", "allocation_rejected"),
        ("Unresolved", "unresolved"),
        ("No entry candle", "no_entry_candle"),
        ("Outside session", "outside_session"),
    ):
        print(f"{label:26s}: {a.get(key, 0):,}")
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
        print(f"{reason:20s} | exits={count:4d} | pnl={pnl:,.2f}")
    print()
    print("PORTFOLIO")
    print(
        f"Max concurrent trades    : "
        f"{report['portfolio']['max_concurrent_trades']:,}"
    )
    print()
    print("No canonical code was changed.")

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
