from __future__ import annotations

import unittest


class FyersExpiredDownloaderTests(unittest.TestCase):
    def test_extract_contracts_from_nested_options(self):
        from scripts.download_fyers_expired_options import extract_contracts

        response = {"data": {"contracts": {"options": [
            {"symbol": "NSE:NIFTY2691525000CE", "strike": 25000},
            {"symbol": "NSE:NIFTY2691525000PE", "strike": 25000},
            {"symbol": "NSE:NIFTY2691525050CE", "strike": 25050},
        ]}}}
        contracts = extract_contracts(response)
        self.assertEqual(
            [(x["symbol"], x["strike"], x["side"]) for x in contracts],
            [
                ("NSE:NIFTY2691525000CE", 25000.0, "CE"),
                ("NSE:NIFTY2691525000PE", 25000.0, "PE"),
                ("NSE:NIFTY2691525050CE", 25050.0, "CE"),
            ],
        )

    def test_extract_contracts_from_bare_symbol_strings(self):
        from scripts.download_fyers_expired_options import extract_contracts

        response = {
            "s": "ok",
            "data": {
                "contracts": [
                    "NSE:NIFTY24O2424000CE",
                    "NSE:NIFTY24O2424000PE",
                ]
            },
        }
        contracts = extract_contracts(response)
        self.assertEqual(
            [(x["symbol"], x["strike"], x["side"]) for x in contracts],
            [
                ("NSE:NIFTY24O2424000CE", 24000.0, "CE"),
                ("NSE:NIFTY24O2424000PE", 24000.0, "PE"),
            ],
        )

    def test_normalize_candles_uses_named_columns_and_preserves_missing_greeks(self):
        from scripts.download_fyers_expired_options import normalize_candles

        response = {
            "s": "ok",
            "columns": [
                "timestamp", "open", "high", "low", "close", "volume",
                "open_interest", "implied_volatility", "delta", "gamma", "theta", "vega",
            ],
            "candles": [[1000, 10, 11, 9, 10.5, 100, 500, None, None, None, None, None]],
        }
        rows = normalize_candles(response, {"symbol": "NSE:TESTCE", "strike": 25000.0, "side": "CE"}, "2026-09-15")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "NSE:TESTCE")
        self.assertEqual(rows[0]["open_interest"], 500)
        self.assertIsNone(rows[0]["implied_volatility"])
        self.assertIsNone(rows[0]["delta"])

    def test_no_data_response_is_classified_without_being_success(self):
        from scripts.download_fyers_expired_options import is_no_data_response

        self.assertTrue(is_no_data_response({"s": "no_data"}))
        self.assertFalse(is_no_data_response({"s": "ok", "candles": []}))
        self.assertFalse(is_no_data_response({"s": "error"}))

    def test_validate_columns_rejects_unknown_or_short_payloads(self):
        from scripts.download_fyers_expired_options import validate_response_shape

        bad = {"s": "ok", "columns": ["timestamp", "open"], "candles": [[1, 2]]}
        with self.assertRaisesRegex(ValueError, "required columns"):
            validate_response_shape(bad)

    def test_cached_catalog_is_invalid_when_empty(self):
        from pathlib import Path
        from scripts.download_fyers_expired_options import cached_catalog_is_valid

        response_path = Path("cached-contracts.json")
        response_path.write_text("{}", encoding="utf-8")
        try:
            self.assertFalse(cached_catalog_is_valid({
                "contract_count": 0,
                "contracts": [],
            }, response_path))
            self.assertFalse(cached_catalog_is_valid({
                "contract_count": 1,
                "contracts": [],
            }, response_path))
        finally:
            response_path.unlink()

    def test_cached_catalog_is_valid_when_non_empty_and_consistent(self):
        from pathlib import Path
        from scripts.download_fyers_expired_options import cached_catalog_is_valid

        response_path = Path("cached-contracts.json")
        response_path.write_text("{}", encoding="utf-8")
        try:
            self.assertTrue(cached_catalog_is_valid({
                "contract_count": 1,
                "contracts": [{"symbol": "NSE:NIFTY24O2424000CE"}],
            }, response_path))
            self.assertFalse(cached_catalog_is_valid({
                "contract_count": 2,
                "contracts": [{"symbol": "NSE:NIFTY24O2424000CE"}],
            }, response_path))
        finally:
            response_path.unlink()

    def test_select_contracts_requires_explicit_filters(self):
        from scripts.download_fyers_expired_options import select_contracts

        contracts = [
            {"symbol": "A", "strike": 24000.0, "side": "CE"},
            {"symbol": "B", "strike": 25000.0, "side": "CE"},
            {"symbol": "C", "strike": 26000.0, "side": "PE"},
        ]
        self.assertEqual(select_contracts(contracts, None, None, None), contracts)
        self.assertEqual(
            [x["symbol"] for x in select_contracts(contracts, 24500, 25500, None)],
            ["B"],
        )
        self.assertEqual(
            [x["symbol"] for x in select_contracts(contracts, None, None, "CE")],
            ["A", "B"],
        )
        self.assertEqual(
            [x["symbol"] for x in select_contracts(contracts, None, None, None, ["C", "A"])],
            ["A", "C"],
        )

    def test_build_expiry_windows_respects_fyers_366_day_limit(self):
        from scripts.download_fyers_expired_options import build_expiry_windows

        windows = build_expiry_windows("2025-10-12", "2026-10-11")
        self.assertTrue(windows)
        self.assertTrue(all(
            (windows[i][1] and __import__("datetime").date.fromisoformat(windows[i][1]) -
             __import__("datetime").date.fromisoformat(windows[i][0])).days <= 366
            for i in range(len(windows))
        ))
