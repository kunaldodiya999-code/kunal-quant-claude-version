import unittest
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from paper_trading.entry_adapter import (
    PaperEntryAdapter,
    PaperEntryAdapterConfig,
)
from paper_trading.engine import PaperStrategyId
from paper_trading.signals import PaperSignal
from strategies.option_contract_resolver import ResolvedOptionContract


TZ = ZoneInfo("Asia/Kolkata")
ENTRY_TS = int(datetime(2026, 10, 13, 10, 0, tzinfo=TZ).timestamp())


@dataclass
class FakeResolver:
    symbol: str = "NSE:NIFTY2610025000CE"
    calls: list | None = None

    def resolve(self, *, underlying_price, entry_date, direction):
        if self.calls is not None:
            self.calls.append((underlying_price, entry_date, direction))
        if underlying_price <= 0:
            raise ValueError("bad underlying")
        if direction not in ("LONG", "SHORT"):
            raise ValueError("bad direction")
        option_type = "CE" if direction == "LONG" else "PE"
        return ResolvedOptionContract(
            instrument_id=123,
            symbol=self.symbol.replace("CE", option_type),
            underlying="NIFTY",
            expiry_date=date(2026, 10, 27),
            strike=25000,
            option_type=option_type,
        )


def make_signal(direction="LONG"):
    return PaperSignal(
        strategy_id=PaperStrategyId.STRATEGY_A,
        direction=direction,
        timestamp=ENTRY_TS,
        index=10,
        reason="test",
    )


def make_quote(symbol="NSE:NIFTY2610025000CE", price=100.0, timestamp=ENTRY_TS):
    return {"symbol": symbol, "lp": price, "exch_feed_time": timestamp}


class PaperEntryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.resolver = FakeResolver()
        self.adapter = PaperEntryAdapter(self.resolver)

    def test_valid_signal_resolves_contract_and_uses_option_quote(self):
        candidate = self.adapter.prepare_entry(
            signal=make_signal(),
            underlying_price=25012.0,
            option_quote=make_quote(),
        )
        self.assertEqual(candidate.contract.symbol, "NSE:NIFTY2610025000CE")
        self.assertEqual(candidate.contract.option_type, "CE")
        self.assertEqual(candidate.entry_price, 100.0)
        self.assertEqual(candidate.entry_timestamp, ENTRY_TS)

    def test_short_signal_resolves_put(self):
        candidate = self.adapter.prepare_entry(
            signal=make_signal("SHORT"),
            underlying_price=25012.0,
            option_quote=make_quote("NSE:NIFTY2610025000PE"),
        )
        self.assertEqual(candidate.contract.option_type, "PE")
        self.assertEqual(candidate.contract.symbol, "NSE:NIFTY2610025000PE")

    def test_rejects_zero_negative_and_nonfinite_prices(self):
        for price in (0, -1, float("nan"), float("inf")):
            with self.subTest(price=price), self.assertRaises(ValueError):
                self.adapter.prepare_entry(
                    signal=make_signal(),
                    underlying_price=25000,
                    option_quote=make_quote(price=price),
                )

    def test_rejects_mismatched_quote_symbol(self):
        with self.assertRaisesRegex(ValueError, "symbol mismatch"):
            self.adapter.prepare_entry(
                signal=make_signal(),
                underlying_price=25000,
                option_quote=make_quote("NSE:WRONG"),
            )

    def test_rejects_stale_quote(self):
        with self.assertRaisesRegex(ValueError, "stale"):
            self.adapter.prepare_entry(
                signal=make_signal(),
                underlying_price=25000,
                option_quote=make_quote(timestamp=ENTRY_TS - 6),
            )

    def test_rejects_future_quote_timestamp(self):
        with self.assertRaisesRegex(ValueError, "later than"):
            self.adapter.prepare_entry(
                signal=make_signal(),
                underlying_price=25000,
                option_quote=make_quote(timestamp=ENTRY_TS + 1),
            )

    def test_rejects_missing_price_or_timestamp(self):
        for payload in (
            {"symbol": "NSE:NIFTY2610025000CE", "exch_feed_time": ENTRY_TS},
            {"symbol": "NSE:NIFTY2610025000CE", "lp": 100},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.adapter.prepare_entry(
                    signal=make_signal(),
                    underlying_price=25000,
                    option_quote=payload,
                )

    def test_quote_must_match_resolved_contract_not_just_be_a_valid_price(self):
        self.resolver.symbol = "NSE:NIFTY2610025100CE"
        with self.assertRaisesRegex(ValueError, "symbol mismatch"):
            self.adapter.prepare_entry(
                signal=make_signal(),
                underlying_price=25000,
                option_quote=make_quote("NSE:NIFTY2610025000CE"),
            )

    def test_quote_age_limit_is_configurable(self):
        adapter = PaperEntryAdapter(
            self.resolver,
            PaperEntryAdapterConfig(max_quote_age_seconds=10),
        )
        candidate = adapter.prepare_entry(
            signal=make_signal(),
            underlying_price=25000,
            option_quote=make_quote(timestamp=ENTRY_TS - 10),
        )
        self.assertEqual(candidate.entry_price, 100.0)


if __name__ == "__main__":
    unittest.main()
