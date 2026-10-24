"""Targeted acquisition of FYERS expired NIFTY option candles.

This layer discovers only the exact contracts required by the existing KTMI
event/resolver pipeline. It does not change resolver or strategy logic.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from api.fyers_client import FyersClient
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import (
    build_ktmi_config,
    load_complete_3m_bars,
)
from strategies.option_contract_resolver import OptionContractResolver
from downloader.historical import HistoricalDownloader

TZ = ZoneInfo("Asia/Kolkata")
UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
OPTION_SYMBOL_RE = re.compile(r"^(?P<prefix>NSE:NIFTY)(?P<body>\d+)(?P<type>CE|PE)$")


def _extract_symbols(value) -> set[str]:
    """Extract FYERS NIFTY option symbols from supported response shapes."""
    if not isinstance(value, dict):
        return set()

    data = value.get("data", {})
    if not isinstance(data, dict):
        return set()

    candidates: list[object] = []

    legacy_symbols = data.get("symbols", [])
    if isinstance(legacy_symbols, list):
        candidates.extend(legacy_symbols)

    contracts = data.get("contracts", {})
    if isinstance(contracts, dict):
        options = contracts.get("options", [])
        if isinstance(options, list):
            candidates.extend(options)

    return {
        symbol
        for symbol in candidates
        if isinstance(symbol, str)
        and symbol.startswith("NSE:NIFTY")
        and symbol.endswith(("CE", "PE"))
    }


def _strike_from_symbol(symbol: str) -> int | None:
    match = OPTION_SYMBOL_RE.match(symbol)
    if not match:
        return None
    body = match.group("body")
    if len(body) < 4:
        return None
    for width in (5, 4):
        if len(body) >= width:
            return int(body[-width:])
    return None


def _option_type_from_symbol(symbol: str) -> str | None:
    if symbol.endswith("CE"):
        return "CE"
    if symbol.endswith("PE"):
        return "PE"
    return None


def _discover_required_symbols(
    client: FyersClient,
    required_by_expiry: dict[str, dict[tuple[int, str], tuple[str, str]]],
) -> dict[tuple[str, int, str], str]:
    """
    Discover the exact FYERS option symbols required by the existing
    resolver/event pipeline.

    FYERS expired_contracts response structure is:

        {
            "data": {
                "symbol": "NIFTY",
                "expiry_date": "2026-09-22",
                "contracts": {
                    "futures": [],
                    "options": [
                        "NSE:NIFTY2692223250CE",
                        "NSE:NIFTY2692223250PE",
                        ...
                    ]
                }
            }
        }

    This function only matches contracts already required by the
    existing resolver/event pipeline.
    """
    discovered: dict[tuple[str, int, str], str] = {}

    for expiry, requirements in sorted(required_by_expiry.items()):
        response = client.expired_contracts(
            symbol=UNDERLYING_SYMBOL,
            expiry_date=expiry,
        )
        symbols = _extract_symbols(response)

        for symbol in symbols:
            strike = _strike_from_symbol(symbol)
            option_type = _option_type_from_symbol(symbol)

            if strike is None or option_type is None:
                continue

            requirement_key = (strike, option_type)

            if requirement_key in requirements:
                discovered[(expiry, strike, option_type)] = symbol

    return discovered


def _register_instrument(
    database_path: Path | str,
    symbol: str,
    expiry: str,
    strike: int,
    option_type: str,
    lot_size: int | None = None,
) -> int:
    with sqlite3.connect(database_path) as db:
        row = db.execute(
            "SELECT id FROM instruments WHERE broker='FYERS' AND symbol=?",
            (symbol,),
        ).fetchone()
        if row:
            return int(row[0])

        template = db.execute(
            """
            SELECT exchange, segment, lot_size, tick_size, currency
            FROM instruments
            WHERE broker='FYERS' AND underlying='NIFTY'
              AND instrument_type='OPTION'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

        exchange, segment, template_lot_size, tick_size, currency = (
            template if template else ("NSE", "11", 65, 0.05, "INR")
        )
        resolved_lot_size = int(lot_size) if lot_size is not None else int(template_lot_size)

        db.execute(
            """
            INSERT INTO instruments (
                broker, exchange, segment, symbol, underlying,
                instrument_type, expiry_date, strike, option_type,
                lot_size, tick_size, currency, is_active
            )
            VALUES (?, ?, ?, ?, 'NIFTY', 'OPTION', ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(broker, symbol) DO UPDATE SET
                expiry_date=excluded.expiry_date,
                strike=excluded.strike,
                option_type=excluded.option_type,
                is_active=1,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                "FYERS", exchange, segment, symbol, expiry,
                float(strike), option_type, resolved_lot_size, tick_size, currency,
            ),
        )
        db.commit()
        row = db.execute(
            "SELECT id FROM instruments WHERE broker='FYERS' AND symbol=?",
            (symbol,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Failed to register instrument: {symbol}")
        return int(row[0])


def build_required_contracts() -> tuple[dict[str, dict[tuple[int, str], tuple[str, str]]], int, int]:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())
    resolver = OptionContractResolver(DATABASE_PATH)

    required: dict[str, dict[tuple[int, str], tuple[str, str]]] = defaultdict(dict)
    for event in pipeline.events:
        bar = bars[event.index]
        entry_date = datetime.fromtimestamp(bar.timestamp, tz=TZ).date()
        option_type = "CE" if event.direction.value == "LONG" else "PE"
        expiry = resolver.find_nearest_expiry(entry_date, option_type)
        strike = resolver.calculate_atm_strike(bar.close)
        expiry_key = expiry.isoformat()
        key = (strike, option_type)
        event_date = entry_date.isoformat()
        previous = required[expiry_key].get(key)
        if previous is None:
            required[expiry_key][key] = (event_date, event_date)
        else:
            required[expiry_key][key] = (
                min(previous[0], event_date),
                max(previous[1], event_date),
            )

    return required, len(bars), len(pipeline.events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Acquire targeted NIFTY option history.")
    parser.parse_args()

    required, bar_count, event_count = build_required_contracts()

    client = FyersClient()
    discovered = _discover_required_symbols(client, required)

    print("=" * 80)
    print("KUNAL QUANT — TARGETED NIFTY OPTION ACQUISITION")
    print("=" * 80)
    print(f"3M bars examined       : {bar_count:,}")
    print(f"KTMI events examined   : {event_count:,}")
    print(f"Required contract keys : {sum(len(v) for v in required.values()):,}")
    print(f"FYERS contracts found  : {len(discovered):,}")
    print(f"Missing from FYERS     : {sum(len(v) for v in required.values()) - len(discovered):,}")
    print()

    downloader = HistoricalDownloader()
    totals = {"inserted": 0, "received": 0, "failed": 0}
    for expiry, requirements in sorted(required.items()):
        for strike, option_type in sorted(requirements):
            key = (expiry, strike, option_type)
            range_from, range_to = requirements[(strike, option_type)]
            symbol = discovered.get(key)
            if symbol is None:
                print(f"[MISS] {expiry} {strike} {option_type}")
                continue

            instrument_id = _register_instrument(
                DATABASE_PATH, symbol, expiry, strike, option_type
            )
            print(f"[OK] {expiry} {strike} {option_type} -> {symbol} (instrument={instrument_id})")

            result = downloader.download_symbol(
                symbol=symbol,
                range_from=range_from,
                range_to=range_to,
                resolution="1",
                mode="expired",
            )
            totals["received"] += int(result["received"])
            totals["inserted"] += int(result["inserted"])
            totals["failed"] += int(result["failed"])

    print()
    print(f"Candles received : {totals['received']:,}")
    print(f"Candles inserted : {totals['inserted']:,}")
    print(f"Failed chunks    : {totals['failed']:,}")
    print("TARGETED ACQUISITION COMPLETE")


if __name__ == "__main__":
    main()
