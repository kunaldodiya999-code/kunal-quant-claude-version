"""Build a targeted Opening Breakout V2 option acquisition manifest.

Research-only and read-only. Reuses the existing required-option audit logic and
produces a JSON manifest of exact contract-days that are already complete or
still require acquisition. It does not call FYERS and does not modify SQLite.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import DATABASE_PATH
from scripts.audit_opening_breakout_v2_required_options import (
    audit_coverage,
    epoch_seconds,
    load_nifty,
    resolve_required,
    session_groups,
)
from strategies.option_contract_resolver import OptionContractResolver


def build_required(database_path: Path, start_ts: int, end_ts: int) -> list:
    nifty = load_nifty(database_path, start_ts, end_ts)
    if not nifty:
        raise RuntimeError("No NIFTY 1-minute candles found in requested range.")

    resolver = OptionContractResolver(database_path=database_path)
    required = []

    for _, candles in session_groups(nifty).items():
        for instrument, option_type, trigger in (
            ("CALL", "CE", "CANDLE_HIGH"),
            ("PUT", "PE", "CANDLE_LOW"),
        ):
            from backtest.opening_breakout_v2_signal_engine import SignalSeries, scan_series
            from research.opening_breakout_1m_v2 import IndicatorSnapshot, V2Config

            series = SignalSeries(
                symbol="NIFTY-V2-CANDIDATE",
                option_type=option_type,
                strike=0,
                lot_size=1,
                candles=candles,
            )
            config = V2Config(
                trade_instrument=instrument,
                market_bias="NEUTRAL",
                selected_timeframes=("1M",),
                selected_triggers=(trigger,),
                filter_open_high=False,
                filter_open_low=False,
            )

            _, signals = scan_series(
                series,
                config=config,
                indicator_provider=lambda timestamp, candle: IndicatorSnapshot(),
            )

            for event in signals:
                required.append(resolve_required(resolver, event, candles, set(session_groups(nifty))))

    return required


def build_manifest(
    database_path: Path,
    required: list,
    expected_candles_by_date: dict | None = None,
) -> dict:
    if expected_candles_by_date is None:
        results = audit_coverage(database_path, required)
    else:
        results = audit_coverage(
            database_path,
            required,
            expected_candles_by_date=expected_candles_by_date,
        )

    contracts = defaultdict(
        lambda: {
            "expiry_date": None,
            "strike": None,
            "option_type": None,
            "instrument_id": None,
            "symbol": None,
            "required_dates": [],
            "complete_dates": [],
            "missing_dates": [],
            "unregistered_dates": [],
        }
    )

    for row in results:
        key = (
            row["expiry_date"].isoformat(),
            int(row["strike"]),
            row["option_type"],
        )
        item = contracts[key]
        item["expiry_date"] = key[0]
        item["strike"] = key[1]
        item["option_type"] = key[2]
        item["instrument_id"] = row["instrument_id"]
        item["symbol"] = row["symbol"]
        date_value = row["signal_date"].isoformat()
        item["required_dates"].append(date_value)

        if row["status"] == "COMPLETE":
            item["complete_dates"].append(date_value)
        else:
            item["missing_dates"].append(date_value)
            if row["status"] == "UNREGISTERED":
                item["unregistered_dates"].append(date_value)

    for item in contracts.values():
        item["required_dates"] = sorted(set(item["required_dates"]))
        item["complete_dates"] = sorted(set(item["complete_dates"]))
        item["missing_dates"] = sorted(set(item["missing_dates"]))
        item["unregistered_dates"] = sorted(set(item["unregistered_dates"]))
        item["missing_day_count"] = len(item["missing_dates"])

    status_counts = defaultdict(int)
    for row in results:
        status_counts[row["status"]] += 1

    missing_days = sum(item["missing_day_count"] for item in contracts.values())
    return {
        "schema_version": 1,
        "source": "OPENING_BREAKOUT_V2_REQUIRED_OPTION_AUDIT",
        "resolution": "1",
        "read_only_build": True,
        "summary": {
            "signals_requiring_option_data": len(required),
            "unique_contract_days": len(results),
            "complete": status_counts["COMPLETE"],
            "partial": status_counts["PARTIAL"],
            "empty": status_counts["EMPTY"],
            "unregistered": status_counts["UNREGISTERED"],
            "missing_contract_days": missing_days,
            "unique_contracts": len(contracts),
        },
        "contracts": [contracts[key] for key in sorted(contracts)],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", required=True, help="IST datetime")
    parser.add_argument("--to", dest="end", required=True, help="IST datetime")
    parser.add_argument("--database", type=Path, default=DATABASE_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("opening_breakout_v2_option_acquisition_manifest.json"),
    )
    args = parser.parse_args()

    start_ts = epoch_seconds(args.start)
    end_ts = epoch_seconds(args.end)
    nifty = load_nifty(args.database, start_ts, end_ts)
    required = build_required(args.database, start_ts, end_ts)
    expected_candles_by_date = {
        day: len(candles) for day, candles in session_groups(nifty).items()
    }

    manifest = build_manifest(
        args.database,
        required,
        expected_candles_by_date=expected_candles_by_date,
    )
    args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("=" * 110)
    print("KUNAL QUANT — OPENING BREAKOUT V2 OPTION ACQUISITION MANIFEST")
    print("=" * 110)
    print("READ-ONLY: no FYERS calls, no database changes")
    for key, value in manifest["summary"].items():
        print(f"{key:<36}: {value:,}")
    print(f"Manifest written                : {args.output}")
    print("=" * 110)


if __name__ == "__main__":
    main()
