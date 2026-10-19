"""FYERS WebSocket runner for paper-mode underlying market data.

This adapter owns socket lifecycle and tick fan-out. It never invokes an
order API. Dynamic option subscriptions and entry execution are intentionally
left to a higher-level paper orchestrator so a signal is not lost while an
option subscription is warming up.
"""
from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Callable, Iterable

from api.fyers_client import FyersClient
from market_data.fyers_quote_cache import FyersQuoteCache
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.signals import PaperSignal


@dataclass(frozen=True)
class FyersFeedStatus:
    connected: bool
    subscribed_symbols: tuple[str, ...]
    messages_received: int
    messages_rejected_by_quote_cache: int
    last_error: str | None


class FyersPaperFeed:
    """Connect a FYERS data socket and route ticks to quote cache + signal pipeline.

    socket_factory is injectable for tests. Production defaults to the existing
    FyersClient.create_data_socket method. The connect callback subscribes
    configured underlying symbols using FYERS SymbolUpdate mode.
    """

    def __init__(
        self,
        *,
        client: FyersClient,
        pipeline: PaperMarketDataPipeline,
        quote_cache: FyersQuoteCache,
        underlying_symbols: Iterable[str],
        on_signals: Callable[[tuple[PaperSignal, ...]], None] | None = None,
        on_tick: Callable[[Any], None] | None = None,
        socket_factory: Callable[..., Any] | None = None,
    ) -> None:
        symbols = tuple(dict.fromkeys(str(s).strip() for s in underlying_symbols if str(s).strip()))
        if not symbols:
            raise ValueError("At least one underlying symbol is required.")
        self.client = client
        self.pipeline = pipeline
        self.quote_cache = quote_cache
        self.underlying_symbols = symbols
        self.on_signals = on_signals
        self.on_tick = on_tick
        self.socket_factory = socket_factory or client.create_data_socket
        self._lock = threading.RLock()
        self._socket: Any | None = None
        self._connected = False
        self._subscribed: set[str] = set()
        self._messages_received = 0
        self._last_error: str | None = None

    def start(self) -> None:
        """Create and connect the socket; returns control to the SDK's loop."""
        with self._lock:
            if self._socket is not None:
                raise RuntimeError("FYERS paper feed has already been started.")
            self._socket = self.socket_factory(
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_connect=self.on_connect,
                reconnect=True,
                lite_mode=False,
            )
            socket = self._socket
        socket.connect()

    def on_connect(self, *_args: Any, **_kwargs: Any) -> None:
        """Subscribe configured underlyings on connect/reconnect."""
        with self._lock:
            self._connected = True
            socket = self._socket
        if socket is None:
            self.on_error("FYERS connected callback fired before socket creation.")
            return
        try:
            socket.subscribe(symbols=list(self.underlying_symbols), data_type="SymbolUpdate")
            with self._lock:
                self._subscribed.update(self.underlying_symbols)
        except Exception as exc:
            self.on_error(exc)

    def subscribe_symbols(self, symbols: Iterable[str]) -> tuple[str, ...]:
        """Subscribe additional option symbols without duplicate requests.

        Intended for a future coordinator that queues a signal while the option
        feed warms up. Returns only symbols newly requested from the socket.
        """
        normalized = tuple(dict.fromkeys(str(s).strip() for s in symbols if str(s).strip()))
        with self._lock:
            socket = self._socket
            if socket is None or not self._connected:
                raise RuntimeError("Cannot subscribe before the FYERS socket is connected.")
            new_symbols = tuple(s for s in normalized if s not in self._subscribed)
            if not new_symbols:
                return ()
            self._subscribed.update(new_symbols)
        try:
            socket.subscribe(symbols=list(new_symbols), data_type="SymbolUpdate")
        except Exception as exc:
            with self._lock:
                self._subscribed.difference_update(new_symbols)
            self.on_error(exc)
            raise
        return new_symbols

    def on_message(self, message: Any) -> None:
        """Cache valid quote data and pass the original tick to signal pipeline."""
        with self._lock:
            self._messages_received += 1
        self.quote_cache.update(message)
        signals = self.pipeline.on_message(message)
        if signals and self.on_signals is not None:
            self.on_signals(tuple(signals))
        # Run after signal callbacks so newly queued option contracts can also
        # be checked against this tick; option ticks then release pending entries.
        if self.on_tick is not None:
            self.on_tick(message)

    def on_error(self, error: Any, *_args: Any, **_kwargs: Any) -> None:
        with self._lock:
            self._last_error = str(error)

    def on_close(self, *_args: Any, **_kwargs: Any) -> None:
        with self._lock:
            self._connected = False

    def close(self) -> None:
        """Close the socket when supported by the installed SDK."""
        with self._lock:
            socket = self._socket
            self._connected = False
        if socket is not None:
            close = getattr(socket, "close", None)
            if callable(close):
                close()

    def status(self) -> FyersFeedStatus:
        with self._lock:
            return FyersFeedStatus(
                connected=self._connected,
                subscribed_symbols=tuple(sorted(self._subscribed)),
                messages_received=self._messages_received,
                messages_rejected_by_quote_cache=self.quote_cache.rejected_messages,
                last_error=self._last_error,
            )


__all__ = ["FyersFeedStatus", "FyersPaperFeed"]
