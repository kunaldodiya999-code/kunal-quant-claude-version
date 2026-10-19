import unittest

from market_data.fyers_quote_cache import FyersQuoteCache
from paper_trading.fyers_feed import FyersPaperFeed


class FakeSocket:
    def __init__(self):
        self.callbacks = {}
        self.subscriptions = []
        self.connected_calls = 0
        self.closed = False

    def connect(self):
        self.connected_calls += 1
        self.callbacks["on_connect"]()

    def subscribe(self, *, symbols, data_type):
        self.subscriptions.append((tuple(symbols), data_type))

    def close(self):
        self.closed = True


class FakePipeline:
    def __init__(self):
        self.messages = []

    def on_message(self, message):
        self.messages.append(message)
        return []


class FakeClient:
    def __init__(self):
        self.socket = FakeSocket()

    def create_data_socket(self, **callbacks):
        self.socket.callbacks = callbacks
        return self.socket


class FyersPaperFeedTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.pipeline = FakePipeline()
        self.cache = FyersQuoteCache(receive_clock=lambda: 1000.0)
        self.feed = FyersPaperFeed(
            client=self.client,
            pipeline=self.pipeline,
            quote_cache=self.cache,
            underlying_symbols=["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX", "NSE:NIFTY50-INDEX"],
        )

    def test_start_connects_and_subscribes_underlyings(self):
        self.feed.start()
        self.assertEqual(self.client.socket.connected_calls, 1)
        self.assertEqual(
            self.client.socket.subscriptions,
            [(("NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"), "SymbolUpdate")],
        )
        self.assertTrue(self.feed.status().connected)

    def test_tick_is_forwarded_and_quote_cached(self):
        self.feed.start()
        tick = {
            "symbol": "NSE:NIFTY50-INDEX",
            "ltp": 25000,
            "exch_feed_time": 1000,
        }
        self.client.socket.callbacks["on_message"](tick)
        self.assertEqual(self.pipeline.messages, [tick])
        self.assertEqual(
            self.cache.get_quote("NSE:NIFTY50-INDEX", decision_timestamp=1000)["lp"],
            25000,
        )
        self.assertEqual(self.feed.status().messages_received, 1)

    def test_option_symbol_subscription_is_deduplicated(self):
        self.feed.start()
        added = self.feed.subscribe_symbols(["NSE:NIFTY2610025000PE", "NSE:NIFTY2610025000PE"])
        self.assertEqual(added, ("NSE:NIFTY2610025000PE",))
        self.assertEqual(
            self.client.socket.subscriptions[-1],
            (("NSE:NIFTY2610025000PE",), "SymbolUpdate"),
        )
        self.assertEqual(self.feed.subscribe_symbols(["NSE:NIFTY2610025000PE"]), ())

    def test_subscription_before_connect_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "before the FYERS socket"):
            self.feed.subscribe_symbols(["NSE:NIFTY2610025000PE"])

    def test_close_marks_disconnected_and_closes_socket(self):
        self.feed.start()
        self.feed.close()
        self.assertTrue(self.client.socket.closed)
        self.assertFalse(self.feed.status().connected)

    def test_socket_error_is_visible_in_status(self):
        self.feed.on_error(RuntimeError("socket failed"))
        self.assertEqual(self.feed.status().last_error, "socket failed")

    def test_empty_underlying_symbols_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "At least one underlying"):
            FyersPaperFeed(
                client=self.client,
                pipeline=self.pipeline,
                quote_cache=self.cache,
                underlying_symbols=[],
            )


if __name__ == "__main__":
    unittest.main()
