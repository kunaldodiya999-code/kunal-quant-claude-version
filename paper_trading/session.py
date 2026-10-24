"""Composition root for a buyer-only FYERS paper session.

Building a session does not connect to a socket or place broker orders.
Starting the feed is explicit. The current option lot size must be supplied
by the caller after checking the selected contract specification.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Callable

from api.fyers_client import FyersClient
from market_data.fyers_quote_cache import FyersQuoteCache
from market_data.live_ticks import LiveMinuteBarBuilder
from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.engine import PaperStrategyId, PaperEngineConfig, PaperTradingEngine
from paper_trading.entry_adapter import PaperEntryAdapter, PaperEntryAdapterConfig
from paper_trading.fyers_feed import FyersPaperFeed
from paper_trading.market_data_pipeline import PaperMarketDataPipeline
from paper_trading.pending_entry_orchestrator import PendingEntryConfig, PendingEntryOrchestrator
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.signals import evaluate_latest_paper_signals
from paper_trading.uni_lite_signals import evaluate_uni_lite_paper_signals
from indicators.ktmi_uni_lite import UNI_LITE_CORE, UNI_LITE_DEFAULTS
import time

from paper_trading.account import PaperAccount
from paper_trading.sizing import AllocationSetting, AllocationStore
from paper_trading.exit_manager import DEFAULT_TSL, ExitManager, ExitRules
from paper_trading.costs import OptionCostModel
from paper_trading.controls import SessionControls, SessionControlsConfig
from paper_trading.recovery import RecoveryReport, restore_from_journal
from paper_trading.tsl_shadow_lab import OptionCandle, TslShadowLab
from strategies.option_contract_resolver import OptionContractResolver


SIGNAL_PROFILES = {
    "UNI_LITE_CORE": partial(evaluate_uni_lite_paper_signals, uni_lite_config=UNI_LITE_CORE),
    "UNI_LITE_DEFAULTS": partial(evaluate_uni_lite_paper_signals, uni_lite_config=UNI_LITE_DEFAULTS),
    "LEGACY_UNIVERSAL": evaluate_latest_paper_signals,
}


@dataclass(frozen=True)
class PaperSessionConfig:
    lot_size: int
    allocation: float = 15_000.0          # starting budget per trade (rupees); the saved choice wins on restart
    allocation_percent: float | None = None   # if set, start in PERCENT mode (of the account balance)
    resolution_minutes: int = 3
    # Which entry rules drive the paper engine:
    #   UNI_LITE_CORE     owner's current rules: Long Speed crosses above +0.5 -> BUY CE,
    #                     Short Speed crosses above +0.5 -> BUY PE (all other arrows silent)
    #   UNI_LITE_DEFAULTS every arrow of the Pine script with its default trigger
    #   LEGACY_UNIVERSAL  the earlier KTMI Universal Strategy A/B + confluence evaluator
    signal_profile: str = "UNI_LITE_CORE"
    underlying_symbol: str = "NSE:NIFTY50-INDEX"
    database_path: str | Path | None = None
    output_dir: str | Path = "data/paper_trading"
    pending_journal_path: str | Path = "data/paper_trading/pending_entries.csv"
    pending_timeout_seconds: int = 8
    max_quote_age_seconds: int = 5
    max_receive_age_seconds: float = 5.0
    stop_loss_pct: float = 0.30           # initial stop: 30% below the premium paid (owner default)
    target_rr: float = 3.0
    target_enabled: bool = True
    restore_from_journal: bool = True
    # Session rules (owner-configurable). Window and forced exit apply to NSE & BSE F&O.
    entry_start_hhmm: str = "09:30"
    entry_end_hhmm: str = "15:00"
    force_exit_hhmm: str = "15:10"
    starting_capital: float = 100_000.0           # paper account opening balance
    cost_model: OptionCostModel = OptionCostModel()
    max_daily_loss_amount: float | None = None    # rupees; None = off
    max_daily_loss_pct: float | None = None       # percent of the day's opening equity; None = off
    kill_hours: float = 12.0
    # Exit rules (checkboxes). A saved choice in exit_rules.json wins over these on restart.
    active_tsl: tuple[str, ...] = DEFAULT_TSL
    kama_exit_enabled: bool = False
    mark_max_age_seconds: int = 30   # option price older than this cannot value an open position

    def __post_init__(self) -> None:
        if self.lot_size < 1:
            raise ValueError("Supply the verified current contract lot size.")
        if self.allocation <= 0:
            raise ValueError("allocation must be positive.")
        if self.resolution_minutes not in (1, 3, 5):
            raise ValueError("resolution_minutes must be 1, 3, or 5.")
        if self.signal_profile not in SIGNAL_PROFILES:
            raise ValueError(f"signal_profile must be one of {sorted(SIGNAL_PROFILES)}.")


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
    recovery: RecoveryReport | None = None
    controls: SessionControls | None = None
    account: PaperAccount | None = None
    allocation_store: AllocationStore | None = None
    exit_manager: ExitManager | None = None

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
        signal_evaluator=SIGNAL_PROFILES[config.signal_profile],
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
    controls = SessionControls(
        SessionControlsConfig.from_hhmm(
            config.entry_start_hhmm, config.entry_end_hhmm, config.force_exit_hhmm,
            max_daily_loss_amount=config.max_daily_loss_amount,
            max_daily_loss_pct=config.max_daily_loss_pct,
            kill_hours=config.kill_hours,
        ),
        journal_dir=config.output_dir,
    )
    account = PaperAccount(engine, starting_capital=config.starting_capital, cost_model=config.cost_model)
    controls.bind(engine, account)
    default_setting = (AllocationSetting.from_percent(config.allocation_percent)
                       if config.allocation_percent is not None
                       else AllocationSetting.from_amount(config.allocation))
    allocation_store = AllocationStore(default_setting, journal_dir=config.output_dir)

    def entry_budget(*, timestamp: int, entry_price: float) -> float:
        """Rupee budget for the next entry: the chosen allocation, capped by balance and free cash."""
        snap = account.snapshot(timestamp)
        return allocation_store.setting.budget(
            balance=snap.balance, available_cash=snap.available_cash).budget

    engine.allocation_provider = entry_budget
    coordinator = PaperExecutionCoordinator(adapter=adapter, engine=engine, controls=controls)
    # Rebuild open positions and seen signals from the journal so a restart
    # cannot lose a position or enter the same signal twice.
    recovery = restore_from_journal(engine, coordinator) if config.restore_from_journal else None

    # Late-bound callbacks resolve entry wiring and shadow exit tracking.
    holder: dict[str, PendingEntryOrchestrator] = {}
    tsl_shadow = TslShadowLab(Path(config.output_dir) / "tsl_shadow")
    exit_manager = ExitManager(
        engine, tsl_shadow,
        rules=ExitRules(active_tsl=config.active_tsl, partial_target=config.target_enabled,
                        kama_exit=config.kama_exit_enabled),
        journal_dir=config.output_dir,
    )

    def current_marks() -> dict:
        """Latest fresh option price per open paper position; stale or missing prices are omitted."""
        marks = {}
        for strategy in PaperStrategyId:
            record = engine.open_trade(strategy)
            if record is None:
                continue
            try:
                quote = quote_cache.get_quote(
                    record.position.symbol, decision_timestamp=int(time.time()),
                    max_exchange_age_seconds=config.mark_max_age_seconds,
                    max_receive_age_seconds=float(config.mark_max_age_seconds),
                )
            except (LookupError, ValueError):
                continue
            marks[strategy] = float(quote["lp"])
        return marks

    coordinator.marks_provider = current_marks
    option_tick_builder = LiveMinuteBarBuilder()

    def on_signals(signals) -> None:
        orchestrator = holder.get("orchestrator")
        if orchestrator is not None:
            orchestrator.on_signals(signals)

    def on_tick(message) -> None:
        orchestrator = holder.get("orchestrator")
        if orchestrator is not None:
            orchestrator.on_tick(message)

        # Enrol each accepted paper entry with every trailing-stop method (shadow lab).
        exit_manager.enroll_open_trades()

        # Only completed candles from option symbols drive the exit rules.
        if isinstance(message, dict):
            symbol = message.get("symbol")
            if isinstance(symbol, str) and symbol.strip() != config.underlying_symbol:
                for candle in option_tick_builder.on_message(message):
                    exit_manager.on_option_candle(
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
        recovery=recovery,
        controls=controls,
        account=account,
        allocation_store=allocation_store,
        exit_manager=exit_manager,
    )


__all__ = ["PaperSession", "PaperSessionConfig", "build_paper_session"]
