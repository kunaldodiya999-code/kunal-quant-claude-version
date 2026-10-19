"""Convert FYERS SymbolUpdate ticks into completed one-minute candles.

This adapter is deliberately independent of sockets, signals, option selection,
and order execution. It does not synthesize candles for minutes with no ticks.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

from market_data.resampling import Candle


@dataclass
class _OpenMinute:
    timestamp: int
    open: float
    high: float
    low: float
    close: float


class LiveMinuteBarBuilder:
    """Build completed 1-minute OHLC candles from FYERS SymbolUpdate messages.

    Exchange timestamps are preferred. FYERS packet variants may expose
    last_traded_time, timestamp, or exch_feed_time. Messages without a usable
    timestamp or finite positive LTP are ignored. The caller receives a candle
    only after a later minute arrives; the still-forming candle is never emitted.
    """

    def __init__(self) -> None:
        self._open_by_symbol: dict[str, _OpenMinute] = {}

    @staticmethod
    def _timestamp_seconds(message: Mapping[str, Any]) -> int | None:
        # Prefer trade time where supplied. The existing WebSocket test confirms
        # that index feed packets can instead contain exch_feed_time only.
        raw = message.get("last_traded_time")
        if raw in (None, "", 0, "0"):
            raw = message.get("timestamp")
        if raw in (None, "", 0, "0"):
            raw = message.get("exch_feed_time")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        # Be tolerant of millisecond epoch timestamps.
        if value >= 1_000_000_000_000:
            value /= 1000
        return int(value)

    @staticmethod
    def _last_price(message: Mapping[str, Any]) -> float | None:
        try:
            value = float(message.get("ltp"))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value) or value <= 0:
            return None
        return value

    def on_message(self, message: Any) -> list[Candle]:
        """Consume one socket message and return any newly completed candles."""
        if not isinstance(message, Mapping):
            return []
        symbol = message.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            return []

        timestamp = self._timestamp_seconds(message)
        price = self._last_price(message)
        if timestamp is None or price is None:
            return []

        minute = (timestamp // 60) * 60
        symbol = symbol.strip()
        current = self._open_by_symbol.get(symbol)

        if current is None:
            self._open_by_symbol[symbol] = _OpenMinute(
                timestamp=minute, open=price, high=price, low=price, close=price
            )
            return []

        # Ignore late/out-of-order ticks; never revise an emitted candle.
        if minute < current.timestamp:
            return []

        if minute == current.timestamp:
            current.high = max(current.high, price)
            current.low = min(current.low, price)
            current.close = price
            return []

        completed = Candle(
            timestamp=current.timestamp,
            open=current.open,
            high=current.high,
            low=current.low,
            close=current.close,
            volume=None,
            open_interest=None,
        )
        self._open_by_symbol[symbol] = _OpenMinute(
            timestamp=minute, open=price, high=price, low=price, close=price
        )
        # No candles are filled for minutes without ticks. The regular-session
        # resampler remains responsible for identifying gaps/incomplete bars.
        return [completed]

    def current_minute(self, symbol: str) -> Candle | None:
        """Return a snapshot of the still-forming candle, if present."""
        current = self._open_by_symbol.get(symbol)
        if current is None:
            return None
        return Candle(
            timestamp=current.timestamp,
            open=current.open,
            high=current.high,
            low=current.low,
            close=current.close,
            volume=None,
            open_interest=None,
        )
