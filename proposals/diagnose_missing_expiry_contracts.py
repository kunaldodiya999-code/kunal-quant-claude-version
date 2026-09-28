"""
Kunal Quant — Missing Historical Expiry Contract Audit

READ-ONLY PROPOSAL

Purpose:
- Use the independently reconstructed historical weekly-expiry calendar,
  not the local resolver, to identify the exact NIFTY option contracts
  required by KTMI events whose true nearest expiry is missing locally.
- Query FYERS expired-contract discovery only for those missing expiry dates.
- Reconcile the required (expiry, strike, CE/PE) tuples against the FYERS
  symbols returned.

No database writes, registrations, candle downloads, or canonical changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Allow execution from the proposal repository without requiring the caller
# to set PYTHONPATH manually.
HERE = Path(__file__).resolve().parent
CANONICAL_ROOT = HERE.parents[1]
if str(CANONICAL_ROOT) not in sys.path:
    sys.path.insert(0, str(CANONICAL_ROOT))

from api.fyers_client import FyersClient
from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from proposals.diagnose_historical_expiry_coverage import (
    expected_weekly_expiries,
    load_registered_expiries,
    load_underlying_trading_dates,
)
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars
from strategies.option_contract_resolver import OptionContractResolver

TZ = ZoneInfo("Asia/Kolkata")
UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"


def option_type_for_direction(direction: str) -> str:
    return "CE" if str(direction).upper() == "LONG" else "PE"


def option_type_from_symbol(symbol: str) -> str | None:
    value = str(symbol).strip().upper()
    if value.endswith("CE"):
        return "CE"
    if value.endswith("PE"):
        return "PE"
    return None


def strike_from_symbol(symbol: str) -> int | None:
    value = str(symbol).strip().upper()
    if not value.startswith("NSE:NIFTY") or not value.endswith(("CE", "PE")):
        return None

    body = value[len("NSE:NIFTY"):-2]
    match = re.search(r"(\d{4,5})$", body)
    return int(match.group(1)) if match else None


def extract_option_symbols(response: object) -> set[str]:
    if not isinstance(response, dict):
        return set()

    data = response.get("data", {})
    if not isinstance(data, dict):
        return set()

    candidates: list[object] = []
    legacy = data.get("symbols", [])
    if isinstance(legacy, list):
        candidates.extend(legacy)

    contracts = data.get("contracts", {})
    if isinstance(contracts, dict):
        options = contracts.get("options", [])
        if isinstance(options, list):
            candidates.extend(options)

    return {
        str(value).strip()
        for value in candidates
        if isinstance(value, str)
        and value.strip().startswith("NSE:NIFTY")
        and value.strip().endswith(("CE", "PE"))
    }


def build_missing_expiry_requirements(
    since: date,
    until: date | None,
) -> tuple[list[date], dict[tuple[str, int, str], dict[str, object]], int]:
    bars = load_complete_3m_bars()
    trading_dates = load_underlying_trading_dates()
    local_last = trading_dates[-1]
    end = until or local_last

    expected = expected_weekly_expiries(trading_dates, since, end)
    registered = load_registered_expiries()
    missing = [expiry for expiry in expected if expiry not in registered]

    missing_set = set(missing)
    resolver = OptionContractResolver(DATABASE_PATH)
    pipeline = run_ktmi_trigger_pipeline(bars, build_ktmi_config())

    required: dict[tuple[str, int, str], dict[str, object]] = {}

    for event in pipeline.events:
        event_timestamp = int(bars[event.index].timestamp)
        event_date = datetime.fromtimestamp(event_timestamp, tz=TZ).date()

        # Find the true nearest expected weekly expiry, independently of the
        # local instrument registry.
        expiry = next((d for d in expected if d >= event_date), None)
        if expiry is None or expiry not in missing_set:
            continue

        option_type = option_type_for_direction(event.direction.value)
        strike = resolver.calculate_atm_strike(float(bars[event.index].close))
        key = (expiry.isoformat(), strike, option_type)

        item = required.setdefault(
            key,
            {
                "event_count": 0,
                "first_event_date": event_date.isoformat(),
                "last_event_date": event_date.isoformat(),
            },
        )
        item["event_count"] = int(item["event_count"]) + 1
        item["first_event_date"] = min(str(item["first_event_date"]), event_date.isoformat())
        item["last_event_date"] = max(str(item["last_event_date"]), event_date.isoformat())

    return missing, required, len(pipeline.events)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-08-01")
    parser.add_argument("--until", default=None)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    since = date.fromisoformat(args.since)
    until = date.fromisoformat(args.until) if args.until else None

    missing, required, event_count = build_missing_expiry_requirements(
        since, until
    )

    print("=" * 100)
    print("KUNAL QUANT — MISSING HISTORICAL EXPIRY CONTRACT AUDIT")
    print("=" * 100)
    print("READ-ONLY: FYERS discovery only; no DB writes/downloads")
    print()
    print(f"KTMI events examined            : {event_count:,}")
    print(f"Missing expected expiries      : {len(missing):,}")
    print(f"Required contracts on missing  : {len(required):,}")
    print()

    print("REQUIRED CONTRACTS BY MISSING EXPIRY")
    by_expiry: dict[str, list[tuple[str, int, str, dict[str, object]]]] = defaultdict(list)
    for (expiry, strike, option_type), meta in required.items():
        by_expiry[expiry].append((expiry, strike, option_type, meta))

    client = FyersClient()
    fyers_matches: list[dict[str, object]] = []
    fyers_missing: list[dict[str, object]] = []
    api_errors: list[dict[str, object]] = []

    for expiry in missing:
        expiry_text = expiry.isoformat()
        records = sorted(by_expiry.get(expiry_text, []), key=lambda item: (item[1], item[2]))
        print(f"\n{expiry_text} | required tuples={len(records):,}")

        try:
            response = client.expired_contracts(
                symbol=UNDERLYING_SYMBOL,
                expiry_date=expiry_text,
            )
            symbols = extract_option_symbols(response)
            indexed = {
                (strike_from_symbol(symbol), option_type_from_symbol(symbol)): symbol
                for symbol in symbols
            }
            print(f"  FYERS symbols discovered: {len(symbols):,}")
        except Exception as exc:
            print(f"  API ERROR: {exc}")
            for _, strike, option_type, meta in records:
                api_errors.append(
                    {
                        "expiry": expiry_text,
                        "strike": strike,
                        "option_type": option_type,
                        **meta,
                        "error": str(exc),
                    }
                )
            continue

        for _, strike, option_type, meta in records:
            symbol = indexed.get((strike, option_type))
            item = {
                "expiry": expiry_text,
                "strike": strike,
                "option_type": option_type,
                **meta,
            }
            if symbol:
                item["fyers_symbol"] = symbol
                fyers_matches.append(item)
                print(
                    f"  FOUND {strike:>6} {option_type} | "
                    f"events={int(meta['event_count']):>3} | {symbol}"
                )
            else:
                fyers_missing.append(item)
                print(
                    f"  NOT FOUND {strike:>6} {option_type} | "
                    f"events={int(meta['event_count']):>3}"
                )

        if args.delay > 0:
            import time
            time.sleep(args.delay)

    print()
    print("=" * 100)
    print("RESULT SUMMARY")
    print("=" * 100)
    print(f"Missing expected expiries      : {len(missing):,}")
    print(f"Required missing-expiry tuples : {len(required):,}")
    print(f"Found at FYERS                : {len(fyers_matches):,}")
    print(f"Not found at FYERS             : {len(fyers_missing):,}")
    print(f"API-error tuples               : {len(api_errors):,}")
    print()

    report = {
        "database_path": str(DATABASE_PATH),
        "since": since.isoformat(),
        "until": until.isoformat() if until else None,
        "ktmi_event_count": event_count,
        "missing_expected_expiries": [d.isoformat() for d in missing],
        "required_contracts": len(required),
        "fyers_found": fyers_matches,
        "fyers_not_found": fyers_missing,
        "fyers_api_errors": api_errors,
    }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"JSON report written to: {args.json}")

    print("NO DATABASE CHANGES WERE MADE.")


if __name__ == "__main__":
    main()
