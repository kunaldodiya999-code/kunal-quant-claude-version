"""Build a minimal, read-only NIFTY near-ATM option acquisition manifest.

Research scope:
- NIFTY spot 1-minute timestamps from 2023-01-01 onward.
- For each synchronized spot timestamp, select the nearest expiry on/after
  the timestamp's IST trading date.
- Select ATM plus/minus five *actual strikes* from that expiry's instrument
  ladder, not a hard-coded strike interval.
- Include both CE and PE.
- Collapse timestamp selections into unique instrument requirements with the
  first/last date on which each contract is required.
- Audit whether those contracts already have historical 1-minute candles.

This does not modify the database, resolver, strategy, or download state.
It is a planning/audit tool only.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = timezone(timedelta(hours=5, minutes=30))
SPOT_SYMBOL = "NSE:NIFTY50-INDEX"
SPOT_SOURCE = "FYERS_HISTORY"
OPTION_SOURCE = "FYERS_FNO_HISTORY"
TIMEFRAME = "1"
START_DATE = "2023-01-01"


def ist_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, IST).date().isoformat()


def load_spot(db: sqlite3.Connection, start_date: str) -> list[tuple[int, float, str]]:
    row = db.execute(
        "SELECT id FROM instruments WHERE broker='FYERS' AND symbol=? ORDER BY id LIMIT 1",
        (SPOT_SYMBOL,),
    ).fetchone()
    if row is None:
        return []

    start_ts = int(datetime.fromisoformat(start_date).replace(tzinfo=IST).timestamp())
    rows = db.execute(
        """
        SELECT timestamp, close
        FROM candles
        WHERE instrument_id=? AND resolution=? AND source=?
          AND timestamp>=? AND close IS NOT NULL AND close>0
        ORDER BY timestamp
        """,
        (row[0], TIMEFRAME, SPOT_SOURCE, start_ts),
    )
    return [(int(ts), float(close), ist_date(int(ts))) for ts, close in rows]


def load_expiry_ladders(
    db: sqlite3.Connection,
) -> tuple[dict[str, list[float]], dict[tuple[str, float, str], tuple[int, str]]]:
    ladders: dict[str, set[float]] = defaultdict(set)
    contracts: dict[tuple[str, float, str], tuple[int, str]] = {}
    rows = db.execute(
        """
        SELECT id, expiry_date, strike, option_type, symbol
        FROM instruments
        WHERE broker='FYERS'
          AND underlying='NIFTY'
          AND expiry_date IS NOT NULL
          AND strike IS NOT NULL
          AND option_type IN ('CE','PE')
        ORDER BY expiry_date, strike, option_type, id
        """
    )
    for instrument_id, expiry, strike, option_type, symbol in rows:
        expiry = str(expiry)
        strike = float(strike)
        ladders[expiry].add(strike)
        contracts.setdefault((expiry, strike, str(option_type)), (int(instrument_id), str(symbol)))
    return {e: sorted(v) for e, v in ladders.items()}, contracts


def select_strikes(strikes: list[float], spot: float, radius: int = 5) -> list[float]:
    if len(strikes) == 0:
        return []
    pos = bisect_left(strikes, spot)
    if pos == 0:
        atm_idx = 0
    elif pos == len(strikes):
        atm_idx = len(strikes) - 1
    else:
        left = strikes[pos - 1]
        right = strikes[pos]
        atm_idx = pos - 1 if abs(spot - left) <= abs(right - spot) else pos
    lo = max(0, atm_idx - radius)
    hi = min(len(strikes), atm_idx + radius + 1)
    return strikes[lo:hi]


def nearest_expiry(expiries: list[str], trade_date: str, max_days: int = 90) -> str | None:
    idx = bisect_left(expiries, trade_date)
    if idx >= len(expiries):
        return None
    expiry = expiries[idx]
    trade = datetime.fromisoformat(trade_date).date()
    expiry_day = datetime.fromisoformat(expiry).date()
    if (expiry_day - trade).days > max_days:
        return None
    return expiry


def audit_existing(db: sqlite3.Connection, required: dict[int, dict]) -> None:
    instrument_ids = list(required)
    if not instrument_ids:
        return
    placeholders = ",".join("?" for _ in instrument_ids)
    sql = f"""
        SELECT instrument_id,
               date(timestamp, 'unixepoch', '+5 hours', '+30 minutes') AS trade_date,
               COUNT(*) AS candle_count,
               MIN(timestamp) AS first_timestamp,
               MAX(timestamp) AS last_timestamp
        FROM candles
        WHERE resolution=? AND source=? AND instrument_id IN ({placeholders})
        GROUP BY instrument_id, trade_date
    """
    existing_days: dict[int, set[str]] = defaultdict(set)
    existing_counts: dict[int, int] = defaultdict(int)
    existing_first: dict[int, int] = {}
    existing_last: dict[int, int] = {}
    for instrument_id, trade_date, candle_count, first_ts, last_ts in db.execute(
        sql, [TIMEFRAME, OPTION_SOURCE, *instrument_ids]
    ):
        instrument_id = int(instrument_id)
        existing_days[instrument_id].add(str(trade_date))
        existing_counts[instrument_id] += int(candle_count)
        existing_first[instrument_id] = min(
            int(first_ts), existing_first.get(instrument_id, int(first_ts))
        )
        existing_last[instrument_id] = max(
            int(last_ts), existing_last.get(instrument_id, int(last_ts))
        )

    for instrument_id, item in required.items():
        required_days = item["required_days"]
        covered_days = existing_days[instrument_id] & required_days
        item["required_trading_days"] = len(required_days)
        item["existing_days_with_candles"] = len(covered_days)
        item["missing_required_days"] = len(required_days - existing_days[instrument_id])
        item["existing_candles_total"] = existing_counts[instrument_id]
        item["existing_first_timestamp"] = existing_first.get(instrument_id)
        item["existing_last_timestamp"] = existing_last.get(instrument_id)
        item["existing_coverage_pct"] = round(
            100 * len(covered_days) / max(1, len(required_days)), 2
        )
        if len(covered_days) == len(required_days):
            item["existing_status"] = "COVERED"
        elif covered_days:
            item["existing_status"] = "PARTIAL"
        else:
            item["existing_status"] = "EMPTY"


def build_manifest(
    database_path: Path,
    output_prefix: Path,
    start_date: str = START_DATE,
    radius: int = 5,
) -> tuple[list[dict], dict]:
    if radius < 0:
        raise ValueError("radius must be >= 0")

    with sqlite3.connect(database_path) as db:
        db.execute("PRAGMA query_only = ON")
        spot_rows = load_spot(db, start_date)
        ladders, contracts = load_expiry_ladders(db)

        expiries = sorted(ladders)
        required: dict[tuple[int, str], dict] = {}
        selected_timestamps = 0
        timestamps_without_expiry = 0
        timestamps_without_strikes = 0
        max_selected_strikes = 0

        for timestamp, spot, trade_date in spot_rows:
            expiry = nearest_expiry(expiries, trade_date, max_days=90)
            if expiry is None:
                timestamps_without_expiry += 1
                continue

            strikes = select_strikes(ladders[expiry], spot, radius)
            if not strikes:
                timestamps_without_strikes += 1
                continue

            selected_timestamps += 1
            max_selected_strikes = max(max_selected_strikes, len(strikes))
            for strike in strikes:
                for option_type in ("CE", "PE"):
                    contract = contracts.get((expiry, strike, option_type))
                    if contract is None:
                        continue
                    instrument_id, symbol = contract
                    key = (instrument_id, trade_date)
                    if key not in required:
                        required[key] = {
                            "instrument_id": instrument_id,
                            "symbol": symbol,
                            "expiry_date": expiry,
                            "strike": strike,
                            "option_type": option_type,
                            "first_required_date": trade_date,
                            "last_required_date": trade_date,
                            "required_spot_timestamps": 0,
                            "required_days": set(),
                        }
                    item = required[key]
                    item["first_required_date"] = min(item["first_required_date"], trade_date)
                    item["last_required_date"] = max(item["last_required_date"], trade_date)
                    item["required_spot_timestamps"] += 1
                    item["required_days"].add(trade_date)

        # Collapse the temporary (instrument, day) rows to one row per
        # instrument while preserving the exact date range in which it is used.
        collapsed: dict[int, dict] = {}
        for (instrument_id, _trade_date), item in required.items():
            out = collapsed.setdefault(
                instrument_id,
                {
                    "instrument_id": instrument_id,
                    "symbol": item["symbol"],
                    "expiry_date": item["expiry_date"],
                    "strike": item["strike"],
                    "option_type": item["option_type"],
                    "first_required_date": item["first_required_date"],
                    "last_required_date": item["last_required_date"],
                    "required_spot_timestamps": 0,
                    "required_days": set(),
                },
            )
            out["first_required_date"] = min(out["first_required_date"], item["first_required_date"])
            out["last_required_date"] = max(out["last_required_date"], item["last_required_date"])
            out["required_spot_timestamps"] += item["required_spot_timestamps"]
            out["required_days"].update(item["required_days"])

        audit_existing(db, collapsed)

    rows = []
    for item in sorted(collapsed.values(), key=lambda x: (x["expiry_date"], x["strike"], x["option_type"])):
        item["required_trading_days"] = len(item.pop("required_days"))
        status = item.pop("existing_status", "EMPTY")
        item["existing_status"] = status
        item["action"] = "REUSE_EXISTING" if status == "COVERED" else "ACQUIRE"
        rows.append(item)

    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output_prefix.with_name(output_prefix.name + "_manifest.csv")
    summary_path = output_prefix.with_name(output_prefix.name + "_summary.csv")

    fields = [
        "instrument_id", "symbol", "expiry_date", "strike", "option_type",
        "first_required_date", "last_required_date", "required_trading_days",
        "required_spot_timestamps", "required_trading_days",
        "existing_days_with_candles", "missing_required_days",
        "existing_coverage_pct", "existing_candles_total",
        "existing_status", "action",
    ]
    with manifest_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    reuse = sum(r["action"] == "REUSE_EXISTING" for r in rows)
    partial = sum(r["existing_status"] == "PARTIAL" for r in rows)
    acquire = sum(r["action"] == "ACQUIRE" for r in rows)
    summary = [
        ("start_date", start_date),
        ("spot_timestamps", len(spot_rows)),
        ("selected_spot_timestamps", selected_timestamps),
        ("timestamps_without_future_expiry", timestamps_without_expiry),
        ("timestamps_without_strike_ladder", timestamps_without_strikes),
        ("unique_required_contracts", len(rows)),
        ("fully_covered_contracts", reuse),
        ("partially_covered_contracts", partial),
        ("contracts_to_acquire", acquire),
        ("max_strikes_selected_per_timestamp", max_selected_strikes),
        ("strike_radius", radius),
    ]
    with summary_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(("metric", "value"))
        writer.writerows(summary)

    print("=" * 100)
    print("KUNAL QUANT — MINIMAL NEAR-ATM OPTION ACQUISITION MANIFEST")
    print("=" * 100)
    print("READ-ONLY: no downloads, no database changes, resolver/strategy untouched")
    print(f"Start date                         : {start_date}")
    print(f"NIFTY spot timestamps              : {len(spot_rows):,}")
    print(f"Selected timestamps with expiry    : {selected_timestamps:,}")
    print(f"Without future expiry              : {timestamps_without_expiry:,}")
    print(f"Without strike ladder              : {timestamps_without_strikes:,}")
    print(f"Unique required contracts          : {len(rows):,}")
    print(f"Fully covered existing contracts   : {reuse:,}")
    print(f"Partially covered contracts        : {partial:,}")
    print(f"Need acquisition                   : {acquire:,}")
    print(f"Strike radius                      : +/- {radius} actual strikes")
    print()
    print("NOTE: ATM is resolved against the actual instrument strike ladder for each expiry.")
    print("      No hard-coded 50-point/100-point strike spacing is assumed.")
    print(f"Manifest CSV : {manifest_path}")
    print(f"Summary CSV  : {summary_path}")
    return rows, dict(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build read-only minimal NIFTY near-ATM option acquisition manifest.")
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output-prefix", type=Path, default=None)
    parser.add_argument("--start-date", default=START_DATE)
    parser.add_argument("--radius", type=int, default=5)
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database
    output_prefix = args.output_prefix or (
        PROJECT_ROOT / "data" / "research" / "nifty_near_atm_option_requirements"
    )
    build_manifest(database_path, output_prefix, args.start_date, args.radius)


if __name__ == "__main__":
    main()
