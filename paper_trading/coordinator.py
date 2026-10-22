"""Coordinator connecting completed KTMI signals to paper entries.

All market-data and quote access is injected by the caller. No broker order
API is imported or called. This coordinator does not treat a bar's bucket-start
timestamp as the actual quote-decision time: callers must pass the timestamp
at which the quote was observed/entry evaluated.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from paper_trading.controls import Segment
from paper_trading.entry_adapter import PaperEntryAdapter, PaperEntryCandidate
from paper_trading.engine import PaperTradeRecord, PaperTradingEngine
from paper_trading.signals import PaperSignal


@dataclass(frozen=True)
class PaperEntryAttempt:
    signal: PaperSignal
    candidate: PaperEntryCandidate | None
    trade: PaperTradeRecord | None
    rejection_reason: str | None


class PaperExecutionCoordinator:
    """Resolve, validate, deduplicate and open simulated option positions."""

    def __init__(
        self,
        *,
        adapter: PaperEntryAdapter,
        engine: PaperTradingEngine,
        controls: Any = None,
        segment: Segment = Segment.FNO,
    ) -> None:
        self.adapter = adapter
        self.engine = engine
        # Optional SessionControls: entry window, daily loss cap and kill switch.
        self.controls = controls
        self.segment = Segment(segment)   # NIFTY options trade in NSE & BSE F&O
        self._seen_signals: set[tuple[str, str, int, int]] = set()
        # Signals journaled before a restart, keyed without the bar index
        # because bar indexes are not stable across a rebuilt history.
        self._restored_bar_keys: set[tuple[str, str, int]] = set()

    def restore_seen_signals(self, keys) -> None:
        """Remember signals journaled before a restart so they are never re-entered."""
        self._restored_bar_keys.update(
            (str(s), str(d), int(t)) for s, d, t in keys
        )

    @staticmethod
    def _key(signal: PaperSignal) -> tuple[str, str, int, int]:
        strategy = getattr(signal.strategy_id, "value", signal.strategy_id)
        return (str(strategy), str(signal.direction), int(signal.timestamp), int(signal.index))

    def process_signal(
        self,
        *,
        signal: PaperSignal,
        underlying_price: float,
        option_quote: Mapping[str, Any],
        decision_timestamp: int,
    ) -> PaperEntryAttempt:
        """Attempt exactly one paper entry; repeated signal IDs are rejected."""
        key = self._key(signal)
        if int(decision_timestamp) <= int(signal.timestamp):
            return PaperEntryAttempt(
                signal=signal, candidate=None, trade=None,
                rejection_reason="Entry decision must occur after the signal timestamp.",
            )
        if (key[0], key[1], key[2]) in self._restored_bar_keys:
            return PaperEntryAttempt(
                signal=signal, candidate=None, trade=None,
                rejection_reason="Duplicate signal already processed before restart.",
            )
        if key in self._seen_signals:
            return PaperEntryAttempt(
                signal=signal, candidate=None, trade=None,
                rejection_reason="Duplicate signal already processed.",
            )
        # Mark before validation: a rejected signal must not be retried on each
        # tick with the same signal. A new signal event is required.
        self._seen_signals.add(key)
        if self.controls is not None:
            blocked = self.controls.entry_block_reason(int(decision_timestamp), self.segment)
            if blocked:
                return PaperEntryAttempt(
                    signal=signal, candidate=None, trade=None, rejection_reason=blocked,
                )
        try:
            candidate = self.adapter.prepare_entry(
                signal=signal,
                underlying_price=underlying_price,
                option_quote=option_quote,
                entry_timestamp=decision_timestamp,
            )
            trade = self.adapter.open_position(self.engine, candidate)
            if trade is None:
                return PaperEntryAttempt(
                    signal=signal, candidate=candidate, trade=None,
                    rejection_reason="Strategy disabled or already has an open position.",
                )
            return PaperEntryAttempt(
                signal=signal, candidate=candidate, trade=trade,
                rejection_reason=None,
            )
        except (ValueError, TypeError, KeyError) as exc:
            return PaperEntryAttempt(
                signal=signal, candidate=None, trade=None,
                rejection_reason=str(exc),
            )


__all__ = ["PaperEntryAttempt", "PaperExecutionCoordinator"]
