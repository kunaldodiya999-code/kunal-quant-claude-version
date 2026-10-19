"""
KUNAL QUANT — 3M NIFTY → OPTION ENTRY BRIDGE

Connects the validated 3-minute NIFTY signal boundary to the
existing option contract resolver and 1-minute option candles.

This module intentionally does NOT change:
- KTMI calculations
- Strategy A/B trigger definitions
- Option Contract Resolver V2
- Position Lifecycle V1
- Option Trade Management V1

Entry timing rule:
The option entry candle must have timestamp strictly greater than
the 3-minute NIFTY signal timestamp. Same-candle option entry is
rejected to prevent lookahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Sequence
from zoneinfo import ZoneInfo

from backtest.models import BacktestBar
from backtest.position_lifecycle import (
    ActivePosition,
    DEFAULT_POSITION_LIFECYCLE_CONFIG,
    SignalAction,
    evaluate_signal,
)
from strategies.option_contract_resolver import (
    OptionContractResolver,
    ResolvedOptionContract,
)
from strategies.ktmi_trigger_strategy import KTMITriggerEvent


TIMEZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class OptionCandle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class OptionEntry:
    event: KTMITriggerEvent
    contract: ResolvedOptionContract
    signal_timestamp: int
    entry_timestamp: int
    underlying_price: float
    entry_price: float
    lifecycle_action: SignalAction
    lifecycle_reason: str


OptionCandleLoader = Callable[
    [int, int, int],
    Iterable[OptionCandle],
]


def _entry_date(timestamp: int):
    return datetime.fromtimestamp(
        timestamp,
        tz=TIMEZONE,
    ).date()


def resolve_option_entries(
    *,
    bars: Sequence[BacktestBar],
    events: Sequence[KTMITriggerEvent],
    resolver: OptionContractResolver,
    option_candle_loader: OptionCandleLoader,
    active_positions: list[ActivePosition] | None = None,
) -> list[OptionEntry]:
    """
    Resolve eligible Strategy A/B events into actual option entries.

    Option candle loading is bounded around each signal. The loader
    receives (instrument_id, start_timestamp, end_timestamp).

    Existing lifecycle rules are applied before an option entry is
    accepted. Accepted positions are appended to a local active list
    so subsequent events respect the same lifecycle boundary.
    """
    if not bars:
        raise ValueError("bars cannot be empty")

    positions = list(active_positions or [])
    entries: list[OptionEntry] = []

    for event in events:
        if event.index < 0 or event.index >= len(bars):
            raise ValueError(
                f"event index {event.index} is outside the supplied bars"
            )

        bar = bars[event.index]
        signal_timestamp = bar.timestamp

        direction = event.direction.value
        strategy_id = event.strategy_id.value

        contract = resolver.resolve(
            underlying_price=bar.close,
            entry_date=_entry_date(signal_timestamp),
            direction=direction,
        )

        decision = evaluate_signal(
            strategy_id=strategy_id,
            direction=direction,
            symbol=contract.symbol,
            active_positions=positions,
            config=DEFAULT_POSITION_LIFECYCLE_CONFIG,
        )

        if decision.action != SignalAction.ENTER:
            continue

        candles = list(
            option_candle_loader(
                contract.instrument_id,
                signal_timestamp - 3600,
                signal_timestamp + 3600,
            )
        )

        next_candle = next(
            (
                candle
                for candle in sorted(candles, key=lambda item: item.timestamp)
                if candle.timestamp > signal_timestamp
            ),
            None,
        )

        if next_candle is None:
            continue

        entries.append(
            OptionEntry(
                event=event,
                contract=contract,
                signal_timestamp=signal_timestamp,
                entry_timestamp=next_candle.timestamp,
                underlying_price=bar.close,
                entry_price=next_candle.close,
                lifecycle_action=decision.action,
                lifecycle_reason=decision.reason,
            )
        )

        positions.append(
            ActivePosition(
                strategy_id=strategy_id,
                direction=direction,
                symbol=contract.symbol,
            )
        )

    return entries
