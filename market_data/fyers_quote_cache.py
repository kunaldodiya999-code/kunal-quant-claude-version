"""Thread-safe, timestamp-validating cache for FYERS market-data updates.

This is a feed adapter only: it does not connect sockets, subscribe symbols,
resolve contracts, or place orders. The socket callback should call update()
for every decoded FYERS SymbolUpdate. Consumers must request a quote by exact
symbol and supply the current epoch timestamp; stale or untimestamped quotes
are rejected rather than relabelled with local time.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import threading
import time
from typing import Any, Callable, Mapping


def _epoch_seconds(value: Any) -> int | None:
    """Normalize a valid seconds/milliseconds epoch value to integer seconds."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number <= 0:
        return None
    if number >= 1_000_000_000_000:
        number /= 1000
    return int(number)


@dataclass(frozen=True)
class FyersQuoteSnapshot:
    symbol: str
    last_price: float
    exchange_timestamp: int
    received_at: float

    def as_entry_quote(self) -> dict[str, Any]:
        """Return the quote keys consumed by PaperEntryAdapter."""
        return {
            "symbol": self.symbol,
            "lp": self.last_price,
            "exch_feed_time": self.exchange_timestamp,
        }


class FyersQuoteCache:
    """Keep the latest valid tick per exact FYERS symbol.

    The receive clock is injectable for deterministic tests. It records local
    receipt time separately from exchange time so a delayed feed cannot appear
    fresh merely because its packet was just received.
    """

    def __init__(self, *, receive_clock: Callable[[], float] = time.time) -> None:
        self._receive_clock = receive_clock
        self._lock = threading.RLock()
        self._quotes: dict[str, FyersQuoteSnapshot] = {}
        self.rejected_messages = 0

    @staticmethod
    def _timestamp(message: Mapping[str, Any]) -> int | None:
        for key in ("last_traded_time", "timestamp", "exch_feed_time"):
            raw = message.get(key)
            if raw not in (None, "", 0, "0"):
                timestamp = _epoch_seconds(raw)
                if timestamp is not None:
                    return timestamp
        return None

    @staticmethod
    def _price(message: Mapping[str, Any]) -> float | None:
        for key in ("ltp", "lp", "last_price"):
            raw = message.get(key)
            if raw in (None, ""):
                continue
            try:
                price = float(raw)
            except (TypeError, ValueError):
                return None
            return price if math.isfinite(price) and price > 0 else None
        return None

    def update(self, message: Any) -> bool:
        """Store one valid symbol update; return False for invalid packets."""
        if not isinstance(message, Mapping):
            self.rejected_messages += 1
            return False
        raw_symbol = message.get("symbol")
        symbol = raw_symbol.strip() if isinstance(raw_symbol, str) else ""
        timestamp = self._timestamp(message)
        price = self._price(message)
        if not symbol or timestamp is None or price is None:
            with self._lock:
                self.rejected_messages += 1
            return False

        received_at = float(self._receive_clock())
        if not math.isfinite(received_at):
            with self._lock:
                self.rejected_messages += 1
            return False

        snapshot = FyersQuoteSnapshot(
            symbol=symbol,
            last_price=price,
            exchange_timestamp=timestamp,
            received_at=received_at,
        )
        with self._lock:
            previous = self._quotes.get(symbol)
            # Never replace a newer exchange update with an older/out-of-order one.
            if previous is not None and timestamp < previous.exchange_timestamp:
                self.rejected_messages += 1
                return False
            self._quotes[symbol] = snapshot
        return True

    def get_quote(
        self,
        symbol: str,
        *,
        decision_timestamp: int,
        max_exchange_age_seconds: int = 5,
        max_receive_age_seconds: float = 5.0,
        now_received_at: float | None = None,
    ) -> dict[str, Any]:
        """Return a normalized quote only if exchange and local ages are valid."""
        if max_exchange_age_seconds < 0 or max_receive_age_seconds < 0:
            raise ValueError("Quote age limits cannot be negative.")
        with self._lock:
            snapshot = self._quotes.get(symbol)
        if snapshot is None:
            raise LookupError(f"No FYERS quote cached for {symbol}.")
        exchange_age = int(decision_timestamp) - snapshot.exchange_timestamp
        if exchange_age < 0:
            raise ValueError(f"FYERS quote for {symbol} is from the future.")
        if exchange_age > max_exchange_age_seconds:
            raise LookupError(
                f"FYERS quote for {symbol} is stale by exchange time "
                f"({exchange_age}s; maximum {max_exchange_age_seconds}s)."
            )
        received_now = float(self._receive_clock() if now_received_at is None else now_received_at)
        receive_age = received_now - snapshot.received_at
        if receive_age < 0:
            raise ValueError("Local quote receipt clock moved backwards.")
        if receive_age > max_receive_age_seconds:
            raise LookupError(
                f"FYERS quote for {symbol} is stale by local receipt age "
                f"({receive_age:.3f}s; maximum {max_receive_age_seconds:.3f}s)."
            )
        return snapshot.as_entry_quote()

    def snapshot(self, symbol: str) -> FyersQuoteSnapshot | None:
        """Return the immutable cached record for diagnostics, without freshness checks."""
        with self._lock:
            return self._quotes.get(symbol)

    def symbols(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._quotes))


__all__ = ["FyersQuoteCache", "FyersQuoteSnapshot"]
