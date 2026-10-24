"""Paper-only adapter from a completed signal to a validated option entry.

This module composes the existing Option Contract Resolver V2 and
PaperTradingEngine. It does not change signal rules, lifecycle rules, or place
broker orders. A candidate is returned only when the selected contract has a
matching, positive, sufficiently fresh quote.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE
from paper_trading.engine import PaperTradeRecord, PaperTradingEngine
from paper_trading.signals import PaperSignal
from strategies.option_contract_resolver import (
    OptionContractResolver,
    ResolvedOptionContract,
)


MARKET_TZ = ZoneInfo(TIMEZONE)


@dataclass(frozen=True)
class PaperEntryAdapterConfig:
    """Quote validation settings; freshness is configurable and paper-only."""

    max_quote_age_seconds: int = 5


@dataclass(frozen=True)
class PaperEntryCandidate:
    """Resolved contract and validated observed option price for one signal."""

    signal: PaperSignal
    contract: ResolvedOptionContract
    entry_price: float
    entry_timestamp: int


class PaperEntryAdapter:
    """Resolve and validate paper entries without changing strategy behavior."""

    def __init__(
        self,
        resolver: OptionContractResolver | None = None,
        config: PaperEntryAdapterConfig | None = None,
    ) -> None:
        self.resolver = resolver or OptionContractResolver()
        self.config = config or PaperEntryAdapterConfig()
        if self.config.max_quote_age_seconds < 0:
            raise ValueError("max_quote_age_seconds cannot be negative")

    @staticmethod
    def _quote_value(
        quote: Mapping[str, Any],
        keys: tuple[str, ...],
        label: str,
    ) -> Any:
        for key in keys:
            value = quote.get(key)
            if value is not None and value != "":
                return value
        raise ValueError(f"Option quote is missing {label}.")

    def prepare_entry(
        self,
        *,
        signal: PaperSignal,
        underlying_price: float,
        option_quote: Mapping[str, Any],
        entry_timestamp: int | None = None,
    ) -> PaperEntryCandidate:
        """Resolve the option and validate its quote before an entry is allowed.

        Accepted FYERS-style price fields: lp, ltp, last_price.
        Accepted epoch timestamp fields: exch_feed_time, last_traded_time,
        timestamp. The quote must match the resolver's exact symbol.
        """
        if not isinstance(option_quote, Mapping):
            raise ValueError("option_quote must be a mapping.")

        timestamp = int(signal.timestamp if entry_timestamp is None else entry_timestamp)
        if timestamp <= 0:
            raise ValueError("Entry timestamp must be positive.")

        try:
            price = float(
                self._quote_value(
                    option_quote,
                    ("lp", "ltp", "last_price"),
                    "last traded price",
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Option quote price must be numeric.") from exc
        if not isfinite(price) or price <= 0:
            raise ValueError("Option quote price must be finite and positive.")

        quote_symbol = str(option_quote.get("symbol", "")).strip()
        if not quote_symbol:
            raise ValueError("Option quote is missing symbol.")

        try:
            quote_timestamp = int(
                self._quote_value(
                    option_quote,
                    ("exch_feed_time", "last_traded_time", "timestamp"),
                    "epoch timestamp",
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("Option quote timestamp must be an epoch integer.") from exc
        if quote_timestamp <= 0:
            raise ValueError("Option quote timestamp must be positive.")

        age_seconds = timestamp - quote_timestamp
        if age_seconds < 0:
            raise ValueError("Option quote timestamp is later than the entry timestamp.")
        if age_seconds > self.config.max_quote_age_seconds:
            raise ValueError(
                f"Option quote is stale ({age_seconds}s old; "
                f"maximum {self.config.max_quote_age_seconds}s)."
            )

        local_entry_date = datetime.fromtimestamp(
            timestamp, tz=MARKET_TZ
        ).date()
        contract = self.resolver.resolve(
            underlying_price=float(underlying_price),
            entry_date=local_entry_date,
            direction=signal.direction,
        )
        if quote_symbol != contract.symbol:
            raise ValueError(
                f"Option quote symbol mismatch: expected {contract.symbol}, "
                f"received {quote_symbol}."
            )

        return PaperEntryCandidate(
            signal=signal,
            contract=contract,
            entry_price=price,
            entry_timestamp=timestamp,
        )

    @staticmethod
    def open_position(
        engine: PaperTradingEngine,
        candidate: PaperEntryCandidate,
    ) -> PaperTradeRecord | None:
        """Pass a validated candidate into the existing paper engine."""
        return engine.open_position(
            strategy_id=candidate.signal.strategy_id,
            direction=candidate.signal.direction,
            symbol=candidate.contract.symbol,
            entry_price=candidate.entry_price,
            timestamp=candidate.entry_timestamp,
        )


__all__ = [
    "PaperEntryAdapterConfig",
    "PaperEntryCandidate",
    "PaperEntryAdapter",
]
