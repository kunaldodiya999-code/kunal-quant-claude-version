"""Paper-mode market-data pipeline; no contract selection or order execution."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE
from market_data.live_ticks import LiveMinuteBarBuilder
from market_data.resampling import Candle, DerivedBar, aggregate_day
from paper_trading.engine import PaperEngineConfig
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.signals import PaperSignal, evaluate_latest_paper_signals


MARKET_TZ = ZoneInfo(TIMEZONE)
SignalEvaluator = Callable[..., list[PaperSignal]]


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
        if resolution_minutes not in (1, 3, 5):
            raise ValueError("resolution_minutes must be 1, 3, or 5")
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
                bar_signals = self.signal_evaluator(
                    history, paper_config=self.paper_config
                )
                if self.recorder is not None:
                    for signal in bar_signals:
                        self.recorder.record_signal(signal, symbol=symbol)
                signals.extend(bar_signals)

        return signals

    def current_minute(self, symbol: str) -> Candle | None:
        """Expose a snapshot of the in-progress minute."""
        return self.tick_builder.current_minute(symbol)


__all__ = ["PaperMarketDataPipeline"]
