import unittest

from market_data.fyers_quote_cache import FyersQuoteCache


class FyersQuoteCacheTests(unittest.TestCase):
    def setUp(self):
        self.receive_time = 1000.0
        self.cache = FyersQuoteCache(receive_clock=lambda: self.receive_time)
        self.message = {
            "symbol": "NSE:NIFTY2610025000PE",
            "ltp": 101.25,
            "exch_feed_time": 1000,
        }

    def test_valid_quote_is_normalized_for_entry_adapter(self):
        self.assertTrue(self.cache.update(self.message))
        quote = self.cache.get_quote(
            "NSE:NIFTY2610025000PE", decision_timestamp=1001
        )
        self.assertEqual(
            quote,
            {
                "symbol": "NSE:NIFTY2610025000PE",
                "lp": 101.25,
                "exch_feed_time": 1000,
            },
        )

    def test_missing_exchange_timestamp_is_rejected_not_fabricated(self):
        message = {"symbol": "NSE:NIFTY2610025000PE", "ltp": 101.25}
        self.assertFalse(self.cache.update(message))
        with self.assertRaises(LookupError):
            self.cache.get_quote(
                "NSE:NIFTY2610025000PE", decision_timestamp=1001
            )

    def test_old_exchange_timestamp_is_rejected(self):
        self.cache.update(self.message)
        with self.assertRaisesRegex(LookupError, "exchange time"):
            self.cache.get_quote(
                "NSE:NIFTY2610025000PE",
                decision_timestamp=1008,
                max_exchange_age_seconds=5,
            )

    def test_old_local_receipt_is_rejected_even_if_exchange_time_is_fresh(self):
        self.cache.update(self.message)
        with self.assertRaisesRegex(LookupError, "receipt age"):
            self.cache.get_quote(
                "NSE:NIFTY2610025000PE",
                decision_timestamp=1001,
                max_receive_age_seconds=2,
                now_received_at=1003.1,
            )

    def test_out_of_order_packet_does_not_replace_newer_quote(self):
        self.cache.update({**self.message, "exch_feed_time": 1001, "ltp": 102})
        self.assertFalse(
            self.cache.update({**self.message, "exch_feed_time": 1000, "ltp": 99})
        )
        quote = self.cache.get_quote(
            "NSE:NIFTY2610025000PE", decision_timestamp=1002
        )
        self.assertEqual(quote["lp"], 102)

    def test_millisecond_epoch_is_normalized(self):
        self.assertTrue(
            self.cache.update(
                {
                    "symbol": "NSE:NIFTY2610025000PE",
                    "ltp": 101,
                    "timestamp": 1_000_000_000_000,
                }
            )
        )
        quote = self.cache.get_quote(
            "NSE:NIFTY2610025000PE", decision_timestamp=1_000_000_001
        )
        self.assertEqual(quote["exch_feed_time"], 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
