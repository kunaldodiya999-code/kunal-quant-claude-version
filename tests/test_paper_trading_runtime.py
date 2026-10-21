import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from paper_trading.coordinator import PaperEntryAttempt
from paper_trading.runtime import PaperTradingRuntime
from paper_trading.signals import PaperSignal
from paper_trading.engine import PaperStrategyId


TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 13, 10, 0, tzinfo=TZ)
TS = int(NOW.timestamp())


class FakePipeline:
    def __init__(self, signals):
        self.signals = signals
        self.messages = []

    def on_message(self, message):
        self.messages.append(message)
        return self.signals


class FakeCoordinator:
    def __init__(self):
        self.calls = []

    def process_signal(self, **kwargs):
        self.calls.append(kwargs)
        return PaperEntryAttempt(
            signal=kwargs["signal"], candidate=None, trade=None,
            rejection_reason=None,
        )


class PaperTradingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.signal = PaperSignal(
            strategy_id=PaperStrategyId.STRATEGY_A,
            direction="SHORT", timestamp=TS - 180, index=10, reason="CROSS_0.5",
        )
        self.pipeline = FakePipeline([self.signal])
        self.coordinator = FakeCoordinator()
        self.quote = {
            "symbol": "NSE:NIFTY2610025000PE",
            "lp": 100.0,
            "exch_feed_time": TS,
        }
        self.runtime = PaperTradingRuntime(
            pipeline=self.pipeline,
            coordinator=self.coordinator,
            underlying_price_provider=lambda signal: 25000.0,
            option_quote_provider=lambda signal, price, decision_ts: self.quote,
            clock=lambda: NOW,
        )

    def test_completed_signal_is_forwarded_with_actual_decision_time(self):
        message = {"symbol": "NSE:NIFTY50-INDEX", "ltp": 25000}
        result = self.runtime.on_message(message)
        self.assertEqual(self.pipeline.messages, [message])
        self.assertEqual(len(result.signals), 1)
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(len(self.coordinator.calls), 1)
        call = self.coordinator.calls[0]
        self.assertEqual(call["decision_timestamp"], TS)
        self.assertEqual(call["underlying_price"], 25000.0)
        self.assertEqual(call["option_quote"], self.quote)

    def test_missing_underlying_price_is_reported_as_rejection(self):
        runtime = PaperTradingRuntime(
            pipeline=self.pipeline,
            coordinator=self.coordinator,
            underlying_price_provider=lambda signal: (_ for _ in ()).throw(
                LookupError("underlying price unavailable")
            ),
            option_quote_provider=lambda signal, price, decision_ts: self.quote,
            clock=lambda: NOW,
        )
        result = runtime.on_message({"symbol": "NSE:NIFTY50-INDEX"})
        self.assertIn("underlying price unavailable", result.attempts[0].rejection_reason)
        self.assertEqual(len(self.coordinator.calls), 0)

    def test_naive_clock_is_rejected(self):
        runtime = PaperTradingRuntime(
            pipeline=self.pipeline,
            coordinator=self.coordinator,
            underlying_price_provider=lambda signal: 25000.0,
            option_quote_provider=lambda signal, price, decision_ts: self.quote,
            clock=lambda: datetime(2026, 10, 13, 10, 0),
        )
        with self.assertRaises(ValueError):
            runtime.on_message({"symbol": "NSE:NIFTY50-INDEX"})


if __name__ == "__main__":
    unittest.main()
