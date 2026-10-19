"""Pending-signal orchestration for buyer-only FYERS paper entries.

Resolves and subscribes an option when a completed signal arrives, then waits
for a fresh exchange-timestamped quote before asking the paper coordinator to
open a simulated position. No broker order API is called.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import threading
from typing import Any, Callable
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE
from market_data.fyers_quote_cache import FyersQuoteCache
from paper_trading.coordinator import PaperEntryAttempt, PaperExecutionCoordinator
from paper_trading.signals import PaperSignal
from strategies.option_contract_resolver import OptionContractResolver, ResolvedOptionContract


MARKET_TZ = ZoneInfo(TIMEZONE)


@dataclass(frozen=True)
class PendingEntryConfig:
    timeout_seconds: int = 8
    max_quote_age_seconds: int = 5
    max_receive_age_seconds: float = 5.0
    journal_path: str | Path = "data/paper_trading/pending_entries.csv"
    state_path: str | Path | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1")
        if self.max_quote_age_seconds < 0 or self.max_receive_age_seconds < 0:
            raise ValueError("Quote age limits cannot be negative")


@dataclass(frozen=True)
class PendingEntry:
    signal: PaperSignal
    underlying_price: float
    contract: ResolvedOptionContract
    queued_at: int


@dataclass(frozen=True)
class PendingEntryEvent:
    signal: PaperSignal
    status: str
    symbol: str | None
    timestamp: int
    reason: str | None = None
    attempt: PaperEntryAttempt | None = None


class PendingEntryOrchestrator:
    """Queue signals until the resolved option has a valid fresh market quote.

    Inject this object's on_signals into FyersPaperFeed.on_signals and its
    on_tick into FyersPaperFeed.on_tick. The feed updates the quote cache before
    calling on_tick, allowing option ticks to release pending entries.
    """

    def __init__(
        self,
        *,
        resolver: OptionContractResolver,
        quote_cache: FyersQuoteCache,
        coordinator: PaperExecutionCoordinator,
        subscribe_symbols: Callable[[list[str]], Any],
        underlying_symbol: str = "NSE:NIFTY50-INDEX",
        config: PendingEntryConfig | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.resolver = resolver
        self.quote_cache = quote_cache
        self.coordinator = coordinator
        self.subscribe_symbols = subscribe_symbols
        self.underlying_symbol = underlying_symbol
        self.config = config or PendingEntryConfig()
        self.clock = clock or (lambda: datetime.now(MARKET_TZ))
        self._lock = threading.RLock()
        self._pending: dict[tuple[str, str, int, int], PendingEntry] = {}
        self._completed: set[tuple[str, str, int, int]] = set()
        self.events: list[PendingEntryEvent] = []
        self._ensure_journal()
        self._load_processed_keys()

    @staticmethod
    def _key(signal: PaperSignal) -> tuple[str, str, int, int]:
        strategy = getattr(signal.strategy_id, "value", signal.strategy_id)
        return (str(strategy), str(signal.direction), int(signal.timestamp), int(signal.index))

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("Pending-entry clock must return a timezone-aware datetime")
        return value.astimezone(MARKET_TZ)

    def _ensure_journal(self) -> None:
        path = Path(self.config.journal_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.stat().st_size == 0:
            with path.open("a", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerow(
                    ["recorded_at", "signal_timestamp", "strategy_id", "direction",
                     "option_symbol", "status", "event_timestamp", "reason"]
                )

    def _state_file(self) -> Path:
        if self.config.state_path is not None:
            return Path(self.config.state_path)
        return Path(self.config.journal_path).with_suffix(".signals.jsonl")

    def _load_processed_keys(self) -> None:
        """Fail closed on restart: never replay a signal already journaled.

        Pending signals are intentionally not resumed because their quote age,
        subscription state, and queued-at deadline cannot be trusted after a
        process restart. Their key is consumed to prevent accidental re-entry.
        """
        path = self._state_file()
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    payload = json.loads(line)
                    raw_key = payload.get("key")
                    if isinstance(raw_key, list) and len(raw_key) == 4:
                        self._completed.add(
                            (str(raw_key[0]), str(raw_key[1]), int(raw_key[2]), int(raw_key[3]))
                        )
                except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                    # Ignore a malformed/torn final line; CSV remains the audit log.
                    continue

    def _persist_signal_key(self, signal: PaperSignal, status: str) -> None:
        path = self._state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"key": list(self._key(signal)), "status": status,
                   "recorded_at": self._now().isoformat(timespec="seconds")}
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":")) + "\\n")
            handle.flush()

    def _record(self, event: PendingEntryEvent) -> None:
        self.events.append(event)
        self._persist_signal_key(event.signal, event.status)
        strategy = getattr(event.signal.strategy_id, "value", event.signal.strategy_id)
        path = Path(self.config.journal_path)
        with path.open("a", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow([
                self._now().isoformat(timespec="seconds"),
                event.signal.timestamp, strategy, event.signal.direction,
                event.symbol or "", event.status, event.timestamp, event.reason or "",
            ])
            handle.flush()

    def on_signals(self, signals: tuple[PaperSignal, ...] | list[PaperSignal]) -> tuple[PendingEntryEvent, ...]:
        """Resolve contracts, subscribe them, and queue signals for fresh quotes."""
        created: list[PendingEntryEvent] = []
        for signal in signals:
            key = self._key(signal)
            with self._lock:
                if key in self._pending or key in self._completed:
                    continue
            now = self._now()
            decision_ts = int(now.timestamp())
            if decision_ts <= int(signal.timestamp):
                event = PendingEntryEvent(signal, "REJECTED", None, decision_ts,
                                          "Decision time is not after signal timestamp.")
                with self._lock:
                    self._completed.add(key)
                    self._record(event)
                created.append(event)
                continue
            try:
                underlying_quote = self.quote_cache.get_quote(
                    self.underlying_symbol,
                    decision_timestamp=decision_ts,
                    max_exchange_age_seconds=self.config.max_quote_age_seconds,
                    max_receive_age_seconds=self.config.max_receive_age_seconds,
                )
                underlying_price = float(underlying_quote["lp"])
                contract = self.resolver.resolve(
                    underlying_price=underlying_price,
                    entry_date=now.date(),
                    direction=signal.direction,
                )
                self.subscribe_symbols([contract.symbol])
                pending = PendingEntry(signal, underlying_price, contract, decision_ts)
                with self._lock:
                    if key in self._pending or key in self._completed:
                        continue
                    self._pending[key] = pending
                event = PendingEntryEvent(signal, "PENDING", contract.symbol, decision_ts)
            except (LookupError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error) as exc:
                event = PendingEntryEvent(signal, "REJECTED", None, decision_ts, str(exc))
                with self._lock:
                    self._completed.add(key)
            with self._lock:
                self._record(event)
            created.append(event)
        return tuple(created)

    def on_tick(self, _message: Any = None) -> tuple[PendingEntryEvent, ...]:
        """Try pending entries after each tick has updated the quote cache."""
        now = self._now()
        decision_ts = int(now.timestamp())
        results: list[PendingEntryEvent] = []
        with self._lock:
            items = list(self._pending.items())
        for key, pending in items:
            if decision_ts - pending.queued_at > self.config.timeout_seconds:
                event = PendingEntryEvent(
                    pending.signal, "TIMED_OUT", pending.contract.symbol, decision_ts,
                    f"No valid option quote within {self.config.timeout_seconds}s.",
                )
                with self._lock:
                    self._pending.pop(key, None)
                    self._completed.add(key)
                    self._record(event)
                results.append(event)
                continue
            try:
                quote = self.quote_cache.get_quote(
                    pending.contract.symbol,
                    decision_timestamp=decision_ts,
                    max_exchange_age_seconds=self.config.max_quote_age_seconds,
                    max_receive_age_seconds=self.config.max_receive_age_seconds,
                )
            except (LookupError, ValueError):
                continue
            try:
                attempt = self.coordinator.process_signal(
                    signal=pending.signal,
                    underlying_price=pending.underlying_price,
                    option_quote=quote,
                    decision_timestamp=decision_ts,
                )
            except (LookupError, ValueError, TypeError, KeyError) as exc:
                event = PendingEntryEvent(
                    pending.signal, "REJECTED", pending.contract.symbol, decision_ts, str(exc)
                )
            else:
                status = "ENTERED" if attempt.trade is not None else "REJECTED"
                event = PendingEntryEvent(
                    pending.signal, status, pending.contract.symbol, decision_ts,
                    attempt.rejection_reason, attempt,
                )
            with self._lock:
                self._pending.pop(key, None)
                self._completed.add(key)
                self._record(event)
            results.append(event)
        return tuple(results)

    def pending(self) -> tuple[PendingEntry, ...]:
        with self._lock:
            return tuple(self._pending.values())


__all__ = [
    "PendingEntry", "PendingEntryConfig", "PendingEntryEvent",
    "PendingEntryOrchestrator",
]
