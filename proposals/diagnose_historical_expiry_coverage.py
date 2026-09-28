"""
Kunal Quant — Historical NIFTY Weekly Expiry Coverage Audit

READ-ONLY PROPOSAL

The local option registry is sparse. This diagnostic does NOT use the local
OptionContractResolver to infer historical expiries, because that would hide
missing expiries by jumping to the next registered date.

Instead it:
1. Reads actual NIFTY trading dates from the local 1-minute underlying data.
2. Builds an expected weekly-expiry calendar using the historical NIFTY
   weekday rule:
      - Thursday for expiries through 2025-08-31.
      - Tuesday for expiries from 2025-09-01 onward.
   If the scheduled weekday is not a trading day in the local underlying
   history, the previous trading day in that same week is used.
3. Compares expected weekly expiries with the local NIFTY option registry.
4. Re-runs the full KTMI event pipeline and counts events whose true expected
   nearest weekly expiry is absent from the registry.

This is a data-coverage audit only.

It does NOT:
- call FYERS
- register instruments
- modify the database
- download candles
- modify canonical KunalQuant
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from backtest.ktmi_trigger_pipeline import run_ktmi_trigger_pipeline
from config.settings import DATABASE_PATH
from scripts.run_real_option_sample import build_ktmi_config, load_complete_3m_bars

TZ = ZoneInfo("Asia/Kolkata")
UNDERLYING_SYMBOL = "NSE:NIFTY50-INDEX"
WEEKLY_RULE_CHANGE = date(2025, 9, 1)


def local_date_from_timestamp(timestamp: int) -> date:
    return datetime.fromtimestamp(timestamp, tz=TZ).date()


def load_underlying_trading_dates() -> list[date]:
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT c.timestamp
            FROM candles AS c
            JOIN instruments AS i
              ON i.id = c.instrument_id
            WHERE i.symbol = ?
              AND c.resolution = '1'
            ORDER BY c.timestamp
            """,
            (UNDERLYING_SYMBOL,),
        ).fetchall()

    dates = sorted({local_date_from_timestamp(int(row[0])) for row in rows})
    if not dates:
        raise RuntimeError(
            f"No 1M candles found for {UNDERLYING_SYMBOL}."
        )
    return dates


def load_registered_expiries() -> set[date]:
    with sqlite3.connect(DATABASE_PATH) as db:
        rows = db.execute(
            """
            SELECT DISTINCT expiry_date
            FROM instruments
            WHERE broker = 'FYERS'
              AND underlying = 'NIFTY'
              AND option_type IN ('CE', 'PE')
              AND expiry_date IS NOT NULL
            ORDER BY expiry_date
            """
        ).fetchall()

    return {date.fromisoformat(str(row[0])) for row in rows}


def expected_weekly_expiries(
    trading_dates: list[date],
    start: date,
    end: date,
) -> list[date]:
    """
    Generate the expected NIFTY weekly expiry date for each calendar week
    touched by the requested range.

    Historical rule:
      pre-2025-09-01: Thursday
      from 2025-09-01: Tuesday

    Holiday handling uses the local raw NIFTY trading-date set rather than
    guessing from a holiday list: if the scheduled weekday is absent, select
    the latest trading day on or before that weekday in the same week.
    """
    trading_set = set(trading_dates)
    cursor = start - timedelta(days=start.weekday())
    final_week = end - timedelta(days=end.weekday())

    result: list[date] = []

    while cursor <= final_week:
        week_start = cursor
        scheduled_weekday = (
            3 if week_start < WEEKLY_RULE_CHANGE else 1
        )
        scheduled = week_start + timedelta(days=scheduled_weekday)

        candidates = [
            d
            for d in trading_dates
            if week_start <= d <= scheduled
        ]
        if candidates:
            expiry = max(candidates)
            if start <= expiry <= end:
                result.append(expiry)

        cursor += timedelta(days=7)

    return sorted(set(result))


def nearest_expected_expiry(
    event_date: date,
    expected_expiries: list[date],
) -> date | None:
    for expiry in expected_expiries:
        if expiry >= event_date:
            return expiry
    return None


