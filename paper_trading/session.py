"""Composition root for a buyer-only FYERS paper session.

Building a session does not connect to a socket or place broker orders.
Starting the feed is explicit. The current option lot size must be supplied
by the caller after checking the selected contract specification.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from api.fyers_client import FyersClient
from market_data.fyers_quote_cache import FyersQuoteCache
from market_data.live_ticks import LiveMinuteBarBuilder
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperEngineConfig, PaperTradingEngine
from paper_trading.entry_adapter import PaperEntryAdapter, PaperEntryAdapterConfig
from paper_trading.fyers_feed import FyersPaperFeed
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.pending_entry_orchestrator import PendingEntryConfig, PendingEntryOrchestrator
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab
from strategies.option_contract_resolver import OptionContractResolver


@dataclass(frozen=True)
class PaperSessionConfig:
    lot_size: int
    allocation: float = 15_000.0
    resolution_minutes: int = 3
    underlying_symbol: str = "NSE:NIFTY50-INDEX"
    database_path: str | Path | None = None
    output_dir: str | Path = "data/paper_trading"
    pending_journal_path: str | Path = "data/paper_trading/pending_entries.csv"
    pending_timeout_seconds: int = 8
    max_quote_age_seconds: int = 5
    max_receive_age_seconds: float = 5.0
    stop_loss_pct: float = 0.20
    target_rr: float = 3.0
    target_enabled: bool = True

    def __post_init__(self) -> None:
        if self.lot_size < 1:
            raise ValueError("Supply the verified current contract lot size.")
        if self.allocation <= 0:
            raise ValueError("allocation must be positive.")
        if self.resolution_minutes not in (1, 3, 5):
            raise ValueError("resolution_minutes must be 1, 3, or 5.")


@dataclass
class PaperSession:
    feed: FyersPaperFeed
    quote_cache: FyersQuoteCache
    pipeline: PaperMarketDataPipeline
    resolver: OptionContractResolver
    engine: PaperTradingEngine
    coordinator: PaperExecutionCoordinator
    orchestrator: PendingEntryOrchestrator
    recorder: PaperTradeRecorder
    tsl_shadow: TslShadowLab

    def start(self) -> None:
        """Start market-data streaming only; no broker orders are submitted."""
        self.feed.start()

    def close(self) -> None:
        self.feed.close()


def build_paper_session(
    *,
    client: FyersClient,
    config: PaperSessionConfig,
    resolver: OptionContractResolver | None = None,
    engine_config: PaperEngineConfig | None = None,
    socket_factory: Callable[..., Any] | None = None,
) -> PaperSession:
    """Wire all paper entry components without connecting the market-data socket."""
    recorder = PaperTradeRecorder(config.output_dir)
    quote_cache = FyersQuoteCache()
    if resolver is None:
        resolver = OptionContractResolver(
            database_path=config.database_path
        ) if config.database_path is not None else OptionContractResolver()

    pipeline = PaperMarketDataPipeline(
        resolution_minutes=config.resolution_minutes,
        paper_config=engine_config,
        recorder=recorder,
    )
    lifecycle = BuyerOptionTradeLifecycle(
        BuyerLifecycleConfig(
            allocation=config.allocation,
            lot_size=config.lot_size,
            stop_loss_pct=config.stop_loss_pct,
            target_rr=config.target_rr,
            target_enabled=config.target_enabled,
        )
    )
    engine = PaperTradingEngine(
        config=engine_config,
        recorder=recorder,
        lifecycle=lifecycle,
    )
    adapter = PaperEntryAdapter(
        resolver=resolver,
        config=PaperEntryAdapterConfig(
            max_quote_age_seconds=config.max_quote_age_seconds
        ),
    )
    coordinator = PaperExecutionCoordinator(adapter=adapter, engine=engine)

    # Late-bound callbacks resolve entry wiring and shadow exit tracking.
    holder: dict[str, PendingEntryOrchestrator] = {}
    tsl_shadow = TslShadowLab(Path(config.output_dir) / "tsl_shadow")
    option_tick_builder = LiveMinuteBarBuilder()

    def on_signals(signals) -> None:
        orchestrator = holder.get("orchestrator")
        if orchestrator is not None:
            orchestrator.on_signals(signals)

    def on_tick(message) -> None:
        orchestrator = holder.get("orchestrator")
        if orchestrator is not None:
            orchestrator.on_tick(message)

        # Register each accepted paper entry with independent shadow candidates.
        for trade in engine.all_trades():
            position = trade.position
            trade_id = f"{trade.strategy_id.value}:{trade.entry_timestamp}:{position.symbol}"
            tsl_shadow.register_trade(
                trade_id=trade_id,
                symbol=position.symbol,
                direction=getattr(position.direction, "value", position.direction),
                entry_timestamp=trade.entry_timestamp,
                entry_price=position.entry_price,
                quantity=position.quantity,
            )

        # Only completed candles from option symbols are used by the shadow lab.
        if isinstance(message, dict):
            symbol = message.get("symbol")
            if isinstance(symbol, str) and symbol.strip() != config.underlying_symbol:
                for candle in option_tick_builder.on_message(message):
                    tsl_shadow.on_candle(
                        symbol=symbol.strip(),
                        candle=OptionCandle(
                            timestamp=candle.timestamp, open=candle.open,
                            high=candle.high, low=candle.low, close=candle.close,
                        ),
                    )

    feed = FyersPaperFeed(
        client=client,
        pipeline=pipeline,
        quote_cache=quote_cache,
        underlying_symbols=[config.underlying_symbol],
        on_signals=on_signals,
        on_tick=on_tick,
        socket_factory=socket_factory,
    )
    orchestrator = PendingEntryOrchestrator(
        resolver=resolver,
        quote_cache=quote_cache,
        coordinator=coordinator,
        subscribe_symbols=feed.subscribe_symbols,
        underlying_symbol=config.underlying_symbol,
        config=PendingEntryConfig(
            timeout_seconds=config.pending_timeout_seconds,
            max_quote_age_seconds=config.max_quote_age_seconds,
            max_receive_age_seconds=config.max_receive_age_seconds,
            journal_path=config.pending_journal_path,
        ),
    )
    holder["orchestrator"] = orchestrator

    return PaperSession(
        feed=feed,
        quote_cache=quote_cache,
        pipeline=pipeline,
        resolver=resolver,
        engine=engine,
        coordinator=coordinator,
        orchestrator=orchestrator,
        recorder=recorder,
        tsl_shadow=tsl_shadow,
    )


__all__ = ["PaperSession", "PaperSessionConfig", "build_paper_session"]
