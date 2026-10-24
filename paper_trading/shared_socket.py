"""One FYERS market-data connection shared by several index sessions.

Each paper session (NIFTY, BANKNIFTY, SENSEX) builds its own feed and asks
for a socket. They all get a light *virtual* socket; the first one to connect
opens the single real FYERS connection. Every incoming message is delivered
only to the virtual sockets that subscribed that symbol. Connect/reconnect
events reach all of them, so each re-subscribes its own symbols.
"""

from __future__ import annotations

import threading
from typing import Any, Callable


class _VirtualSocket:
    def __init__(self, hub: "SharedSocketHub", callbacks: dict) -> None:
        self.hub, self.callbacks = hub, callbacks
        self.symbols: set[str] = set()

    def connect(self) -> None:
        self.hub._connect(self)

    def subscribe(self, symbols, data_type: str = "SymbolUpdate") -> None:
        new = [s for s in symbols if s not in self.symbols]
        self.symbols.update(symbols)
        if new:
            self.hub._subscribe(new, data_type)

    def close(self) -> None:
        self.hub._release(self)


class SharedSocketHub:
    def __init__(self, real_factory: Callable[..., Any]) -> None:
        self.real_factory = real_factory
        self.real: Any = None
        self.connected = False
        self.connect_count = 0
        self.sockets: list[_VirtualSocket] = []
        self._lock = threading.RLock()

    # what build_paper_session(socket_factory=...) calls
    def factory(self, **callbacks) -> _VirtualSocket:
        socket = _VirtualSocket(self, callbacks)
        with self._lock:
            self.sockets.append(socket)
        return socket

    def _connect(self, socket: _VirtualSocket) -> None:
        with self._lock:
            if self.real is None:
                self.real = self.real_factory(
                    on_message=self._on_message, on_error=self._on_error, on_close=self._on_close,
                    on_connect=self._on_connect, reconnect=True, lite_mode=False,
                )
                real = self.real
            else:
                real = None
            already = self.connected
        if real is not None:
            real.connect()
        elif already:
            self._call(socket, "on_connect")

    def _subscribe(self, symbols, data_type) -> None:
        if self.real is not None:
            self.real.subscribe(symbols=list(symbols), data_type=data_type)

    def _release(self, socket: _VirtualSocket) -> None:
        with self._lock:
            if socket in self.sockets:
                self.sockets.remove(socket)
            last = not self.sockets
            real = self.real
        if last and real is not None:
            close = getattr(real, "close_connection", None) or getattr(real, "close", None)
            if callable(close):
                close()

    @staticmethod
    def _call(socket: _VirtualSocket, name: str, *args) -> None:
        callback = socket.callbacks.get(name)
        if callable(callback):
            callback(*args)

    def _on_connect(self, *args) -> None:
        with self._lock:
            self.connected = True
            self.connect_count += 1
            reconnect = self.connect_count > 1
            sockets = list(self.sockets)
            symbols = sorted({sym for socket in sockets for sym in socket.symbols})
        if reconnect and symbols and self.real is not None:
            # The FYERS SDK forgets every subscription when it reconnects: send them all again
            # (index prices AND the option contracts of open trades).
            self.real.subscribe(symbols=symbols, data_type="SymbolUpdate")
        for socket in sockets:
            self._call(socket, "on_connect")

    def _on_message(self, message, *args) -> None:
        symbol = message.get("symbol") if isinstance(message, dict) else None
        for socket in list(self.sockets):
            if symbol is None or symbol in socket.symbols:
                self._call(socket, "on_message", message)

    def _on_error(self, error, *args) -> None:
        for socket in list(self.sockets):
            self._call(socket, "on_error", error)

    def _on_close(self, *args) -> None:
        with self._lock:
            self.connected = False
        for socket in list(self.sockets):
            self._call(socket, "on_close")


__all__ = ["SharedSocketHub"]
