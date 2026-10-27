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
    # AUTO strike (owner 27 Oct 2026): (label, offset, contract) of ATM and ATM+1; the money decides at the entry.
    alternatives: tuple = ()


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
        strike_chooser: Callable[..., Any] | None = None,
    ) -> None:
        """``strike_chooser(candidates=[(label, offset, premium)], timestamp=...)`` -> StrikeChoice
        (strategies/funds_strike.py): picks ATM / ATM+1 for AUTO signals and applies the cost-per-lot cap."""
        self.resolver = resolver
        self.quote_cache = quote_cache
        self.coordinator = coordinator
        self.subscribe_symbols = subscribe_symbols
        self.underlying_symbol = underlying_symbol
        self.config = config or PendingEntryConfig()
        self.clock = clock or (lambda: datetime.now(MARKET_TZ))
        self.strike_chooser = strike_chooser
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
            handle.write(json.dumps(payload, separators=(",", ":")) + "\n")
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
                offset = int(getattr(signal, "strike_offset", 0) or 0)
                alternatives: tuple = ()
                if getattr(signal, "strike_auto", False):
                    from strategies.funds_strike import AUTO_CHOICES
                    alternatives = tuple(
                        (label, off, self.resolver.resolve(
                            **({"strike_offset": off} if off else {}), underlying_price=underlying_price,
                            entry_date=now.date(), direction=signal.direction))
                        for label, off in AUTO_CHOICES)
                    contract = alternatives[0][2]
                    self.subscribe_symbols([c.symbol for _l, _o, c in alternatives])
                else:
                    contract = self.resolver.resolve(
                        **({"strike_offset": offset} if offset else {}),
                        underlying_price=underlying_price,
                        entry_date=now.date(),
                        direction=signal.direction,
                    )
                    self.subscribe_symbols([contract.symbol])
                pending = PendingEntry(signal, underlying_price, contract, decision_ts, alternatives)
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
            timed_out = decision_ts - pending.queued_at > self.config.timeout_seconds
            if pending.alternatives or self.strike_chooser is not None:
                picked = self._choose(pending, decision_ts, timed_out)
                if picked is None:                        # still waiting for prices
                    continue
                if isinstance(picked, PendingEntryEvent):  # no trade within the money rules
                    with self._lock:
                        self._pending.pop(key, None)
                        self._completed.add(key)
                        self._record(picked)
                    results.append(picked)
                    continue
                pending, quote = picked
                results.append(self._enter(key, pending, quote, decision_ts))
                continue
            if timed_out:
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
            results.append(self._enter(key, pending, quote, decision_ts))
        return tuple(results)

    def _fresh(self, symbol: str, decision_ts: int):
        try:
            return self.quote_cache.get_quote(symbol, decision_timestamp=decision_ts,
                                              max_exchange_age_seconds=self.config.max_quote_age_seconds,
                                              max_receive_age_seconds=self.config.max_receive_age_seconds)
        except (LookupError, ValueError):
            return None

    def _choose(self, pending: PendingEntry, decision_ts: int, timed_out: bool):
        """None = keep waiting; a PendingEntryEvent = no trade; (pending for the chosen strike, its quote) = enter.
        AUTO waits until BOTH strikes have a fresh price (or the time is up, then uses the ones it has)."""
        options = pending.alternatives or (("", int(getattr(pending.signal, "strike_offset", 0) or 0),
                                             pending.contract),)
        quotes = {label: self._fresh(c.symbol, decision_ts) for label, _o, c in options}
        have = [(label, off, c) for label, off, c in options if quotes[label] is not None]
        if not have or (len(have) < len(options) and not timed_out):
            if timed_out:
                return PendingEntryEvent(pending.signal, "TIMED_OUT", pending.contract.symbol, decision_ts,
                                         f"No valid option quote within {self.config.timeout_seconds}s.")
            return None
        if self.strike_chooser is None:                              # AUTO without a chooser: plain ATM
            label, off, contract = have[0]
        else:
            choice = self.strike_chooser(
                candidates=[(label or "strike", off, float(quotes[label]["lp"])) for label, off, _c in have],
                timestamp=decision_ts)
            if choice.label is None:
                return PendingEntryEvent(pending.signal, "REJECTED", pending.contract.symbol, decision_ts,
                                         choice.reason)
            label, off, contract = next(h for h in have if h[1] == choice.offset)
            if pending.alternatives:                                 # journal why ATM or ATM+1
                with self._lock:
                    self._record(PendingEntryEvent(pending.signal, "STRIKE_CHOSEN", contract.symbol, decision_ts,
                                                   choice.reason))
        signal = pending.signal
        if pending.alternatives:
            from dataclasses import replace
            signal = replace(signal, strike_offset=off, reason=f"{signal.reason}={label}")
        chosen = PendingEntry(signal, pending.underlying_price, contract, pending.queued_at, pending.alternatives)
        return chosen, quotes[label]

    def _enter(self, key, pending: PendingEntry, quote, decision_ts: int) -> PendingEntryEvent:
        try:
            attempt = self.coordinator.process_signal(
                signal=pending.signal,
                underlying_price=pending.underlying_price,
                option_quote=quote,
                decision_timestamp=decision_ts,
            )
        except (LookupError, ValueError, TypeError, KeyError) as exc:
            event = PendingEntryEvent(pending.signal, "REJECTED", pending.contract.symbol, decision_ts, str(exc))
        else:
            status = "ENTERED" if attempt.trade is not None else "REJECTED"
            event = PendingEntryEvent(pending.signal, status, pending.contract.symbol, decision_ts,
                                      attempt.rejection_reason, attempt)
        with self._lock:
            self._pending.pop(key, None)
            self._completed.add(key)
            self._record(event)
        return event

    def pending(self) -> tuple[PendingEntry, ...]:
        with self._lock:
            return tuple(self._pending.values())


__all__ = [
    "PendingEntry", "PendingEntryConfig", "PendingEntryEvent",
    "PendingEntryOrchestrator",
]
