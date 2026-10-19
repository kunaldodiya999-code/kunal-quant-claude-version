"""Experimental, read-only NIFTY option-chain completeness audit.

This is a data-quality diagnostic only. It does not calculate Greeks/GEX and
does not modify production strategy, resolver, or database records.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

TZ_OFFSET = __import__("datetime").timezone(__import__("datetime").timedelta(hours=5, minutes=30))
OPTION_SOURCE = "FYERS_FNO_HISTORY"
SPOT_SYMBOL = "NSE:NIFTY50-INDEX"
SPOT_SOURCE = "FYERS_HISTORY"
TIMEFRAME = "1"


def summarize_snapshot(
    contracts: dict[float, dict[str, tuple[float | None, int | None]]],
    spot: float | None,
    max_distance: float,
    min_paired_oi_strikes: int,
) -> dict[str, int | float | str | None]:
    """Summarize one expiry/timestamp snapshot.

    A valid option price requires close > 0. OI is considered present when it
    is non-NULL and >= 0. A candidate snapshot is only a coverage screen:
    spot must exist and the configured number of matched CE/PE strikes must
    have both valid prices and non-NULL OI within the configured spot band.
    It is not a claim that Greeks or GEX are economically valid.
    """
    ce = set()
    pe = set()
    paired = set()
    paired_oi = set()

    # Without a synchronized underlying price, "around spot" cannot be
    # evaluated; do not mislabel the entire chain as being inside the band.
    if spot is None:
        return {
            "spot": None,
            "ce_strikes_in_band": 0,
            "pe_strikes_in_band": 0,
            "paired_strikes_in_band": 0,
            "paired_oi_strikes_in_band": 0,
            "candidate_snapshot": "NO",
        }

    for strike, sides in contracts.items():
        if abs(float(strike) - spot) > max_distance:
            continue

        call = sides.get("CE")
        put = sides.get("PE")
        call_price = call[0] if call else None
        put_price = put[0] if put else None
        call_oi = call[1] if call else None
        put_oi = put[1] if put else None

        call_valid = call_price is not None and call_price > 0
        put_valid = put_price is not None and put_price > 0

        if call_valid:
            ce.add(strike)
        if put_valid:
            pe.add(strike)
        if call_valid and put_valid:
            paired.add(strike)
            if call_oi is not None and call_oi >= 0 and put_oi is not None and put_oi >= 0:
                paired_oi.add(strike)

    candidate = spot is not None and len(paired_oi) >= min_paired_oi_strikes
    return {
        "spot": spot,
        "ce_strikes_in_band": len(ce),
        "pe_strikes_in_band": len(pe),
        "paired_strikes_in_band": len(paired),
        "paired_oi_strikes_in_band": len(paired_oi),
        "candidate_snapshot": "YES" if candidate else "NO",
    }


def load_spot_prices(db: sqlite3.Connection) -> dict[int, float]:
    row = db.execute(
        """
        SELECT id FROM instruments
        WHERE broker='FYERS' AND symbol=?
        ORDER BY id LIMIT 1
        """,
        (SPOT_SYMBOL,),
    ).fetchone()
    if row is None:
        return {}

    rows = db.execute(
        """
        SELECT timestamp, close
        FROM candles
        WHERE instrument_id=? AND resolution=? AND source=?
          AND close IS NOT NULL AND close > 0
        ORDER BY timestamp
        """,
        (row[0], TIMEFRAME, SPOT_SOURCE),
    )
    return {int(ts): float(close) for ts, close in rows}


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def run_audit(
    database_path: Path,
    output_prefix: Path,
    max_distance: float = 1000.0,
    min_paired_oi_strikes: int = 5,
    expiry_filter: str | None = None,
) -> tuple[list[dict], list[dict]]:
    if max_distance <= 0:
        raise ValueError("max_distance must be positive")
    if min_paired_oi_strikes < 1:
        raise ValueError("min_paired_oi_strikes must be at least 1")

    with sqlite3.connect(database_path) as db:
        db.execute("PRAGMA query_only = ON")
        spot_prices = load_spot_prices(db)

        sql = """
            SELECT i.expiry_date, c.timestamp, i.strike, i.option_type,
                   c.close, c.open_interest
            FROM candles c
            JOIN instruments i ON i.id = c.instrument_id
            WHERE i.broker='FYERS'
              AND i.underlying='NIFTY'
              AND i.option_type IN ('CE','PE')
              AND i.expiry_date IS NOT NULL
              AND c.resolution=?
              AND c.source=?
        """
        params: list[object] = [TIMEFRAME, OPTION_SOURCE]
        if expiry_filter:
            sql += " AND i.expiry_date = ?"
            params.append(expiry_filter)
        sql += " ORDER BY i.expiry_date, c.timestamp, i.strike"

        snapshots: dict[tuple[str, int], dict] = {}
        for expiry, timestamp, strike, option_type, close, oi in db.execute(sql, params):
            key = (str(expiry), int(timestamp))
            sides_by_strike = snapshots.setdefault(key, {})
            sides = sides_by_strike.setdefault(float(strike), {})
            # Defensive: duplicate contract rows should not inflate strike counts.
            sides[str(option_type)] = (
                float(close) if close is not None else None,
                int(oi) if oi is not None else None,
            )

    timestamp_rows: list[dict] = []
    by_expiry: dict[str, list[dict]] = defaultdict(list)

    for (expiry, timestamp), contracts in sorted(snapshots.items()):
        spot = spot_prices.get(timestamp)
        metrics = summarize_snapshot(
            contracts=contracts,
            spot=spot,
            max_distance=max_distance,
            min_paired_oi_strikes=min_paired_oi_strikes,
        )
        local_time = datetime.fromtimestamp(timestamp, TZ_OFFSET)
        row = {
            "expiry_date": expiry,
            "timestamp": timestamp,
            "datetime_ist": local_time.strftime("%Y-%m-%d %H:%M:%S"),
            **metrics,
        }
        timestamp_rows.append(row)
        by_expiry[expiry].append(row)

    expiry_rows: list[dict] = []
    for expiry, rows in sorted(by_expiry.items()):
        candidate_rows = [r for r in rows if r["candidate_snapshot"] == "YES"]
        expiry_rows.append({
            "expiry_date": expiry,
            "timestamps_with_option_data": len(rows),
            "timestamps_with_spot": sum(r["spot"] is not None for r in rows),
            "candidate_snapshots": len(candidate_rows),
            "candidate_snapshot_pct_of_spot_timestamps": round(
                100 * len(candidate_rows) / max(1, sum(r["spot"] is not None for r in rows)), 2
            ),
            "max_ce_strikes_in_band": max(int(r["ce_strikes_in_band"]) for r in rows),
            "max_pe_strikes_in_band": max(int(r["pe_strikes_in_band"]) for r in rows),
            "max_paired_oi_strikes_in_band": max(int(r["paired_oi_strikes_in_band"]) for r in rows),
            "first_timestamp_ist": rows[0]["datetime_ist"],
            "last_timestamp_ist": rows[-1]["datetime_ist"],
        })

    timestamp_fields = [
        "expiry_date", "timestamp", "datetime_ist", "spot",
        "ce_strikes_in_band", "pe_strikes_in_band",
        "paired_strikes_in_band", "paired_oi_strikes_in_band",
        "candidate_snapshot",
    ]
    expiry_fields = [
        "expiry_date", "timestamps_with_option_data", "timestamps_with_spot",
        "candidate_snapshots", "candidate_snapshot_pct_of_spot_timestamps",
        "max_ce_strikes_in_band", "max_pe_strikes_in_band",
        "max_paired_oi_strikes_in_band", "first_timestamp_ist", "last_timestamp_ist",
    ]
    timestamp_path = output_prefix.with_name(output_prefix.name + "_timestamps.csv")
    expiry_path = output_prefix.with_name(output_prefix.name + "_by_expiry.csv")
    write_csv(timestamp_path, timestamp_rows, timestamp_fields)
    write_csv(expiry_path, expiry_rows, expiry_fields)

    print("=" * 100)
    print("KUNAL QUANT — EXPERIMENTAL OPTION CHAIN COMPLETENESS AUDIT")
    print("=" * 100)
    print("READ-ONLY: no database changes, no downloads, no Greeks/GEX calculations")
    print(f"Database                    : {database_path}")
    print(f"Spot timestamps loaded      : {len(spot_prices):,}")
    print(f"Expiry/timestamp snapshots  : {len(timestamp_rows):,}")
    print(f"Expiries with candle data   : {len(expiry_rows):,}")
    print(f"Spot band                   : +/- {max_distance:.0f} NIFTY points")
    print(f"Minimum matched CE/PE strikes with OI: {min_paired_oi_strikes}")
    print(f"Candidate snapshots         : {sum(r['candidate_snapshot'] == 'YES' for r in timestamp_rows):,}")
    print()
    print("BY EXPIRY (candidate = coverage screen only, not validated GEX)")
    print(f"{'EXPIRY':12s} {'SNAPSHOTS':>10s} {'SPOT':>9s} {'CANDIDATE':>11s} {'MAX CE':>8s} {'MAX PE':>8s} {'MAX PAIRED+OI':>14s}")
    for row in expiry_rows:
        print(
            f"{row['expiry_date']:12s} {row['timestamps_with_option_data']:10,d} "
            f"{row['timestamps_with_spot']:9,d} {row['candidate_snapshots']:11,d} "
            f"{row['max_ce_strikes_in_band']:8,d} {row['max_pe_strikes_in_band']:8,d} "
            f"{row['max_paired_oi_strikes_in_band']:14,d}"
        )
    print()
    print(f"Timestamp detail CSV : {timestamp_path}")
    print(f"Expiry summary CSV   : {expiry_path}")
    return timestamp_rows, expiry_rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only experimental NIFTY option-chain completeness audit."
    )
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--output-prefix", type=Path, default=None)
    parser.add_argument("--expiry", type=str, default=None, help="Optional expiry YYYY-MM-DD.")
    parser.add_argument("--max-distance", type=float, default=1000.0,
                        help="Maximum strike distance from NIFTY spot (default: 1000 points).")
    parser.add_argument("--min-paired-oi-strikes", type=int, default=5,
                        help="Minimum matched CE/PE strikes with valid prices and OI.")
    args = parser.parse_args()

    if args.database is None:
        from config.settings import DATABASE_PATH
        database_path = Path(DATABASE_PATH)
    else:
        database_path = args.database
    output_prefix = args.output_prefix or (
        PROJECT_ROOT / "data" / "research" / "option_chain_completeness"
    )
    run_audit(
        database_path=database_path,
        output_prefix=output_prefix,
        max_distance=args.max_distance,
        min_paired_oi_strikes=args.min_paired_oi_strikes,
        expiry_filter=args.expiry,
    )


if __name__ == "__main__":
    main()
