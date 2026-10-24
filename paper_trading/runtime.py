"""Dependency-injected runtime that joins completed-bar signals to paper entries.

The runtime deliberately does not create a broker client or submit orders.
The application supplies an underlying-price lookup and an option-quote
provider (for example, a cache populated by a subscribed FYERS data socket).
Quote timestamps must be exchange/feed epoch timestamps; do not stamp a quote
with local observation time to make a stale or untimestamped quote look fresh.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE
from paper_trading.coordinator import PaperEntryAttempt, PaperExecutionCoordinator
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.signals import PaperSignal

MARKET_TZ = ZoneInfo(TIMEZONE)

UnderlyingPriceProvider = Callable[[PaperSignal], float]
OptionQuoteProvider = Callable[[PaperSignal, float, int], Mapping[str, Any]]
Clock = Callable[[], datetime]


@dataclass(frozen=True)
class PaperRuntimeResult:
    """Signals and entry attempts produced from one incoming market message."""

    signals: tuple[PaperSignal, ...]
    attempts: tuple[PaperEntryAttempt, ...]


class PaperTradingRuntime:
    """Connect pipeline output to the paper execution coordinator.

    Each signal is attempted once per runtime process. The coordinator also
    deduplicates signals in memory. Persistent restart recovery is intentionally
    not claimed here; it remains a separate required milestone.
    """

    def __init__(
        self,
        *,
        pipeline: PaperMarketDataPipeline,
        coordinator: PaperExecutionCoordinator,
        underlying_price_provider: UnderlyingPriceProvider,
        option_quote_provider: OptionQuoteProvider,
        clock: Clock | None = None,
    ) -> None:
        self.pipeline = pipeline
        self.coordinator = coordinator
        self.underlying_price_provider = underlying_price_provider
        self.option_quote_provider = option_quote_provider
        self.clock = clock or (lambda: datetime.now(MARKET_TZ))

    def on_message(self, message: Any) -> PaperRuntimeResult:
        """Process a FYERS-style tick through completed bars into paper entries."""
        signals = self.pipeline.on_message(message)
        attempts: list[PaperEntryAttempt] = []

        for signal in signals:
            now = self.clock()
            if now.tzinfo is None:
                raise ValueError("Runtime clock must return a timezone-aware datetime.")
            decision_timestamp = int(now.timestamp())

            # A completed bar can be emitted only after a later minute starts.
            # Keep the decision timestamp separate from the bar's bucket start.
            if decision_timestamp <= int(signal.timestamp):
                continue

            try:
                underlying_price = float(
                    self.underlying_price_provider(signal)
                )
                quote = self.option_quote_provider(
                    signal, underlying_price, decision_timestamp
                )
                attempt = self.coordinator.process_signal(
                    signal=signal,
                    underlying_price=underlying_price,
                    option_quote=quote,
                    decision_timestamp=decision_timestamp,
                )
            except (LookupError, ValueError, TypeError, KeyError) as exc:
                # Return an explicit rejected attempt instead of silently
                # dropping a signal when market data or contract data is absent.
                attempts.append(
                    PaperEntryAttempt(
                        signal=signal,
                        candidate=None,
                        trade=None,
                        rejection_reason=f"Runtime input unavailable: {exc}",
                    )
                )
            else:
                attempts.append(attempt)

        return PaperRuntimeResult(
            signals=tuple(signals),
            attempts=tuple(attempts),
        )


__all__ = ["PaperRuntimeResult", "PaperTradingRuntime"]
