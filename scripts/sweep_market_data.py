"""Collect historical data, check every day, keep only CLEAN days.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\sweep_market_data.py --source yahoo
        No login needed. NIFTY, BANK NIFTY, SENSEX, INDIA VIX:
        1-minute (~30 days), 5-minute (~60 days), 1-hour (~2 years).

    python scripts\\sweep_market_data.py --source fyers --days 730
        Needs today's FYERS login. Index + India VIX 1-minute (up to --days),
        futures 1-minute (continuous) and 5-second, current option strikes 1-minute.

    python scripts\\sweep_market_data.py --source both --days 730
        Both, plus a minute-by-minute cross-check: days where Yahoo and FYERS
        agree are marked VERIFIED (the cleanest data you can have).

Everything goes to data\\research\\market_data.db and a report
data\\research\\sweep_report.csv. Read-only: no orders.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import assess_series, group_by_day, longest_clean_stretch  # noqa: E402
from market_data.research_store import ResearchStore  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX")
YAHOO_PLAN = (("1m", 1), ("5m", 5), ("60m", 60))


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def store_series(store: ResearchStore, series: str, source: str, resolution: str, minutes: float,
                 candles, rows: list) -> list:
    reports, _ = assess_series(candles, minutes=minutes, fix_closing_artifact=minutes <= 5)
    store.save_candles(series, source, resolution, candles)
    store.save_quality(series, source, resolution, reports)
    first, last, length = longest_clean_stretch(reports)
    clean = sum(r.clean for r in reports)
    rows.append({"series": series, "source": source, "resolution": resolution, "days": len(reports),
                 "clean_days": clean, "first_day": reports[0].day if reports else "",
                 "last_day": reports[-1].day if reports else "",
                 "longest_clean_run": length, "run_from": first or "", "run_to": last or ""})
    say(f"{series:<10} {source:<6} {resolution:<4} {len(reports):>4} days, {clean:>4} clean"
        + (f", longest clean run {length} days ({first} -> {last})" if length else ""))
    return reports


def sweep_yahoo(store, rows, *, now=None, get=None) -> None:
    from market_data.sources import yahoo
    for key in (*INDEXES, "INDIAVIX"):
        for interval, minutes in YAHOO_PLAN:
            try:
                candles = yahoo.fetch(key, interval, now=now, **({"get": get, "pause": 0} if get else {}))
            except Exception as exc:
                say(f"{key} yahoo {interval}: FAILED ({exc})")
                continue
            store_series(store, key, "yahoo", interval, minutes, candles, rows)


def sweep_fyers(store, rows, *, client, masters, days: int, today: date) -> None:
    from market_data.sources.fyers_history import FYERS_SPOT, fetch_history, nearest_future, option_ladder_symbols
    from strategies.index_profiles import INDEX_PROFILES
    errors = []
    start = today - timedelta(days=days)
    for key, symbol in FYERS_SPOT.items():
        candles = fetch_history(client, symbol, resolution="1", start=start, end=today, on_error=errors.append)
        store_series(store, key, "fyers", "1m", 1, candles, rows)
        if key not in INDEX_PROFILES:
            continue
        profile = INDEX_PROFILES[key]
        master = masters[profile.master]
        future = nearest_future(master, profile.underlying, today)
        if future:
            fut = fetch_history(client, future, resolution="1", start=start, end=today, cont_flag="1",
                                on_error=errors.append)
            store_series(store, f"{key}_FUT", "fyers", "1m", 1, fut, rows)
            secs = fetch_history(client, future, resolution="5S", start=today - timedelta(days=10), end=today,
                                 on_error=errors.append)
            store_series(store, f"{key}_FUT", "fyers", "5s", 5 / 60, secs, rows)
        spot = candles[-1].close if candles else None
        if spot:
            for opt in option_ladder_symbols(master, profile.underlying, spot, profile.strike_step, today):
                oc = fetch_history(client, opt, resolution="1", start=today - timedelta(days=45), end=today,
                                   on_error=errors.append)
                if oc:
                    store_series(store, opt, "fyers", "1m", 1, oc, rows)
    for error in errors:
        say(f"chunk failed: {error}")


def cross_verify(store, rows, *, tolerance_pct: float = 0.05) -> None:
    """Mark days where Yahoo and FYERS 1-minute closes agree (both clean)."""
    for key in (*INDEXES, "INDIAVIX"):
        a = store.load(key, "yahoo", "1m")
        b = store.load(key, "fyers", "1m")
        if not a or not b:
            continue
        days_a, days_b = group_by_day(a), group_by_day(b)
        verified = 0
        for day in sorted(set(days_a) & set(days_b)):
            ca = {c.timestamp: c.close for c in days_a[day]}
            cb = {c.timestamp: c.close for c in days_b[day]}
            common = set(ca) & set(cb)
            if len(common) < 0.95 * min(len(ca), len(cb)):
                continue
            worst = max(abs(ca[t] - cb[t]) / cb[t] * 100 for t in common)
            if worst <= tolerance_pct:
                store.mark_verified(key, "fyers", "1m", day, "yahoo")
                store.mark_verified(key, "yahoo", "1m", day, "fyers")
                verified += 1
        say(f"{key}: {verified} days VERIFIED (Yahoo and FYERS agree within {tolerance_pct}%)")
        for row in rows:
            if row["series"] == key and row["resolution"] == "1m":
                row["verified_days"] = verified


def main(argv=None, *, client=None, masters=None, yahoo_get=None, now=None) -> int:
    p = argparse.ArgumentParser(description="Collect historical data and keep only clean days.")
    p.add_argument("--source", choices=("yahoo", "fyers", "both"), default="yahoo")
    p.add_argument("--days", type=int, default=730, help="FYERS history depth in calendar days (default 2 years)")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    args = p.parse_args(argv)

    now = now or datetime.now(IST)
    store = ResearchStore(args.data_folder / "research" / "market_data.db")
    rows: list = []
    if args.source in ("yahoo", "both"):
        say("Yahoo Finance: indexes and India VIX (no login needed)")
        sweep_yahoo(store, rows, now=now, get=yahoo_get)
    if args.source in ("fyers", "both"):
        if client is None:
            from api.fyers_client import FyersClient
            from scripts.run_paper_session import find_credentials_folder
            client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
        if masters is None:
            from paper_trading.live_support import load_fyers_master
            masters = {name: load_fyers_master(name, args.data_folder / "raw" / "fyers", today=now.date())
                       for name in ("NSE_FO", "BSE_FO")}
        say(f"FYERS: last {args.days} days (this can take a while; failed chunks are listed, never filled)")
        sweep_fyers(store, rows, client=client, masters=masters, days=args.days, today=now.date())
    if args.source == "both":
        cross_verify(store, rows)

    report = args.data_folder / "research" / "sweep_report.csv"
    fields = ["series", "source", "resolution", "days", "clean_days", "verified_days", "first_day", "last_day",
              "longest_clean_run", "run_from", "run_to"]
    with report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({f: row.get(f, "") for f in fields} for row in rows)
    say(f"Report saved: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
