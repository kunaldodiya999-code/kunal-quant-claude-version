import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from paper_trading.market_data_pipeline import PaperMarketDataPipeline


TZ = ZoneInfo("Asia/Kolkata")


class PaperMarketDataPipelineTests(unittest.TestCase):
    def setUp(self):
        self.evaluated = []
        def evaluator(bars, *, paper_config):
            self.evaluated.append(list(bars))
            return []
        self.evaluator = evaluator

    @staticmethod
    def ts(hour, minute):
        return int(datetime(2026, 10, 12, hour, minute, tzinfo=TZ).timestamp())

    @staticmethod
    def tick(timestamp, ltp, symbol="NSE:NIFTY50-INDEX"):
        return {
            "symbol": symbol,
            "last_traded_time": timestamp + 5,
            "ltp": ltp,
            "type": "sf",
        }

    def test_one_minute_resolution_evaluates_only_completed_minutes(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=1, signal_evaluator=self.evaluator
        )
        t1 = self.ts(9, 15)
        self.assertEqual(pipeline.on_message(self.tick(t1, 100)), [])
        self.assertEqual(self.evaluated, [])
        self.assertEqual(pipeline.on_message(self.tick(t1 + 20, 102)), [])
        self.assertEqual(self.evaluated, [])
        pipeline.on_message(self.tick(t1 + 60, 101))
        self.assertEqual(len(self.evaluated), 1)
        bar = self.evaluated[0][0]
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100, 102, 100, 102))

    def test_three_minute_resolution_sends_only_complete_derived_bars(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=3, signal_evaluator=self.evaluator
        )
        start = self.ts(9, 15)
        for offset in (0, 60, 120):
            pipeline.on_message(self.tick(start + offset, 100 + offset // 60))
        self.assertEqual(self.evaluated, [])
        pipeline.on_message(self.tick(start + 180, 103))
        self.assertEqual(len(self.evaluated), 1)
        bar = self.evaluated[0][0]
        self.assertTrue(bar.complete)
        self.assertEqual(bar.resolution, "3")
        self.assertEqual(bar.actual_1m_candles, 3)

    def test_five_minute_resolution_sends_only_complete_derived_bars(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=5, signal_evaluator=self.evaluator
        )
        start = self.ts(9, 15)
        for minute in range(5):
            pipeline.on_message(self.tick(start + minute * 60, 100 + minute))

        self.assertEqual(self.evaluated, [])
        pipeline.on_message(self.tick(start + 5 * 60, 105))

        self.assertEqual(len(self.evaluated), 1)
        bar = self.evaluated[0][0]
        self.assertTrue(bar.complete)
        self.assertEqual(bar.resolution, "5")
        self.assertEqual(bar.actual_1m_candles, 5)
        self.assertEqual(bar.timestamp, start)

    def test_missing_minute_does_not_emit_incomplete_derived_bar(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=3, signal_evaluator=self.evaluator
        )
        start = self.ts(9, 15)

        # Minute 09:17 is intentionally absent. No synthetic candle is created.
        for offset in (0, 60, 180, 240, 300):
            pipeline.on_message(self.tick(start + offset, 100 + offset // 60))

        self.assertEqual(self.evaluated, [])

        # The later, separate 09:18-09:20 bucket is complete and can be emitted.
        pipeline.on_message(self.tick(start + 360, 106))
        self.assertEqual(len(self.evaluated), 1)
        bar = self.evaluated[0][0]
        self.assertTrue(bar.complete)
        self.assertEqual(bar.timestamp, start + 180)
        self.assertEqual(bar.actual_1m_candles, 3)

    def test_rejects_unsupported_resolution(self):
        with self.assertRaises(ValueError):
            PaperMarketDataPipeline(resolution_minutes=2)

    def test_out_of_session_completed_minute_is_not_evaluated(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=1, signal_evaluator=self.evaluator
        )
        after_close = self.ts(15, 30)
        pipeline.on_message(self.tick(after_close, 100))
        pipeline.on_message(self.tick(after_close + 60, 101))
        self.assertEqual(self.evaluated, [])

    def test_actual_fyers_exchange_feed_packet_flows_through_pipeline(self):
        pipeline = PaperMarketDataPipeline(
            resolution_minutes=1, signal_evaluator=self.evaluator
        )
        start = self.ts(9, 15)

        first_tick = {
            "ltp": 100.0,
            "exch_feed_time": start + 5,
            "type": "if",
            "symbol": "NSE:NIFTY50-INDEX",
        }
        next_minute_tick = {
            "ltp": 102.0,
            "exch_feed_time": start + 65,
            "type": "if",
            "symbol": "NSE:NIFTY50-INDEX",
        }

        self.assertEqual(pipeline.on_message(first_tick), [])
        self.assertEqual(self.evaluated, [])

        pipeline.on_message(next_minute_tick)

        self.assertEqual(len(self.evaluated), 1)
        bar = self.evaluated[0][0]
        self.assertEqual(bar.timestamp, start)
        self.assertEqual(
            (bar.open, bar.high, bar.low, bar.close),
            (100.0, 100.0, 100.0, 100.0),
        )


if __name__ == "__main__":
    unittest.main()
