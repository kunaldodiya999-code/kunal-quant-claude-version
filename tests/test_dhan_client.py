from __future__ import annotations

import unittest

from api.dhan_client import build_rolling_options_payload


class DhanPayloadTests(unittest.TestCase):
    def test_builds_documented_nifty_weekly_request(self):
        payload = build_rolling_options_payload(
            from_date="2026-10-06",
            to_date="2026-10-07",
            expiry_flag="WEEK",
            expiry_code=1,
            strike="ATM",
            option_type="CALL",
        )
        self.assertEqual(payload["exchangeSegment"], "NSE_FNO")
        self.assertEqual(payload["securityId"], 13)
        self.assertEqual(payload["instrument"], "OPTIDX")
        self.assertEqual(payload["drvOptionType"], "CALL")
        self.assertEqual(payload["expiryCode"], 1)
        self.assertIn("oi", payload["requiredData"])
        self.assertIn("strike", payload["requiredData"])

    def test_accepts_far_expiry_code_3(self):
        payload = build_rolling_options_payload(
            from_date="2026-10-06", to_date="2026-10-07", expiry_code=3
        )
        self.assertEqual(payload["expiryCode"], 3)

    def test_rejects_expiry_code_0(self):
        with self.assertRaisesRegex(ValueError, "1, 2, or 3"):
            build_rolling_options_payload(
                from_date="2026-10-06", to_date="2026-10-07", expiry_code=0
            )

    def test_rejects_more_than_30_days(self):
        with self.assertRaisesRegex(ValueError, "30 calendar days"):
            build_rolling_options_payload(
                from_date="2026-01-01", to_date="2026-02-01"
            )

    def test_rejects_bad_strike(self):
        with self.assertRaisesRegex(ValueError, "ATM"):
            build_rolling_options_payload(
                from_date="2026-10-06", to_date="2026-10-07", strike="ATM+11"
            )

    def test_rejects_bad_option_type(self):
        with self.assertRaisesRegex(ValueError, "CALL or PUT"):
            build_rolling_options_payload(
                from_date="2026-10-06", to_date="2026-10-07", option_type="CE"
            )


class DhanTimeoutRetryTests(unittest.TestCase):
    def test_rolling_options_retries_read_timeout(self):
        from unittest.mock import patch
        from api import dhan_client

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"data": {"ce": {"timestamp": [1]}}}'

        client = dhan_client.DhanClient(
            access_token="test-token",
            timeout=0.1,
            timeout_retries=2,
            retry_backoff_seconds=0,
        )
        with patch.object(dhan_client, "urlopen", side_effect=[TimeoutError(), TimeoutError(), FakeResponse()]) as mock_urlopen:
            result = client.rolling_options(
                from_date="2026-10-08",
                to_date="2026-10-09",
                interval="5",
            )

        self.assertEqual(result["data"]["ce"]["timestamp"], [1])
        self.assertEqual(mock_urlopen.call_count, 3)

    def test_rolling_options_retries_transient_gateway_error(self):
        from unittest.mock import patch
        from urllib.error import HTTPError
        from api import dhan_client

        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return b'{"data": {"ce": {"timestamp": [2]}}}'

        def gateway_error(code):
            return HTTPError(
                url="https://api.dhan.co/v2/charts/rollingoption",
                code=code,
                msg="gateway timeout",
                hdrs=None,
                fp=None,
            )

        client = dhan_client.DhanClient(
            access_token="test-token",
            timeout=0.1,
            timeout_retries=2,
            retry_backoff_seconds=0,
        )
        with patch.object(
            dhan_client,
            "urlopen",
            side_effect=[gateway_error(504), gateway_error(503), FakeResponse()],
        ) as mock_urlopen:
            result = client.rolling_options(
                from_date="2026-10-08",
                to_date="2026-10-09",
                interval="5",
            )

        self.assertEqual(result["data"]["ce"]["timestamp"], [2])
        self.assertEqual(mock_urlopen.call_count, 3)


class FyersExpiredContractParserTests(unittest.TestCase):
    def test_numeric_expiry_is_five_digits(self):
        from scripts.validate_fyers_expired_history import extract_contracts

        response = {"data": {"contracts": [
            {"symbol": "NSE:NIFTY2691518150CE"},
            {"symbol": "NSE:NIFTY2691518150PE"},
        ]}}
        contracts = extract_contracts(response)
        self.assertEqual([(c["strike"], c["side"]) for c in contracts],
                         [(18150.0, "CE"), (18150.0, "PE")])


class FyersExpiredHistoryQualityTests(unittest.TestCase):
    def test_numeric_quality_detects_duplicates_and_named_fields(self):
        from scripts.validate_fyers_expired_history import _numeric_quality

        candles = [
            [1000, 100, 110, 90, 105, 1000, 500, 0.5, 0.01],
            [1300, 105, 112, 100, 108, 1200, 520, 0.55, 0.02],
            [1300, 108, 113, 101, 109, 900, 0, 0.60, 0.0],
        ]
        result = _numeric_quality(
            candles,
            ["timestamp", "open", "high", "low", "close", "volume", "oi", "delta", "gamma"],
        )
        self.assertEqual(result["duplicate_timestamps"], 1)
        self.assertEqual(result["invalid_rows"], 0)
        self.assertEqual(result["field_stats"]["oi"]["zero_values"], 1)
        self.assertEqual(result["field_stats"]["delta"]["present_values"], 3)

    def test_numeric_quality_does_not_invent_fields_without_columns(self):
        from scripts.validate_fyers_expired_history import _numeric_quality

        result = _numeric_quality([[1000, 1, 2, 0, 1]], [])
        self.assertEqual(result["columns"], [])
        self.assertEqual(result["field_stats"], {})


