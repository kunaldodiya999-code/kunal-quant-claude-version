import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_data.fyers_quote_cache import FyersQuoteCache
from paper_trading.coordinator import PaperEntryAttempt
from paper_trading.engine import PaperStrategyId
from paper_trading.pending_entry_orchestrator import (
    PendingEntryConfig,
    PendingEntryOrchestrator,
)
from paper_trading.signals import PaperSignal
from strategies.option_contract_resolver import ResolvedOptionContract


TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 19, 10, 0, tzinfo=TZ)
TS = int(NOW.timestamp())
OPTION_SYMBOL = "NSE:NIFTY2610025000PE"


class Resolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        return ResolvedOptionContract(
            instrument_id=1, symbol=OPTION_SYMBOL, underlying="NIFTY",
            expiry_date=date(2026, 10, 27), strike=25000, option_type="PE",
        )


class Coordinator:
    def __init__(self):
        self.calls = []

    def process_signal(self, **kwargs):
        self.calls.append(kwargs)
        return PaperEntryAttempt(
            signal=kwargs["signal"], candidate=None, trade=object(),
            rejection_reason=None,
        )


class PendingEntryOrchestratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.now = NOW
        self.cache = FyersQuoteCache(receive_clock=lambda: 1000.0)
        self.cache.update({
            "symbol": "NSE:NIFTY50-INDEX", "ltp": 25000,
            "exch_feed_time": TS,
        })
        self.coordinator = Coordinator()
        self.subscriptions = []
        self.orchestrator = PendingEntryOrchestrator(
            resolver=Resolver(), quote_cache=self.cache,
            coordinator=self.coordinator,
            subscribe_symbols=lambda symbols: self.subscriptions.extend(symbols),
            config=PendingEntryConfig(
                timeout_seconds=8,
                journal_path=Path(self.temp_dir.name) / "pending.csv",
            ),
            clock=lambda: self.now,
        )
        self.signal = PaperSignal(
            strategy_id=PaperStrategyId.STRATEGY_A, direction="SHORT",
            timestamp=TS - 180, index=10, reason="CROSS_0.5",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_signal_subscribes_and_waits_for_option_quote(self):
        events = self.orchestrator.on_signals([self.signal])
        self.assertEqual(events[0].status, "PENDING")
        self.assertEqual(self.subscriptions, [OPTION_SYMBOL])
        self.assertEqual(len(self.orchestrator.pending()), 1)
        self.assertEqual(self.orchestrator.on_tick(), ())
        self.assertEqual(self.coordinator.calls, [])

    def test_fresh_option_tick_releases_pending_signal_once(self):
        self.orchestrator.on_signals([self.signal])
        self.cache.update({
            "symbol": OPTION_SYMBOL, "ltp": 100,
            "exch_feed_time": TS,
        })
        events = self.orchestrator.on_tick({"symbol": OPTION_SYMBOL})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "ENTERED")
        self.assertEqual(len(self.coordinator.calls), 1)
        self.assertEqual(self.coordinator.calls[0]["option_quote"]["symbol"], OPTION_SYMBOL)
        self.assertEqual(self.orchestrator.pending(), ())
        self.assertEqual(self.orchestrator.on_tick(), ())
        self.assertEqual(len(self.coordinator.calls), 1)

    def test_missing_quote_times_out_and_is_journaled(self):
        self.orchestrator.on_signals([self.signal])
        self.now = NOW + timedelta(seconds=9)
        events = self.orchestrator.on_tick()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, "TIMED_OUT")
        self.assertIn("pending", Path(self.temp_dir.name, "pending.csv").read_text().lower())
        self.assertEqual(self.orchestrator.pending(), ())

    def test_duplicate_signal_is_not_queued_twice(self):
        first = self.orchestrator.on_signals([self.signal])
        second = self.orchestrator.on_signals([self.signal])
        self.assertEqual(len(first), 1)
        self.assertEqual(second, ())
        self.assertEqual(len(self.orchestrator.pending()), 1)

    def test_unavailable_underlying_quote_is_explicit_rejection(self):
        cache = FyersQuoteCache(receive_clock=lambda: 1000.0)
        events = []
        orchestrator = PendingEntryOrchestrator(
            resolver=Resolver(), quote_cache=cache, coordinator=self.coordinator,
            subscribe_symbols=lambda symbols: None,
            config=PendingEntryConfig(journal_path=Path(self.temp_dir.name) / "other.csv"),
            clock=lambda: NOW,
        )
        result = orchestrator.on_signals([self.signal])
        self.assertEqual(result[0].status, "REJECTED")
        self.assertIn("No FYERS quote", result[0].reason)


if __name__ == "__main__":
    unittest.main()
