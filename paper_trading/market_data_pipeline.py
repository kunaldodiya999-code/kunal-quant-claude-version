"""Paper-mode market-data pipeline; no contract selection or order execution."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE
from market_data.live_ticks import LiveMinuteBarBuilder
from market_data.resampling import SUPPORTED_MINUTES, Candle, DerivedBar, aggregate_day
from paper_trading.engine import PaperEngineConfig
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.signals import PaperSignal, evaluate_latest_paper_signals


MARKET_TZ = ZoneInfo(TIMEZONE)
SignalEvaluator = Callable[..., list[PaperSignal]]
SUPPORTED_RESOLUTIONS = (1, *SUPPORTED_MINUTES)   # 1, 3, 5, 10, 15, 30, 60 minutes


def bar_close_timestamp(bar_timestamp: int, resolution_minutes: int) -> int:
    """Moment a bar is complete: its end, or the 15:30 session close for the
    day's last, shorter bar (e.g. the 60-minute bar that starts at 15:15)."""
    local = datetime.fromtimestamp(bar_timestamp, tz=MARKET_TZ)
    session_close = int(local.replace(hour=15, minute=30, second=0, microsecond=0).timestamp())
    return min(int(bar_timestamp) + resolution_minutes * 60, session_close)


class PaperMarketDataPipeline:
    """Convert socket ticks into completed bars and evaluate paper signals.

    This pipeline deliberately stops at signal generation. It never resolves
    option contracts, opens positions, or sends broker orders. The caller must
    supply FYERS SymbolUpdate messages to on_message().
    """

    def __init__(
        self,
        *,
        resolution_minutes: int = 3,
        paper_config: PaperEngineConfig | None = None,
        signal_evaluator: SignalEvaluator = evaluate_latest_paper_signals,
        recorder: PaperTradeRecorder | None = None,
    ) -> None:
        if resolution_minutes not in SUPPORTED_RESOLUTIONS:
            raise ValueError(f"resolution_minutes must be one of {SUPPORTED_RESOLUTIONS}")
        self.resolution_minutes = resolution_minutes
        self.paper_config = paper_config or PaperEngineConfig()
        self.signal_evaluator = signal_evaluator
        self.recorder = recorder
        self.tick_builder = LiveMinuteBarBuilder()
        self.minute_history: dict[str, list[Candle]] = {}
        self.signal_bar_history: dict[str, list[Candle | DerivedBar]] = {}
        self._last_signal_bar_timestamp: dict[str, int] = {}

    @staticmethod
    def _is_regular_session(candle: Candle) -> bool:
        local = datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ)
        return local.weekday() < 5 and (
            (local.hour, local.minute) >= (9, 15)
            and (local.hour, local.minute) <= (15, 29)
        )

    def on_message(self, message: Any) -> list[PaperSignal]:
        """Process one FYERS tick and return signals from newly completed bars."""
        completed_minutes = self.tick_builder.on_message(message)
        if not completed_minutes:
            return []

        symbol = message.get("symbol") if isinstance(message, dict) else None
        if not isinstance(symbol, str) or not symbol.strip():
            return []
        symbol = symbol.strip()
        signals: list[PaperSignal] = []

        for candle in completed_minutes:
            if not self._is_regular_session(candle):
                continue
            minutes = self.minute_history.setdefault(symbol, [])
            if minutes and candle.timestamp <= minutes[-1].timestamp:
                # A late tick should not rewind or duplicate signal history.
                continue
            minutes.append(candle)

            if self.resolution_minutes == 1:
                new_bars: list[Candle | DerivedBar] = [candle]
            else:
                local_day = datetime.fromtimestamp(
                    candle.timestamp, tz=MARKET_TZ
                ).date()
                day_candles = [
                    item for item in minutes
                    if datetime.fromtimestamp(item.timestamp, tz=MARKET_TZ).date() == local_day
                ]
                new_bars = [
                    bar for bar in aggregate_day(day_candles, self.resolution_minutes)
                    if bar.complete
                ]

            history = self.signal_bar_history.setdefault(symbol, [])
            last_seen = self._last_signal_bar_timestamp.get(symbol)
            unseen = [bar for bar in new_bars if last_seen is None or bar.timestamp > last_seen]
            if not unseen:
                continue

            # Feed each newly completed bar once, in order, so crossing logic
            # cannot be replayed repeatedly as later ticks arrive.
            for bar in unseen:
                history.append(bar)
                self._last_signal_bar_timestamp[symbol] = bar.timestamp
                close_ts = bar_close_timestamp(bar.timestamp, self.resolution_minutes)
                bar_signals = [
                    replace(signal, close_timestamp=close_ts)
                    for signal in self.signal_evaluator(history, paper_config=self.paper_config)
                ]
                if self.recorder is not None:
                    for signal in bar_signals:
                        self.recorder.record_signal(signal, symbol=symbol)
                signals.extend(bar_signals)

        return signals

    def seed_history(self, symbol: str, candles) -> int:
        """Load completed 1-minute candles from earlier sessions (and earlier today)
        before live ticks start, so KTMI has the same history as the chart.

        No signals are evaluated for seeded bars: history is context, not a trade.
        Must be called before the first live tick. Returns signal bars added.
        """
        symbol = symbol.strip()
        if self.minute_history.get(symbol):
            raise RuntimeError("seed_history must run before live ticks arrive.")
        ordered: dict[int, Candle] = {}
        for candle in candles:
            if self._is_regular_session(candle):
                ordered[int(candle.timestamp)] = candle
        minutes = [ordered[ts] for ts in sorted(ordered)]
        self.minute_history[symbol] = list(minutes)
        if self.resolution_minutes == 1:
            bars: list[Candle | DerivedBar] = list(minutes)
        else:
            by_day: dict = {}
            for candle in minutes:
                by_day.setdefault(datetime.fromtimestamp(candle.timestamp, tz=MARKET_TZ).date(), []).append(candle)
            bars = [
                bar for day in sorted(by_day)
                for bar in aggregate_day(by_day[day], self.resolution_minutes)
                if bar.complete
            ]
        self.signal_bar_history[symbol] = list(bars)
        if bars:
            self._last_signal_bar_timestamp[symbol] = bars[-1].timestamp
        return len(bars)

    def current_minute(self, symbol: str) -> Candle | None:
        """Expose a snapshot of the in-progress minute."""
        return self.tick_builder.current_minute(symbol)


__all__ = ["PaperMarketDataPipeline", "SUPPORTED_RESOLUTIONS", "bar_close_timestamp"]
