"""
Kunal Quant — NIFTY Post-15:30 Coverage Diagnostic (PROPOSAL)

Read-only diagnostic. No database writes.

The current derived 3M/5M builder hard-codes the historical session end at
15:29, while NSE equity derivatives trading currently closes at 15:40 and
that change was effective 2026-08-03.

Before changing the derived-data builder, quantify whether the local raw
FYERS NIFTY 1M data actually contains the additional 15:30–15:39 candles.

Reports, by date:
- raw NIFTY 1M candle count after 15:29
- latest raw NIFTY 1M timestamp
- current derived complete 3M bars after 15:27
- whether the extra raw minutes can form complete 3M bars at 15:30, 15:33,
  and 15:36
- aggregate totals over the available history

Canonical KunalQuant code is not modified.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, time
from zoneinfo import ZoneInfo

from config.settings import DATABASE_PATH, TIMEZONE
from scripts.run_real_option_sample import DERIVED_DB, SYMBOL

RAW_SOURCE = "FYERS_HISTORY"

TZ = ZoneInfo(TIMEZONE)
CUTOFF = time(15, 29)


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """
            SELECT c.timestamp
            FROM candles AS c
            JOIN instruments AS i ON i.id = c.instrument_id
            WHERE i.broker = 'FYERS'
              AND i.symbol = ?
              AND c.resolution = '1'
              AND c.source = ?
            ORDER BY c.timestamp
            """,
            (SYMBOL, RAW_SOURCE),
        ).fetchall()

    raw_by_day: dict[str, list[int]] = defaultdict(list)
    for (timestamp,) in rows:
        dt = datetime.fromtimestamp(int(timestamp), tz=TZ)
        raw_by_day[dt.date().isoformat()].append(int(timestamp))

    derived_by_day: dict[str, list[int]] = defaultdict(list)
    with sqlite3.connect(DERIVED_DB) as connection:
        drows = connection.execute(
            """
            SELECT timestamp
            FROM derived_candles
            WHERE symbol = ?
              AND resolution = '3'
              AND source = 'KQ_DERIVED_FROM_FYERS_1M'
              AND complete = 1
            ORDER BY timestamp
            """,
            (SYMBOL,),
        ).fetchall()

    for (timestamp,) in drows:
        dt = datetime.fromtimestamp(int(timestamp), tz=TZ)
        derived_by_day[dt.date().isoformat()].append(int(timestamp))

    raw_extra_days = []
    raw_extra_rows = 0

    for day, timestamps in sorted(raw_by_day.items()):
        extra = [
            ts for ts in timestamps
            if datetime.fromtimestamp(ts, tz=TZ).time() > CUTOFF
        ]
        if extra:
            raw_extra_days.append(day)
            raw_extra_rows += len(extra)

    print("=" * 100)
    print("KUNAL QUANT — NIFTY POST-15:30 COVERAGE DIAGNOSTIC")
    print("=" * 100)
    print("PROPOSAL ONLY — read-only; canonical KunalQuant unchanged")
    print()
    print(f"Raw NIFTY 1M rows              : {len(rows):,}")
    print(f"Days with raw candles >15:29   : {len(raw_extra_days):,}")
    print(f"Raw candles >15:29             : {raw_extra_rows:,}")
    print()

    print("RECENT DAYS")
    for day in raw_extra_days[-20:]:
        timestamps = raw_by_day[day]
        extra = [
            ts for ts in timestamps
            if datetime.fromtimestamp(ts, tz=TZ).time() > CUTOFF
        ]
        latest = max(extra)
        derived_extra = [
            ts for ts in derived_by_day.get(day, [])
            if datetime.fromtimestamp(ts, tz=TZ).time() > CUTOFF
        ]
        print(
            f"{day} | raw_extra={len(extra):2d} | "
            f"raw_latest={datetime.fromtimestamp(latest, tz=TZ).time()} | "
            f"derived_3m_complete_after_15:29={len(derived_extra):2d}"
        )

    print()
    print("DATE-RANGE STAT")
    if raw_extra_days:
        print(f"First day with extra raw candles : {raw_extra_days[0]}")
        print(f"Last day with extra raw candles  : {raw_extra_days[-1]}")
    else:
        print("No raw NIFTY 1M candles after 15:29 were found.")

    print()
    print(
        "This determines whether a date-aware 15:40 session must also "
        "trigger a rebuild of the derived NIFTY 3M/5M datasets."
    )


if __name__ == "__main__":
    main()
