"""Multi-session real historical runner for Opening Breakout V2.

Research-only orchestration. Each trading date is scanned independently so the
first candle of one session can never become the setup candle for another.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Sequence
from zoneinfo import ZoneInfo

from backtest.broker_cost_model import calculate_options_trade_costs, fyers_options_profile
from backtest.fyers_option_candles import FyersOptionCandleLoader
from backtest.opening_breakout_v2_option_integration import (
    ResolvedOpeningBreakoutTrade,
    run_opening_breakout_trade,
)
from backtest.opening_breakout_v2_signal_engine import (
    OpeningBreakoutEvent,
    SignalSeries,
    scan_series,
)
from backtest.portfolio_accounting import EquityPoint, build_equity_curve
from execution.opening_breakout_v2_execution import V2ExecutionPolicy
from research.opening_breakout_1m_v2 import Candle, IndicatorSnapshot, V2Config
from strategies.option_contract_resolver import OptionContractResolver

IST = ZoneInfo("Asia/Kolkata")
IndicatorProvider = Callable[[int, Candle], IndicatorSnapshot]


@dataclass(frozen=True)
class MultiSessionResult:
    sessions: int
    signals: int
    closed: int
    rejected: int
    rejection_reasons: tuple[tuple[str, int], ...]
    initial_capital: float
    ending_equity: float
    peak_equity: float
    max_drawdown: float
    max_drawdown_pct: float
    wins: int
    losses: int
    win_rate_pct: float
    gross_pnl: float
    total_costs: float
    net_pnl: float
    equity_curve: tuple[EquityPoint, ...]
    trades: tuple[ResolvedOpeningBreakoutTrade, ...]


def session_date(timestamp: int):
    return datetime.fromtimestamp(timestamp, tz=IST).date()


def group_candles_by_session(
    candles: Sequence[Candle],
) -> tuple[tuple[object, tuple[Candle, ...]], ...]:
    grouped: dict[object, list[Candle]] = {}
    for candle in sorted(candles, key=lambda item: item.timestamp):
        grouped.setdefault(session_date(candle.timestamp), []).append(candle)
    return tuple((day, tuple(items)) for day, items in sorted(grouped.items()))


def run_multi_session_backtest(
    *,
    candles: Sequence[Candle],
    config: V2Config,
    resolver: OptionContractResolver,
    option_loader: FyersOptionCandleLoader,
    execution_policy: V2ExecutionPolicy,
    capital: float,
    indicator_provider: IndicatorProvider,
) -> MultiSessionResult:
    if capital <= 0:
        raise ValueError("capital must be positive")

    trades: list[ResolvedOpeningBreakoutTrade] = []
    equity_inputs: list[tuple[int, float, float]] = []
    current_capital = float(capital)
    sessions = 0
    signals = 0
    rejection_counts: dict[str, int] = {}

    def record_rejection(reason: str) -> None:
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    for _, session_candles in group_candles_by_session(candles):
        if len(session_candles) < 2:
            continue

        sessions += 1
        series = SignalSeries(
            symbol="NIFTY-V2-CANDIDATE",
            option_type="CE",
            strike=0,
            lot_size=1,
            candles=session_candles,
        )
        _, events = scan_series(
            series,
            config=config,
            indicator_provider=indicator_provider,
        )
        signals += len(events)

        for event in events:
            force_exit = int(
                datetime.fromtimestamp(event.trigger_timestamp, tz=IST)
                .replace(hour=15, minute=15, second=0, microsecond=0)
                .timestamp()
            )
            try:
                trade = run_opening_breakout_trade(
                    event=event,
                    underlying_candles=session_candles,
                    resolver=resolver,
                    option_loader=option_loader,
                    config=config,
                    execution_policy=execution_policy,
                    capital=current_capital,
                    force_exit_timestamp=force_exit,
                )
            except Exception as exc:
                rejection = (
                    f"EXCEPTION:{type(exc).__name__}:{exc}"
                    f"|signal_ts={event.trigger_timestamp}"
                    f"|setup_ts={event.setup_timestamp}"
                    f"|direction={event.direction}"
                )
                record_rejection(rejection)
                continue

            trades.append(trade)
            if trade.status != "CLOSED":
                record_rejection(trade.status)
                continue

            breakdown = calculate_options_trade_costs(
                entry_price=trade.entry.price,
                exit_price=trade.exit.price,
                quantity=trade.quantity,
                profile=fyers_options_profile(
                    session_date(trade.event.trigger_timestamp)
                ),
                gross_pnl=trade.gross_pnl,
            )
            equity_inputs.append(
                (
                    trade.exit.timestamp or trade.event.trigger_timestamp,
                    trade.gross_pnl,
                    breakdown.total_cost,
                )
            )
            current_capital += trade.gross_pnl - breakdown.total_cost

    accounting = build_equity_curve(
        initial_capital=capital,
        trades=equity_inputs,
    )

    return MultiSessionResult(
        sessions=sessions,
        signals=signals,
        closed=len(equity_inputs),
        rejected=sum(rejection_counts.values()),
        rejection_reasons=tuple(sorted(rejection_counts.items())),
        initial_capital=accounting.initial_capital,
        ending_equity=accounting.ending_equity,
        peak_equity=accounting.peak_equity,
        max_drawdown=accounting.max_drawdown,
        max_drawdown_pct=accounting.max_drawdown_pct,
        wins=accounting.wins,
        losses=accounting.losses,
        win_rate_pct=accounting.win_rate_pct,
        gross_pnl=accounting.gross_pnl,
        total_costs=accounting.total_costs,
        net_pnl=accounting.net_pnl,
        equity_curve=accounting.equity_curve,
        trades=tuple(trades),
    )


__all__ = [
    "MultiSessionResult",
    "group_candles_by_session",
    "run_multi_session_backtest",
    "session_date",
]
