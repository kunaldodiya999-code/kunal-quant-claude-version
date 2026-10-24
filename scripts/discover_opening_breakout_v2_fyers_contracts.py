from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backtest.fyers_historical_contract_discovery import FyersHistoricalContractDiscovery


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Discover exact FYERS historical NIFTY option contracts from the acquisition manifest."
    )
    parser.add_argument("--manifest", default="opening_breakout_v2_option_acquisition_manifest.json")
    parser.add_argument("--limit-expiries", type=int, default=1)
    parser.add_argument("--start-expiry", default=None, help="Only process expiries on/after YYYY-MM-DD")
    parser.add_argument("--refresh-expiry", action="store_true", help="Re-query selected expiry dates even if checkpointed")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--output", default="opening_breakout_v2_fyers_contract_discovery.json")
    parser.add_argument("--max-retries", type=int, default=6)
    parser.add_argument("--backoff-seconds", type=float, default=5.0)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    requested_by_expiry = defaultdict(list)

    for item in manifest["contracts"]:
        if item.get("instrument_id") is not None and not item.get("unregistered_dates"):
            continue
        requested_by_expiry[item["expiry_date"]].append(
            {"strike": float(item["strike"]), "option_type": item["option_type"]}
        )

    expiries = sorted(requested_by_expiry)
    if args.start_expiry:
        start_expiry = date.fromisoformat(args.start_expiry)
        expiries = [expiry for expiry in expiries if date.fromisoformat(expiry) >= start_expiry]
    if args.limit_expiries > 0:
        expiries = expiries[:args.limit_expiries]

    discovery = FyersHistoricalContractDiscovery()
    output_path = Path(args.output)
    existing = {}
    if output_path.exists():
        try:
            prior = json.loads(output_path.read_text(encoding="utf-8"))
            existing = {item["expiry_date"]: item for item in prior.get("results", [])}
        except (OSError, json.JSONDecodeError):
            existing = {}

    # Keep every previously checkpointed expiry. Targeted runs such as
    # --start-expiry must update selected dates without discarding older results.
    results_by_expiry = dict(existing)

    print("=" * 100)
    print("KUNAL QUANT — FYERS HISTORICAL CONTRACT DISCOVERY")
    print("=" * 100)
    print("READ-ONLY: no database registration, no candle downloads")
    print(f"Manifest contracts requiring discovery : {len(manifest['contracts'])}")
    print(f"Expiry dates selected                  : {len(expiries)}")
    if args.start_expiry:
        print(f"Start expiry filter                     : {args.start_expiry}")
    if args.refresh_expiry:
        print("Checkpoint behavior                     : refresh selected expiries")

    for expiry_text in expiries:
        requested = requested_by_expiry[expiry_text]
        requested_keys = {(x["strike"], x["option_type"]) for x in requested}

        if expiry_text in existing and not args.refresh_expiry:
            item = existing[expiry_text]
            print(f"\nSkipping checkpointed expiry {expiry_text} ...")
            print(f"  Found exact tuples       : {len(item.get("found", []))}")
            continue

        print(f"\nChecking expiry {expiry_text} ...")

        for attempt in range(args.max_retries + 1):
            try:
                contracts = discovery.discover_expiry(date.fromisoformat(expiry_text))
                break
            except RuntimeError as exc:
                if "429" not in str(exc) or attempt >= args.max_retries:
                    raise
                delay = args.backoff_seconds * (2 ** attempt)
                print(f"  FYERS rate limit (429); retry {attempt + 1}/{args.max_retries} after {delay:.1f}s")
                time.sleep(delay)

        found_by_key = {}
        if args.debug:
            print("  Requested tuples:")
            for strike, option_type in sorted(requested_keys):
                print(f"    {strike:g} {option_type}")
            print("  First 20 normalized FYERS contracts:")
            for sample in contracts[:20]:
                print("   ", repr(sample))
            typed = [contract for contract in contracts if contract.get("option_type") in {"CE", "PE"}]
            parsed = [contract for contract in typed if contract.get("strike") is not None]
            print(f"  Parsed option contracts      : {len(parsed)}/{len(typed)}")
            if parsed:
                strikes = sorted({float(contract["strike"]) for contract in parsed})
                print(f"  Parsed strike range          : {strikes[0]:g} .. {strikes[-1]:g}")
                near = [
                    contract
                    for contract in parsed
                    if any(abs(float(contract["strike"]) - wanted_strike) <= 500 for wanted_strike, _ in requested_keys)
                ]
                print("  Contracts within +/-500 points of requested strikes:")
                for sample in near[:40]:
                    print("   ", repr(sample))

        for contract in contracts:
            symbol = contract.get("symbol")
            if not symbol:
                continue
            option_type = contract.get("option_type")
            strike = contract.get("strike")
            if option_type in {"CE", "PE"} and strike is not None:
                found_by_key[(float(strike), option_type)] = contract

        found_keys = requested_keys & set(found_by_key)
        missing = [
            {"strike": strike, "option_type": option_type}
            for strike, option_type in sorted(requested_keys - set(found_keys))
        ]

        print(f"  FYERS contracts returned : {len(contracts)}")
        print(f"  Requested exact tuples   : {len(requested_keys)}")
        print(f"  Found exact tuples       : {len(found_keys)}")
        print(f"  Missing exact tuples     : {len(missing)}")

        results_by_expiry[expiry_text] = {
            "expiry_date": expiry_text,
            "requested": requested,
            "found": [
                {
                    "strike": key[0],
                    "option_type": key[1],
                    "symbol": found_by_key[key]["symbol"],
                    "raw": found_by_key[key],
                }
                for key in sorted(found_keys)
            ],
            "missing": missing,
            "returned_contract_count": len(contracts),
        }

        checkpoint = {
            "schema_version": 1,
            "source": "OPENING_BREAKOUT_V2_OPTION_ACQUISITION_MANIFEST",
            "read_only": True,
            "resumable": True,
            "expiry_dates_checked": len(results_by_expiry),
            "requested_tuples": sum(len(item.get("requested", [])) for item in results_by_expiry.values()),
            "found_tuples": sum(len(item.get("found", [])) for item in results_by_expiry.values()),
            "missing_tuples": sum(len(item.get("missing", [])) for item in results_by_expiry.values()),
            "results": sorted(results_by_expiry.values(), key=lambda item: item["expiry_date"]),
        }
        output_path.write_text(
            json.dumps(checkpoint, indent=2, default=str),
            encoding="utf-8",
        )

    report = {
        "schema_version": 1,
        "source": "OPENING_BREAKOUT_V2_OPTION_ACQUISITION_MANIFEST",
        "read_only": True,
        "expiry_dates_checked": len(results_by_expiry),
        "requested_tuples": sum(len(item.get("requested", [])) for item in results_by_expiry.values()),
        "found_tuples": sum(len(item.get("found", [])) for item in results_by_expiry.values()),
        "missing_tuples": sum(len(item.get("missing", [])) for item in results_by_expiry.values()),
        "results": sorted(results_by_expiry.values(), key=lambda item: item["expiry_date"]),
    }

    Path(args.output).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 100)
    print("DISCOVERY SUMMARY")
    print("=" * 100)
    total_requested = sum(len(item.get("requested", [])) for item in results_by_expiry.values())
    total_found = sum(len(item.get("found", [])) for item in results_by_expiry.values())
    total_missing = sum(len(item.get("missing", [])) for item in results_by_expiry.values())
    print(f"Requested tuples : {total_requested}")
    print(f"Found tuples     : {total_found}")
    print(f"Missing tuples   : {total_missing}")
    print(f"Report written   : {args.output}")
    print("=" * 100)


if __name__ == "__main__":
    main()
