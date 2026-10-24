import unittest

from market_data.live_ticks import LiveMinuteBarBuilder


class LiveMinuteBarBuilderTests(unittest.TestCase):
    def setUp(self):
        self.builder = LiveMinuteBarBuilder()

    def tick(self, symbol, timestamp, ltp):
        return {
            "symbol": symbol,
            "last_traded_time": timestamp,
            "ltp": ltp,
            "type": "sf",
        }

    def test_emits_only_after_next_minute_arrives(self):
        self.assertEqual(
            self.builder.on_message(self.tick("NSE:NIFTY50-INDEX", 1_760_000_401, 100.0)),
            [],
        )
        self.assertEqual(
            self.builder.on_message(self.tick("NSE:NIFTY50-INDEX", 1_760_000_425, 103.0)),
            [],
        )
        completed = self.builder.on_message(
            self.tick("NSE:NIFTY50-INDEX", 1_760_000_460, 101.0)
        )
        self.assertEqual(len(completed), 1)
        bar = completed[0]
        self.assertEqual(bar.timestamp, (1_760_000_401 // 60) * 60)
        self.assertEqual((bar.open, bar.high, bar.low, bar.close), (100.0, 103.0, 100.0, 103.0))
        self.assertIsNone(bar.volume)

    def test_accepts_actual_fyers_exchange_feed_time_packet(self):
        # Shape observed in fyers_websocket_test.py:
        # {'ltp': ..., 'exch_feed_time': ..., 'type': 'if',
        #  'symbol': 'NSE:NIFTY50-INDEX'}
        timestamp = 1_791_887_369
        first = {
            "ltp": 22721.95,
            "exch_feed_time": timestamp,
            "type": "if",
            "symbol": "NSE:NIFTY50-INDEX",
        }
        self.assertEqual(self.builder.on_message(first), [])
        current = self.builder.current_minute("NSE:NIFTY50-INDEX")
        self.assertIsNotNone(current)
        self.assertEqual(current.close, 22721.95)

        next_tick = {
            "ltp": 22722.0,
            "exch_feed_time": timestamp + 60,
            "type": "if",
            "symbol": "NSE:NIFTY50-INDEX",
        }
        completed = self.builder.on_message(next_tick)
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].close, 22721.95)

    def test_keeps_separate_bars_per_symbol(self):
        self.builder.on_message(self.tick("NSE:NIFTY50-INDEX", 1_760_000_401, 100))
        self.builder.on_message(self.tick("NSE:OTHER", 1_760_000_401, 200))
        completed = self.builder.on_message(self.tick("NSE:OTHER", 1_760_000_460, 201))
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].open, 200)
        self.assertIsNone(self.builder.current_minute("NSE:NIFTY50-INDEX").volume)

    def test_ignores_invalid_messages(self):
        self.assertEqual(self.builder.on_message(None), [])
        self.assertEqual(self.builder.on_message({"symbol": "X", "ltp": 10}), [])
        self.assertEqual(
            self.builder.on_message({"symbol": "X", "timestamp": 1_760_000_401, "ltp": float("nan")}),
            [],
        )
        self.assertIsNone(self.builder.current_minute("X"))

    def test_accepts_millisecond_timestamp_fallback(self):
        timestamp = 1_760_000_401
        self.assertEqual(
            self.builder.on_message(
                {"symbol": "X", "timestamp": timestamp * 1000, "ltp": 10}
            ),
            [],
        )
        current = self.builder.current_minute("X")
        self.assertIsNotNone(current)
        self.assertEqual(current.timestamp, (timestamp // 60) * 60)

    def test_ignores_late_ticks_and_does_not_synthesize_gap_bars(self):
        self.builder.on_message(self.tick("X", 1_760_000_401, 10))
        completed = self.builder.on_message(self.tick("X", 1_760_000_580, 12))
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].close, 10)
        # This tick belongs to the already-finalized minute and must not alter
        # the currently forming later candle.
        self.assertEqual(self.builder.on_message(self.tick("X", 1_760_000_430, 99)), [])
        current = self.builder.current_minute("X")
        self.assertEqual((current.open, current.high, current.low, current.close), (12, 12, 12, 12))

    def test_current_minute_is_a_snapshot_not_a_completed_bar(self):
        self.builder.on_message(self.tick("X", 1_760_000_401, 10))
        current = self.builder.current_minute("X")
        self.assertEqual((current.open, current.high, current.low, current.close), (10, 10, 10, 10))
        self.assertEqual(self.builder.on_message(self.tick("X", 1_760_000_420, 11)), [])
        current = self.builder.current_minute("X")
        self.assertEqual((current.open, current.high, current.low, current.close), (10, 11, 10, 11))


if __name__ == "__main__":
    unittest.main()