class FyersSessionQualityTests(unittest.TestCase):
    def test_session_completeness_accepts_full_five_minute_session(self):
        from scripts.validate_fyers_expired_history import _session_completeness
        import datetime as dt
        base = int(dt.datetime(2026, 1, 5, 3, 45, tzinfo=dt.timezone.utc).timestamp())
        candles = [[base + i * 300, 1, 1, 1, 1] for i in range(75)]
        result = _session_completeness(candles, 5)
        self.assertEqual(result["expected_full_session_candles"], 75)
        self.assertEqual(result["full_sessions"], 1)
        self.assertEqual(result["partial_or_gap_sessions"], 0)

    def test_session_completeness_flags_missing_candle(self):
        from scripts.validate_fyers_expired_history import _session_completeness
        import datetime as dt
        base = int(dt.datetime(2026, 1, 5, 3, 45, tzinfo=dt.timezone.utc).timestamp())
        candles = [[base + i * 300, 1, 1, 1, 1] for i in range(75) if i != 20]
        result = _session_completeness(candles, 5)
        self.assertEqual(result["full_sessions"], 0)
        self.assertEqual(result["partial_or_gap_sessions"], 1)
        self.assertEqual(result["sessions"][0]["missing_expected_candles"], 1)


class DhanRollingDownloaderTests(unittest.TestCase):
    def test_build_chunks_never_exceeds_thirty_days_and_end_is_exclusive(self):
        from scripts.download_dhan_rolling_history import build_chunks

        chunks = build_chunks("2025-01-01", "2025-02-15")
        self.assertEqual(chunks[0], ("2025-01-01", "2025-01-31"))
        self.assertEqual(chunks[-1], ("2025-01-31", "2025-02-15"))
        self.assertTrue(all((__import__("datetime").date.fromisoformat(end) -
                             __import__("datetime").date.fromisoformat(start)).days <= 30
                            for start, end in chunks))

    def test_rows_from_response_keeps_actual_strike_and_request_label(self):
        from scripts.download_dhan_rolling_history import rows_from_response

        response = {"data": {"ce": {
            "timestamp": [1000, 1300], "strike": [22500, 22550],
            "close": [10.0, 11.0], "oi": [100, 120], "spot": [22520, 22560],
        }, "pe": None}}
        rows = rows_from_response(response, "CALL", "ATM+1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["strike"], 22550)
        self.assertEqual(rows[1]["request_strike"], "ATM+1")
        self.assertEqual(rows[1]["option_type"], "CALL")
        self.assertIsNone(rows[0]["iv"])

    def test_inspect_response_flags_mismatched_array_lengths(self):
        from scripts.download_dhan_rolling_history import inspect_response

        response = {"data": {"ce": {"timestamp": [1, 2], "close": [10.0], "oi": [100, 200]}}}
        quality = inspect_response(response, "CALL")
        self.assertEqual(quality["rows"], 2)
        self.assertEqual(quality["field_length_mismatches"], {"close": 1})


class DhanOfflineAuditTests(unittest.TestCase):
    def test_flatten_response_preserves_ist_timestamp_and_actual_strike(self):
        from scripts.audit_dhan_rolling_history import flatten_response
        from datetime import datetime, timezone

        timestamp = int(datetime(2026, 10, 8, 3, 45, tzinfo=timezone.utc).timestamp())
        response = {"data": {"ce": {
            "timestamp": [timestamp], "strike": [25000], "open": [100],
            "high": [110], "low": [95], "close": [105], "oi": [1200],
        }}}
        task = {
            "option_type": "CALL", "strike": "ATM+1", "expiry_flag": "WEEK",
            "expiry_code": 1, "from_date": "2026-10-08", "to_date": "2026-10-09",
        }
        rows, quality = flatten_response(response, task, "test_request")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date_ist"], "2026-10-08")
        self.assertEqual(rows[0]["time_ist"], "09:15:00")
        self.assertEqual(rows[0]["strike"], 25000)
        self.assertEqual(quality["field_length_mismatches"], {})


class DhanPlanOnlyTests(unittest.TestCase):
    def test_plan_only_does_not_require_credentials_or_write_files(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from scripts.download_dhan_rolling_history import main

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"DHAN_ACCESS_TOKEN": ""}, clear=False):
                with patch("sys.argv", [
                    "download_dhan_rolling_history.py",
                    "--from-date", "2026-10-08",
                    "--to-date", "2026-10-10",
                    "--output-dir", tmp,
                ]):
                    self.assertEqual(main(), 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class DhanResponseEnvelopeTests(unittest.TestCase):
    def test_error_envelope_is_not_success(self):
        from scripts.download_dhan_rolling_history import response_is_success
        self.assertFalse(response_is_success({"errorCode": "DH-905", "data": {}}))
        self.assertFalse(response_is_success({"status": "error", "data": {}}))

    def test_successful_data_envelope_is_accepted(self):
        from scripts.download_dhan_rolling_history import response_is_success
        self.assertTrue(response_is_success({"data": {"ce": {"timestamp": [1]}}}))


if __name__ == "__main__":
    unittest.main()
