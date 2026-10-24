"""Paper-only orchestration components for KunalQuant."""

from paper_trading.signals import PaperSignal, evaluate_latest_paper_signals
from paper_trading.engine import (
    PaperEngineConfig,
    PaperStrategyId,
    PaperTradeRecord,
    PaperTradingEngine,
)
from paper_trading.recorder import PaperTradeRecorder
from paper_trading.entry_adapter import (
    PaperEntryAdapter,
    PaperEntryAdapterConfig,
    PaperEntryCandidate,
)

__all__ = [
    "PaperSignal",
    "evaluate_latest_paper_signals",
    "PaperEngineConfig",
    "PaperStrategyId",
    "PaperTradeRecord",
    "PaperTradingEngine",
    "PaperTradeRecorder",
    "PaperEntryAdapter",
    "PaperEntryAdapterConfig",
    "PaperEntryCandidate",
]
