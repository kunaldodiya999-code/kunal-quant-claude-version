"""Download FYERS history for testing the strategies (read-only, never orders). Needs today's FYERS login.

Owner 26 Oct 2026: "3 months of CLEAN data is better than 1 year of broken data". So, by default:
  * the last 90 days, up to the LAST FINISHED trading day (today only after 15:35);
  * NIFTY, BANK NIFTY, SENSEX, India VIX and every F&O stock, 1-minute candles;
  * 5-minute stock candles are built from those 1-minute candles (one consistent data set);
  * every day is checked (market_data/day_quality.py: strict for indexes, stock rules for stocks) and the result
    saved; a day that is not clean is asked for ONCE more (FYERS sometimes sends a day with holes) and checked again.
Run it again any evening: it only adds the new days and re-tries broken ones, so the data keeps growing.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\data_audit.py            first: what is there, what is clean, what is missing (no login)
    python scripts\\fetch_data.py            then: download what is missing (about 10-20 minutes the first time)
    python scripts\\fetch_data.py --only indexes            (or --only stocks)
    python scripts\\fetch_data.py --symbols RELIANCE,SBIN    (a few stocks only)
    python scripts\\fetch_data.py --days 180                 (more days)

Everything goes to data\\research\\market_data.db (source "fyers"). Next: python scripts\\prove_strategies.py
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import INDEX_RULES, STOCK_RULES, assess_series  # noqa: E402
from market_data.research_store import ResearchStore  # noqa: E402
from market_data.resampling import Candle  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
SOURCE = "fyers"
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX")
DAY_DONE = time(15, 35)
MAX_RETRY_DAYS = 10            # broken days asked for again per series and run


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def last_finished_day(now: datetime) -> date:
    """Today after 15:35 on a weekday, else the weekday before (a holiday simply has no candles)."""
    day = now.date() if now.time() >= DAY_DONE else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def saved_range(store: ResearchStore, series: str, resolution: str) -> tuple[date | None, date | None]:
    with sqlite3.connect(store.path) as db:
        lo, hi = db.execute("SELECT MIN(ts), MAX(ts) FROM candles WHERE series=? AND source=? AND resolution=?",
                            (series, SOURCE, resolution)).fetchone()
    if lo is None:
        return None, None
    return datetime.fromtimestamp(lo, IST).date(), datetime.fromtimestamp(hi, IST).date()


def five_minute(candles: list[Candle]) -> list[Candle]:
    from market_data.resampling import aggregate_regular_session
    return [Candle(b.timestamp, b.open, b.high, b.low, b.close, b.volume)
            for b in aggregate_regular_session(candles, 5)]


def fetch_series(store: ResearchStore, client, series: str, symbol: str, *, days: int, end: date, pause: float,
                 errors: list, stock: bool) -> dict:
    """Download what is missing, re-ask broken days once, check every day. Returns counts for the summary."""
    from market_data.sources.fyers_history import fetch_history
    first, have = saved_range(store, series, "1m")
    start = end - timedelta(days=days)
    if have is not None and first <= start + timedelta(days=7):   # older days already there: only the new ones
        start = max(start, have)
    new = fetch_history(client, symbol, resolution="1", start=start, end=end, pause=pause, on_error=errors.append)
    if new:
        store.save_candles(series, SOURCE, "1m", new)
    rules = STOCK_RULES if stock else INDEX_RULES
    window_start = end - timedelta(days=days)
    candles = [c for c in store.load(series, SOURCE, "1m", clean_only=False)
               if datetime.fromtimestamp(c.timestamp, IST).date() >= window_start]
    reports, _ = assess_series(candles, minutes=1, fix_closing_artifact=False, rules=rules)
    retried = 0
    broken = [r.day for r in reports if not r.clean and not r.corporate_action][-MAX_RETRY_DAYS:]
    for day in broken:                                   # FYERS sometimes sends a day with holes: ask once more
        again = fetch_history(client, symbol, resolution="1", start=day, end=day, pause=pause, on_error=errors.append)
        if again:
            store.save_candles(series, SOURCE, "1m", again)
            retried += 1
    if retried:
        candles = [c for c in store.load(series, SOURCE, "1m", clean_only=False)
                   if datetime.fromtimestamp(c.timestamp, IST).date() >= window_start]
        reports, _ = assess_series(candles, minutes=1, fix_closing_artifact=False, rules=rules)
    store.save_quality(series, SOURCE, "1m", reports)
    if stock and candles:
        store.save_candles(series, SOURCE, "5m", five_minute(candles))
    return {"series": series, "new": len(new), "days": len(reports), "clean": sum(r.clean for r in reports),
            "retried": retried, "last": reports[-1].day if reports else None,
            "broken": [(r.day, r.reason) for r in reports if not r.clean]}


def main(argv=None, *, client=None, master=None, today: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Download FYERS history for the strategy tests (3 months, clean days).")
    p.add_argument("--only", choices=("all", "indexes", "stocks"), default="all")
    p.add_argument("--symbols", default="", help="comma list of stocks (default: every F&O stock)")
    p.add_argument("--days", type=int, default=90, help="days back (default 90 = about 3 months)")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--pause", type=float, default=0.35, help="seconds between FYERS requests (their limit)")
    args = p.parse_args(argv)
    end = today or last_finished_day(datetime.now(IST))
    if client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    store = ResearchStore(args.data_folder / "research" / "market_data.db")
    errors: list[str] = []
    say(f"FYERS 1-minute candles, {args.days} days back, up to {end} (the last finished trading day).")

    if args.only in ("all", "indexes"):
        from market_data.sources.fyers_history import FYERS_SPOT
        for key in INDEXES:
            r = fetch_series(store, client, key, FYERS_SPOT[key], days=args.days, end=end, pause=args.pause,
                             errors=errors, stock=False)
            say(f"{key:<10} {r['clean']} clean of {r['days']} days (last {r['last']}), {r['new']} new candles"
                + (f", {r['retried']} broken days asked again" if r["retried"] else ""))
            for day, why in r["broken"][-5:]:
                print(f"      not clean {day}: {why}")

    if args.only in ("all", "stocks"):
        if args.symbols.strip():
            stocks = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
        else:
            from market_data.stock_universe import load_fno_stocks
            stocks = [s["stock"] for s in load_fno_stocks(args.data_folder, today=end,
                                                          fetch=(lambda url: master) if master else None)]
        say(f"{len(stocks)} F&O stocks. Leave this window open; progress every 10 stocks.")
        results = []
        for n, stock in enumerate(stocks, 1):
            try:
                results.append(fetch_series(store, client, f"STK_{stock}", f"NSE:{stock}-EQ", days=args.days, end=end,
                                            pause=args.pause, errors=errors, stock=True))
            except Exception as exc:                     # one bad stock must not stop the rest
                errors.append(f"{stock}: {exc}")
            if n % 10 == 0 or n == len(stocks):
                say(f"  {n} of {len(stocks)} stocks done ({100 * n // len(stocks)}%)")
        if results:
            days = sum(r["days"] for r in results)
            clean = sum(r["clean"] for r in results)
            thin = sorted((r["clean"], r["series"][4:]) for r in results if r["clean"] < 0.8 * max(1, r["days"]))
            say(f"Stocks: {clean} clean of {days} stock-days ({100 * clean // max(1, days)}%).")
            if thin:
                print("      fewer than 80% clean days (still tested on their clean days): "
                      + ", ".join(f"{s} {c}" for c, s in thin[:15]) + (" ..." if len(thin) > 15 else ""))

    if errors:
        say(f"{len(errors)} requests failed (run the same command again to retry them). First ones:")
        for line in errors[:5]:
            print("   ", line)
    say(f"Done. Data in {store.path}. Check:  python scripts\\data_audit.py   Test:  python scripts\\prove_strategies.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
