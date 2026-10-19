"""Targeted FYERS expired-contract discovery for historical option research.

This module is deliberately separate from the locked OptionContractResolver V2.
It resolves exact historical contracts from FYERS' expired F&O contract endpoint
using the historically-correct expiry/strike/option-type tuple from an acquisition
manifest.

Discovery is read-only. Database registration is intentionally handled separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable
import re

from api.fyers_client import FyersClient


@dataclass(frozen=True)
class HistoricalContract:
    symbol: str
    expiry_date: date
    strike: float
    option_type: str
    raw: dict[str, Any]


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    return None


def _normalise_option_type(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if text in {"CE", "CALL"}:
        return "CE"
    if text in {"PE", "PUT"}:
        return "PE"
    return None


def _normalise_contract(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        return {"symbol": item}
    if not isinstance(item, dict):
        return None

    symbol = _first(item, "symbol", "fyTokenSymbol", "contract_symbol", "underlying_symbol")
    result = dict(item)
    if symbol is not None:
        result["symbol"] = str(symbol).strip()
    return result


def extract_option_contracts(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract option contract records from the FYERS response.

    FYERS documents the response under data -> contracts -> options. The parser
    accepts list/dict variants so harmless SDK response-shape changes do not
    silently break discovery.
    """
    data = _as_dict(response.get("data"))
    contracts = _as_dict(data.get("contracts"))

    candidates: Any = contracts.get("options")
    if candidates is None:
        candidates = data.get("options")
    if candidates is None:
        candidates = response.get("options")

    if isinstance(candidates, dict):
        candidates = list(candidates.values())
    if not isinstance(candidates, list):
        return []

    result: list[dict[str, Any]] = []
    for item in candidates:
        normalised = _normalise_contract(item)
        if normalised and normalised.get("symbol"):
            strike = _contract_strike(normalised)
            option_type = _contract_option_type(normalised)
            if strike is not None:
                normalised["strike"] = strike
            if option_type is not None:
                normalised["option_type"] = option_type
            result.append(normalised)
    return result


def _contract_strike(contract: dict[str, Any], expiry_date: date | None = None) -> float | None:
    value = _first(contract, "strike", "strike_price", "strikePrice")
    if value is not None:
        try:
            numeric = float(value)
            if 1000 <= numeric <= 100000:
                return numeric
        except (TypeError, ValueError):
            pass

    symbol = str(contract.get("symbol", "")).strip().upper()
    if expiry_date is not None:
        # FYERS weekly NIFTY symbology uses numeric month digits for Jan-Sep
        # and O/N/D for Oct/Nov/Dec, followed by two-digit expiry day.
        month_token = str(expiry_date.month) if expiry_date.month <= 9 else {10: "O", 11: "N", 12: "D"}[expiry_date.month]
        prefix = f"NIFTY{expiry_date:%y}{month_token}{expiry_date:%d}"
        if symbol.startswith("NSE:" + prefix):
            suffix = symbol[len("NSE:" + prefix):]
            suffix = re.sub(r"(?:CE|PE)$", "", suffix)
            try:
                return float(suffix)
            except ValueError:
                pass

    # Fallback: the strike is the final numeric run immediately before CE/PE.
    # This also handles symbols such as NIFTY24O1019550CE.
    match = re.search(r"(\d+)(?:CE|PE)$", symbol)
    if match:
        numeric = float(match.group(1))
        return numeric if 1000 <= numeric <= 100000 else None
    return None


def _contract_option_type(contract: dict[str, Any]) -> str | None:
    explicit = _normalise_option_type(
        _first(contract, "option_type", "optionType", "optiontype", "type")
    )
    if explicit is not None:
        return explicit

    symbol = str(contract.get("symbol", "")).strip().upper()
    if symbol.endswith("CE"):
        return "CE"
    if symbol.endswith("PE"):
        return "PE"
    return None


def filter_exact_option(
    contracts: Iterable[dict[str, Any]],
    *,
    strike: float,
    option_type: str,
) -> list[dict[str, Any]]:
    """Return contracts matching strike and CE/PE exactly."""
    wanted_type = _normalise_option_type(option_type)
    if wanted_type is None:
        raise ValueError("option_type must be CE or PE")

    matches: list[dict[str, Any]] = []
    for contract in contracts:
        contract_strike = _contract_strike(contract)
        contract_type = _contract_option_type(contract)
        if contract_strike == float(strike) and contract_type == wanted_type:
            matches.append(contract)
    return matches


class FyersHistoricalContractDiscovery:
    """Read-only targeted discovery against FYERS expired F&O contracts."""

    def __init__(self, client: FyersClient | None = None) -> None:
        self.client = client or FyersClient()

    def discover_expiry(self, expiry_date: date) -> list[dict[str, Any]]:
        response = self.client.expired_contracts(
            symbol="NSE:NIFTY50-INDEX",
            expiry_date=expiry_date.isoformat(),
        )
        contracts = extract_option_contracts(response)
        for contract in contracts:
            strike = _contract_strike(contract, expiry_date)
            option_type = _contract_option_type(contract)
            if strike is not None:
                contract["strike"] = strike
            if option_type is not None:
                contract["option_type"] = option_type
        return contracts

    def discover_exact(
        self,
        expiry_date: date,
        strike: float,
        option_type: str,
    ) -> list[dict[str, Any]]:
        return filter_exact_option(
            self.discover_expiry(expiry_date),
            strike=strike,
            option_type=option_type,
        )
