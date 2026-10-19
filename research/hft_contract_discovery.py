"""HFT historical contract discovery helpers.

Research-only HFT layer. This module does not modify the locked
Option Contract Resolver V2.

The resolver here is deliberately FYERS-driven:
- historical option expiry dates come from FYERS
- historical futures expiry dates come from FYERS
- exact expired contract symbols come from FYERS
- the historical NIFTY 1m opening price determines the daily ATM ladder

This avoids assuming a fixed weekly-expiry calendar across all history.
"""
from __future__ import annotations
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from api.fyers_client import FyersClient

UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
_OPTION_RE = re.compile(r"^(?P<body>.+?)(?P<type>CE|PE)$", re.IGNORECASE)

def _date_chunks(start: date, end: date, days: int = 365):
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=days), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)

def _parse_expiry_value(value) -> date | None:
    # FYERS may expose expiry as ISO text, epoch seconds, or nested metadata.
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            pass
        if text.isdigit():
            try:
                return datetime.fromtimestamp(int(text), tz=timezone.utc).date()
            except (OverflowError, OSError, ValueError):
                return None
        return None
    if isinstance(value, dict):
        for key in ("expiry_date", "expiryDate", "expiry", "date", "expiryDateEpoch"):
            parsed = _parse_expiry_value(value.get(key))
            if parsed:
                return parsed
    return None

def _iter_expiry_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _iter_expiry_values(nested)
    elif isinstance(value, (list, tuple, set)):
        for nested in value:
            yield from _iter_expiry_values(nested)
    else:
        yield value

def extract_expiry_dates(response: dict, contract_type: str) -> set[date]:
    data = response.get("data") or {}
    expiry_dates = data.get("expiry_dates") or {}
    values = expiry_dates.get(contract_type) or []
    return {
        parsed
        for value in _iter_expiry_values(values)
        if (parsed := _parse_expiry_value(value))
    }

def discover_expiry_dates(client: FyersClient, start: date, end: date) -> tuple[set[date], set[date]]:
    futures: set[date] = set()
    options: set[date] = set()
    # range_to must include the future expiry after the trade date; a one-day
    # request ending on the trade date can legitimately return no expiry.
    query_end = min(end + timedelta(days=45), date.today() - timedelta(days=1))
    if query_end < start:
        query_end = start
    for chunk_start, chunk_end in _date_chunks(start, query_end):
        response = client.expired_expiry_dates(
            symbol=UNDERLYING_SYMBOL,
            range_from=chunk_start.isoformat(),
            range_to=chunk_end.isoformat(),
        )
        futures.update(extract_expiry_dates(response, "futures"))
        options.update(extract_expiry_dates(response, "options"))
    return futures, options

def nearest_expiry(trade_date: date, expiries: Iterable[date]) -> date | None:
    eligible = sorted(expiry for expiry in expiries if expiry >= trade_date)
    return eligible[0] if eligible else None

def _month_tokens(expiry: date) -> list[str]:
    year = expiry.strftime("%y")
    month_number = expiry.strftime("%m")
    month_no_zero = str(int(month_number))
    month_short = expiry.strftime("%b").upper()
    day = expiry.strftime("%d")
    return [
        year + month_short + day,
        year + month_short,
        year + month_number + day,
        year + month_no_zero + day,
        year + month_number,
        year + month_no_zero,
    ]

def option_strike_and_type(symbol: str, expiry: date) -> tuple[int, str] | None:
    ticker = symbol.split(":", 1)[-1].upper()
    match = _OPTION_RE.match(ticker)
    if not match:
        return None
    option_type = match.group("type").upper()
    body = match.group("body")
    for token in sorted(_month_tokens(expiry), key=len, reverse=True):
        index = body.find(token)
        if index <= 0:
            continue
        strike_text = body[index + len(token):]
        if strike_text.isdigit():
            return int(strike_text), option_type
    return None

def extract_contracts(response: dict) -> tuple[list[object], list[object]]:
    data = response.get("data") or {}
    contracts = data.get("contracts") or {}
    return contracts.get("futures") or [], contracts.get("options") or []

def contract_symbol(contract: object) -> str | None:
    if isinstance(contract, str):
        return contract.strip() or None
    if isinstance(contract, dict):
        for key in ("symbol", "symTicker", "fySymbol", "ticker"):
            value = contract.get(key)
            if value:
                return str(value).strip()
    return None

def find_option_symbols(response: dict, expiry: date, required: set[tuple[int, str]]) -> dict[tuple[int, str], str]:
    _, options = extract_contracts(response)
    found: dict[tuple[int, str], str] = {}
    for contract in options:
        symbol = contract_symbol(contract)
        if not symbol:
            continue
        parsed = option_strike_and_type(symbol, expiry)
        if parsed in required and parsed not in found:
            found[parsed] = symbol
    return found

def find_nearest_future_symbol(response: dict) -> str | None:
    futures, _ = extract_contracts(response)
    symbols = [contract_symbol(item) for item in futures]
    symbols = [s for s in symbols if s and s.endswith("FUT")]
    return sorted(symbols)[0] if symbols else None
