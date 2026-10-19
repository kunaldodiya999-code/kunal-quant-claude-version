import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from paper_trading.buyer_lifecycle import BuyerLifecycleConfig, BuyerOptionTradeLifecycle
from paper_trading.coordinator import PaperExecutionCoordinator
from paper_trading.entry_adapter import PaperEntryAdapter
from paper_trading.engine import PaperTradingEngine
from paper_trading.signals import PaperSignal
from paper_trading.engine import PaperStrategyId
from strategies.option_contract_resolver import ResolvedOptionContract
from datetime import date


TZ = ZoneInfo("Asia/Kolkata")
TS = int(datetime(2026, 10, 13, 10, 0, tzinfo=TZ).timestamp())


class Resolver:
    def resolve(self, *, underlying_price, entry_date, direction):
        typ = "CE" if direction == "LONG" else "PE"
        return ResolvedOptionContract(
            instrument_id=1, symbol=f"NSE:NIFTY2610025000{typ}",
            underlying="NIFTY", expiry_date=date(2026, 10, 27),
            strike=25000, option_type=typ,
        )


class PaperExecutionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.engine = PaperTradingEngine(
            lifecycle=BuyerOptionTradeLifecycle(
                BuyerLifecycleConfig(allocation=15000, lot_size=25)
            )
        )
        self.coordinator = PaperExecutionCoordinator(
            adapter=PaperEntryAdapter(Resolver()), engine=self.engine
        )
        self.signal = PaperSignal(
            strategy_id=PaperStrategyId.STRATEGY_A, direction="SHORT",
            timestamp=TS - 180, index=20, reason="CROSS_0.5",
        )

    def test_valid_bearish_signal_opens_bought_put(self):
        attempt = self.coordinator.process_signal(
            signal=self.signal, underlying_price=25000,
            option_quote={"symbol":"NSE:NIFTY2610025000PE","lp":100,"exch_feed_time":TS},
            decision_timestamp=TS,
        )
        self.assertIsNone(attempt.rejection_reason)
        self.assertEqual(attempt.trade.position.symbol, "NSE:NIFTY2610025000PE")
        self.assertEqual(attempt.trade.position.stop_loss, 80)

    def test_duplicate_signal_is_not_opened_twice(self):
        kwargs = dict(
            signal=self.signal, underlying_price=25000,
            option_quote={"symbol":"NSE:NIFTY2610025000PE","lp":100,"exch_feed_time":TS},
            decision_timestamp=TS,
        )
        first = self.coordinator.process_signal(**kwargs)
        second = self.coordinator.process_signal(**kwargs)
        self.assertIsNotNone(first.trade)
        self.assertIn("Duplicate", second.rejection_reason)
        self.assertEqual(len(self.engine.all_trades()), 1)

    def test_entry_decision_must_follow_signal_timestamp(self):
        attempt = self.coordinator.process_signal(
            signal=self.signal, underlying_price=25000,
            option_quote={"symbol":"NSE:NIFTY2610025000PE","lp":100,"exch_feed_time":TS},
            decision_timestamp=self.signal.timestamp,
        )
        self.assertIn("after the signal", attempt.rejection_reason)
        self.assertEqual(self.engine.all_trades(), ())

    def test_stale_quote_is_rejected_without_opening_trade(self):
        attempt = self.coordinator.process_signal(
            signal=self.signal, underlying_price=25000,
            option_quote={"symbol":"NSE:NIFTY2610025000PE","lp":100,"exch_feed_time":TS-10},
            decision_timestamp=TS,
        )
        self.assertIn("stale", attempt.rejection_reason)
        self.assertEqual(self.engine.all_trades(), ())


if __name__ == "__main__":
    unittest.main()
