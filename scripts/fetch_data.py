"""Download FYERS history for testing the strategies (read-only, never orders). Needs today's FYERS login.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\fetch_data.py
        Indexes NIFTY, BANK NIFTY, SENSEX + India VIX: 1-minute, last 365 days.
        Every F&O stock: 1-minute (last 60 days) and 5-minute (last 365 days).
        First run: about 20-40 minutes. Run it again any evening after 15:30: it only adds the
        new days (a few minutes), so the data keeps growing with every live market day.

    python scripts\\fetch_data.py --only indexes            (or --only stocks)
    python scripts\\fetch_data.py --symbols RELIANCE,SBIN    (a few stocks only)
    python scripts\\fetch_data.py --index-days 730 --stock-days-5m 730

Everything goes to data\\research\\market_data.db (source "fyers"); the tests read it with
--source fyers (KTMI / TSL Lab / Opening Scalp) or --source cache --cache-source fyers (stocks).
Then:  python scripts\\prove_strategies.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.research_store import ResearchStore  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "fyers"
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX")


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def saved_range(store: ResearchStore, series: str, resolution: str) -> tuple[date | None, date | None]:
    with sqlite3.connect(store.path) as db:
        lo, hi = db.execute("SELECT MIN(ts), MAX(ts) FROM candles WHERE series=? AND source=? AND resolution=?",
                            (series, SOURCE, resolution)).fetchone()
    if lo is None:
        return None, None
    return datetime.fromtimestamp(lo, IST).date(), datetime.fromtimestamp(hi, IST).date()


def fetch_series(store: ResearchStore, client, series: str, symbol: str, resolution: str, *, days: int, today: date,
                 pause: float, errors: list, quality: bool = False) -> int:
    """Download only what is missing: from the last saved day (again, it may have been partial) to today."""
    from market_data.sources.fyers_history import fetch_history
    first, have = saved_range(store, series, resolution)
    start = today - timedelta(days=days)
    if have is not None and first <= start + timedelta(days=7):   # older days already there: only the new ones
        start = max(start, have)
    candles = fetch_history(client, symbol, resolution=resolution.rstrip("m"), start=start, end=today, pause=pause,
                            on_error=errors.append)
    if candles:
        store.save_candles(series, SOURCE, resolution, candles)
        if quality:                                   # index days: clean / not clean, as the data sweep does
            from market_data.day_quality import assess_series
            everything = store.load(series, SOURCE, resolution, clean_only=False)
            reports, _ = assess_series(everything, minutes=int(resolution.rstrip("m")), fix_closing_artifact=True)
            store.save_quality(series, SOURCE, resolution, reports)
    return len(candles)


def main(argv=None, *, client=None, master=None, today: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Download FYERS history for the strategy tests.")
    p.add_argument("--only", choices=("all", "indexes", "stocks"), default="all")
    p.add_argument("--symbols", default="", help="comma list of stocks (default: every F&O stock)")
    p.add_argument("--index-days", type=int, default=365)
    p.add_argument("--stock-days", type=int, default=60, help="1-minute stock candles, days back")
    p.add_argument("--stock-days-5m", type=int, default=365, help="5-minute stock candles, days back")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--pause", type=float, default=0.35, help="seconds between FYERS requests (their limit)")
    args = p.parse_args(argv)
    today = today or datetime.now(IST).date()
    if client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    store = ResearchStore(args.data_folder / "research" / "market_data.db")
    errors: list[str] = []

    if args.only in ("all", "indexes"):
        from market_data.sources.fyers_history import FYERS_SPOT
        for key in INDEXES:
            n = fetch_series(store, client, key, FYERS_SPOT[key], "1m", days=args.index_days, today=today,
                             pause=args.pause, errors=errors, quality=True)
            clean = store.clean_days(key, SOURCE)
            say(f"{key:<10} 1-minute: {n:>7} new candles; {len(clean)} clean days saved"
                + (f" ({clean[0][0]} to {clean[-1][0]})" if clean else ""))

    if args.only in ("all", "stocks"):
        if args.symbols.strip():
            stocks = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
        else:
            from market_data.stock_universe import load_fno_stocks
            stocks = [s["stock"] for s in load_fno_stocks(args.data_folder, today=today,
                                                          fetch=(lambda url: master) if master else None)]
        say(f"{len(stocks)} F&O stocks: 1-minute ({args.stock_days} days) and 5-minute ({args.stock_days_5m} days). "
            "Leave this window open.")
        for n, stock in enumerate(stocks, 1):
            for resolution, days in (("1m", args.stock_days), ("5m", args.stock_days_5m)):
                if days > 0:
                    fetch_series(store, client, f"STK_{stock}", f"NSE:{stock}-EQ", resolution, days=days, today=today,
                                 pause=args.pause, errors=errors)
            if n % 10 == 0 or n == len(stocks):
                say(f"  {n} of {len(stocks)} stocks done ({100 * n // len(stocks)}%)")

    if errors:
        say(f"{len(errors)} requests failed (run the same command again to retry them). First ones:")
        for line in errors[:5]:
            print("   ", line)
    say(f"Done. Data in {store.path}. Next:  python scripts\\prove_strategies.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