def audit_event_impact(
    expected_expiries: list[date],
    registered_expiries: set[date],
) -> tuple[int, int, dict[date, int]]:
    bars = load_complete_3m_bars()
    pipeline = run_ktmi_trigger_pipeline(
        bars,
        build_ktmi_config(),
    )

    impacted_events = 0
    mapped_events = 0
    counts_by_expiry: dict[date, int] = defaultdict(int)

    for event in pipeline.events:
        event_date = local_date_from_timestamp(
            int(bars[event.index].timestamp)
        )
        expected = nearest_expected_expiry(
            event_date,
            expected_expiries,
        )
        if expected is None:
            continue

        mapped_events += 1

        if expected not in registered_expiries:
            impacted_events += 1
            counts_by_expiry[expected] += 1

    return (
        len(pipeline.events),
        impacted_events,
        dict(sorted(counts_by_expiry.items())),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only historical NIFTY weekly expiry coverage audit"
    )
    parser.add_argument(
        "--since",
        default="2021-01-01",
        help="Start date YYYY-MM-DD (default: 2021-01-01)",
    )
    parser.add_argument(
        "--until",
        default=None,
        help="End date YYYY-MM-DD (default: latest local NIFTY trading date)",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Optional JSON output path.",
    )
    args = parser.parse_args()

    start = date.fromisoformat(args.since)

    trading_dates = load_underlying_trading_dates()
    local_first = trading_dates[0]
    local_last = trading_dates[-1]
    end = date.fromisoformat(args.until) if args.until else local_last

    if start < local_first:
        start = local_first
    if end > local_last:
        end = local_last
    if start > end:
        raise ValueError("Requested date range is outside local data coverage.")

    registered = load_registered_expiries()
    expected = expected_weekly_expiries(
        trading_dates,
        start,
        end,
    )

    missing = [expiry for expiry in expected if expiry not in registered]
    registered_expected = [expiry for expiry in expected if expiry in registered]

    event_count, impacted_events, impacted_by_expiry = audit_event_impact(
        expected,
        registered,
    )

    print("=" * 100)
    print("KUNAL QUANT — HISTORICAL NIFTY WEEKLY EXPIRY COVERAGE AUDIT")
    print("=" * 100)
    print("READ-ONLY: no API calls, no DB writes, no registrations, no downloads")
    print()
    print(f"Underlying trading-date coverage : {local_first} -> {local_last}")
    print(f"Audit range                      : {start} -> {end}")
    print(f"Registered option expiries       : {len(registered):,}")
    print(f"Expected weekly expiries         : {len(expected):,}")
    print(f"Expected expiries registered     : {len(registered_expected):,}")
    print(f"Expected expiries missing        : {len(missing):,}")
    print()
    print("EXPECTED EXPIRY RULE")
    print("  Through 2025-08-31 : Thursday")
    print("  From 2025-09-01     : Tuesday")
    print("  Holiday             : previous local NIFTY trading day")
    print()

    if missing:
        print("MISSING EXPECTED WEEKLY EXPIRIES")
        for expiry in missing:
            print(expiry.isoformat())
        print()

    print("KTMI EVENT IMPACT")
    print(f"KTMI events examined               : {event_count:,}")
    print(f"Events whose expected expiry is absent from registry : {impacted_events:,}")
    print()

    if impacted_by_expiry:
        print("IMPACTED EVENTS BY MISSING EXPIRY")
        for expiry, count in impacted_by_expiry.items():
            print(f"{expiry.isoformat()} | events={count:,}")
        print()

    report = {
        "database_path": str(DATABASE_PATH),
        "underlying_symbol": UNDERLYING_SYMBOL,
        "underlying_local_first_date": local_first.isoformat(),
        "underlying_local_last_date": local_last.isoformat(),
        "audit_start": start.isoformat(),
        "audit_end": end.isoformat(),
        "weekly_rule": {
            "through": "2025-08-31",
            "weekday": "Thursday",
            "from": "2025-09-01",
            "weekday_after_change": "Tuesday",
            "holiday_rule": "previous_local_trading_day",
        },
        "registered_expiry_count": len(registered),
        "expected_weekly_expiry_count": len(expected),
        "registered_expected_expiry_count": len(registered_expected),
        "missing_expected_expiries": [
            d.isoformat() for d in missing
        ],
        "ktmi_event_count": event_count,
        "events_impacted_by_missing_expected_expiry": impacted_events,
        "impacted_events_by_expiry": {
            d.isoformat(): count
            for d, count in impacted_by_expiry.items()
        },
    }

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, indent=2),
            encoding="utf-8",
        )
        print(f"JSON report written to: {args.json}")

    print("NO DATABASE CHANGES WERE MADE.")


if __name__ == "__main__":
    main()
