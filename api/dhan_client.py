"""Minimal read-only client for DhanHQ rolling/expired options history.

This client intentionally contains no order-placement methods. Credentials are
read from the local .env file and are never printed or written to responses.
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

ROLLING_OPTIONS_URL = "https://api.dhan.co/v2/charts/rollingoption"
NIFTY_SECURITY_ID = 13
MAX_RANGE_DAYS = 30
ALLOWED_INTERVALS = {"1", "5", "15", "25", "60"}
ALLOWED_DATA = {"open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"}
DEFAULT_TIMEOUT_RETRIES = 2
RETRY_BACKOFF_SECONDS = 1.0
TRANSIENT_HTTP_CODES = {502, 503, 504}


class DhanAPIError(RuntimeError):
    """Safe-to-display Dhan API error; never includes request headers."""


def _validate_dates(from_date: str, to_date: str) -> None:
    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD format.") from exc
    span = (end - start).days
    if span <= 0:
        raise ValueError("to_date must be later than from_date.")
    if span > MAX_RANGE_DAYS:
        raise ValueError("Dhan rolling-options requests are limited to 30 calendar days.")


def build_rolling_options_payload(
    *,
    from_date: str,
    to_date: str,
    expiry_flag: str = "WEEK",
    expiry_code: int = 1,
    strike: str = "ATM",
    option_type: str = "CALL",
    interval: str = "1",
    required_data: list[str] | None = None,
    security_id: int = NIFTY_SECURITY_ID,
) -> dict[str, Any]:
    """Validate and build one documented Dhan rolling-options request."""
    _validate_dates(from_date, to_date)
    expiry_flag = expiry_flag.upper()
    option_type = option_type.upper()
    interval = str(interval)
    strike = strike.upper()

    if expiry_flag not in {"WEEK", "MONTH"}:
        raise ValueError("expiry_flag must be WEEK or MONTH.")
    # For /charts/rollingoption, Dhan support documents endpoint-specific mapping:
    # 1 = near expiry, 2 = next expiry, 3 = far expiry. Code 0 returns DH-905.
    if expiry_code not in {1, 2, 3}:
        raise ValueError("expiry_code must be 1, 2, or 3 for rolling/expired options.")
    if option_type not in {"CALL", "PUT"}:
        raise ValueError("option_type must be CALL or PUT.")
    if interval not in ALLOWED_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(ALLOWED_INTERVALS)}.")
    if not (strike == "ATM" or
            (strike.startswith("ATM+") and strike[4:].isdigit() and 1 <= int(strike[4:]) <= 10) or
            (strike.startswith("ATM-") and strike[4:].isdigit() and 1 <= int(strike[4:]) <= 10)):
        raise ValueError("strike must be ATM or ATM +/- 1..10 for index options.")
    if not isinstance(security_id, int) or security_id <= 0:
        raise ValueError("security_id must be a positive integer.")

    data_fields = required_data or ["open", "high", "low", "close", "iv", "volume", "strike", "oi", "spot"]
    invalid = set(data_fields) - ALLOWED_DATA
    if invalid:
        raise ValueError(f"Unsupported required_data fields: {sorted(invalid)}.")
    if not data_fields:
        raise ValueError("required_data cannot be empty.")

    return {
        "exchangeSegment": "NSE_FNO",
        "interval": interval,
        "securityId": security_id,
        "instrument": "OPTIDX",
        "expiryFlag": expiry_flag,
        "expiryCode": expiry_code,
        "strike": strike,
        "drvOptionType": option_type,
        "requiredData": data_fields,
        "fromDate": from_date,
        "toDate": to_date,
    }


class DhanClient:
    """Read-only DhanHQ Data API client."""

    def __init__(
        self,
        access_token: str | None = None,
        timeout: float = 30.0,
        timeout_retries: int = DEFAULT_TIMEOUT_RETRIES,
        retry_backoff_seconds: float = RETRY_BACKOFF_SECONDS,
    ):
        self.access_token = (access_token or os.getenv("DHAN_ACCESS_TOKEN", "")).strip()
        self.timeout = float(timeout)
        self.timeout_retries = int(timeout_retries)
        self.retry_backoff_seconds = float(retry_backoff_seconds)
        if self.timeout_retries < 0:
            raise ValueError("timeout_retries must be >= 0.")
        if self.retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be >= 0.")
        if not self.access_token:
            raise RuntimeError(
                "DHAN_ACCESS_TOKEN is missing. Add it to the local .env file; "
                "never paste it into chat or commit it."
            )

    def rolling_options(self, **kwargs: Any) -> dict[str, Any]:
        payload = build_rolling_options_payload(**kwargs)
        request = Request(
            ROLLING_OPTIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "access-token": self.access_token,
            },
            method="POST",
        )
        attempts = self.timeout_retries + 1
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    status = response.status
                break
            except TimeoutError:
                if attempt >= self.timeout_retries:
                    raise DhanAPIError(
                        f"Dhan API read timed out after {attempts} attempts."
                    ) from None
                if self.retry_backoff_seconds:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
            except HTTPError as exc:
                # Do not expose request headers or the access token.
                body = exc.read().decode("utf-8", errors="replace")[:1500]
                if exc.code in TRANSIENT_HTTP_CODES and attempt < self.timeout_retries:
                    if self.retry_backoff_seconds:
                        time.sleep(self.retry_backoff_seconds * (attempt + 1))
                    continue
                raise DhanAPIError(f"Dhan HTTP {exc.code}: {body}") from None
            except URLError as exc:
                raise DhanAPIError(f"Could not reach Dhan API: {exc.reason}") from None
        else:
            raise DhanAPIError("Dhan API request failed unexpectedly.")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise DhanAPIError(f"Dhan returned non-JSON content (HTTP {status}).") from None
        if not isinstance(result, dict):
            raise DhanAPIError("Dhan returned an unexpected response type.")
        if status >= 400:
            raise DhanAPIError(f"Dhan HTTP {status}: {str(result)[:1500]}")
        if result.get("errorCode") or result.get("errorType"):
            raise DhanAPIError(
                f"Dhan API error {result.get('errorCode', result.get('errorType'))}: "
                f"{result.get('errorMessage', result.get('errorDescription', 'request failed'))}"
            )
        return result
