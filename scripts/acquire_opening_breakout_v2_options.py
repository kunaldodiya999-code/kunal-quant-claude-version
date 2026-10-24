"""Targeted Opening Breakout V2 option-candle acquisition.

Consumes the already-built Opening Breakout V2 acquisition manifest and the
read-only FYERS historical-contract discovery report. It deliberately does
not resolve contracts, rebuild signals, or modify strategy/lifecycle logic.

Only contract-days listed as missing by the manifest are downloaded.
The existing HistoricalDownloader remains the single candle-download engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from typing import Any

from config.settings import DATABASE_PATH
from backtest.opening_breakout_v2_historical_lot_size import historical_nifty_lot_size
from downloader.historical import HistoricalDownloader
from scripts.acquire_required_nifty_options import _register_instrument

DEFAULT_MANIFEST = Path("opening_breakout_v2_option_acquisition_manifest.json")
DEFAULT_DISCOVERY = Path("opening_breakout_v2_fyers_contract_discovery.json")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _discovered_symbol(
    discovery: dict[str, Any],
    expiry_date: str,
    strike: float,
    option_type: str,
) -> str | None:
    for result in discovery.get("results", []):
        if result.get("expiry_date") != expiry_date:
            continue
        for found in result.get("found", []):
            if (
                float(found.get("strike")) == float(strike)
                and found.get("option_type") == option_type
            ):
                return found.get("symbol")
    return None


def build_acquisition_plan(
    manifest: dict[str, Any],
    discovery: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the exact contract-day download plan without touching SQLite/FYERS."""
    plan: list[dict[str, Any]] = []

    for contract in manifest.get("contracts", []):
        missing_dates = sorted(set(contract.get("missing_dates", [])))
        if not missing_dates:
            continue

        expiry_date = str(contract["expiry_date"])
        strike = float(contract["strike"])
        option_type = str(contract["option_type"])

        symbol = contract.get("symbol")
        if not symbol:
            symbol = _discovered_symbol(
                discovery,
                expiry_date,
                strike,
                option_type,
            )

        if not symbol:
            raise RuntimeError(
                "No discovered FYERS symbol for required contract: "
                f"{expiry_date} {strike:g} {option_type}"
            )

        plan.append(
            {
                "expiry_date": expiry_date,
                "strike": strike,
                "option_type": option_type,
                "symbol": symbol,
                "required_dates": missing_dates,
            }
        )

    return plan


def acquire_plan(
    plan: list[dict[str, Any]],
    *,
    database_path: Path,
    downloader: HistoricalDownloader,
) -> dict[str, int]:
    totals = {
        "contract_days": 0,
        "received": 0,
        "inserted": 0,
        "duplicates": 0,
        "failed": 0,
    }

    for item in plan:
        signal_date = date.fromisoformat(item["required_dates"][0])
        expiry_date = date.fromisoformat(item["expiry_date"])
        lot_size = historical_nifty_lot_size(
            signal_date=signal_date,
            expiry_date=expiry_date,
        )
        instrument_id = _register_instrument(
            database_path,
            item["symbol"],
            item["expiry_date"],
            int(item["strike"]),
            item["option_type"],
            lot_size=lot_size,
        )

        for trading_date in item["required_dates"]:
            print(
                f"[DOWNLOAD] {trading_date} | "
                f"{item['expiry_date']} {item['strike']:g} "
                f"{item['option_type']} | {item['symbol']} "
                f"| instrument={instrument_id}"
            )

            result = downloader.download_symbol(
                symbol=item["symbol"],
                range_from=trading_date,
                range_to=trading_date,
                resolution="1",
                mode="expired",
            )

            totals["contract_days"] += 1
            totals["received"] += int(result.get("received", 0))
            totals["inserted"] += int(result.get("inserted", 0))
            totals["duplicates"] += int(result.get("duplicates", 0))
            totals["failed"] += int(result.get("failed", 0))

            print(
                f"  received={result.get('received', 0)} "
                f"inserted={result.get('inserted', 0)} "
                f"duplicates={result.get('duplicates', 0)} "
                f"failed={result.get('failed', 0)}"
            )

    return totals


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Acquire only missing Opening Breakout V2 option contract-days."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the exact acquisition plan without FYERS calls or database writes.",
    )
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    discovery = load_json(args.discovery)
    plan = build_acquisition_plan(manifest, discovery)

    total_days = sum(len(item["required_dates"]) for item in plan)

    print("=" * 110)
    print("KUNAL QUANT — OPENING BREAKOUT V2 TARGETED OPTION ACQUISITION")
    print("=" * 110)
    print("Source: existing HistoricalDownloader + FYERS expired_history")
    print(f"Manifest contracts with missing dates : {len(plan):,}")
    print(f"Contract-days to acquire              : {total_days:,}")

    for item in plan:
        print(
            f"  {item['expiry_date']} {item['strike']:g} {item['option_type']} "
            f"-> {item['symbol']} | dates={','.join(item['required_dates'])}"
        )

    if args.dry_run:
        print("DRY RUN: no FYERS calls and no database changes.")
        return

    downloader = HistoricalDownloader(database_path=args.database)
    totals = acquire_plan(
        plan,
        database_path=args.database,
        downloader=downloader,
    )

    print()
    print("=" * 110)
    print("ACQUISITION SUMMARY")
    print("=" * 110)
    print(f"Contract-days processed : {totals['contract_days']:,}")
    print(f"Candles received        : {totals['received']:,}")
    print(f"Candles inserted        : {totals['inserted']:,}")
    print(f"Duplicate candles       : {totals['duplicates']:,}")
    print(f"Failed chunks           : {totals['failed']:,}")
    print("=" * 110)

    if totals["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
