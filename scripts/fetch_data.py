"""Download FYERS history into the ONE shared database (read-only towards FYERS, never orders). Needs today's login.

Owner 26 Oct 2026: FYERS data only; one database for both repos (KunalQuant\\data\\database\\kunal_quant.db,
market_data/kq_store.py: rows are only ADDED in KunalQuant's own format, backup before the first write);
"3 months of CLEAN data is better than 1 year of broken data". So, by default:
  * the last 90 days, up to the LAST FINISHED trading day (today only after 15:35);
  * NIFTY, BANK NIFTY, SENSEX, India VIX and every F&O stock, 1-minute candles;
  * every day is checked (market_data/day_quality.py: strict for indexes, stock rules for stocks); a day that is not
    clean is asked for ONCE more (FYERS sometimes sends a day with holes) and checked again;
  * FYERS candles an earlier version saved in data\\research\\market_data.db are moved in first (not downloaded again).
Run it again any evening: it only adds the new days and re-tries broken ones.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\data_audit.py            first: what is there, what is clean, what is missing (no login)
    python scripts\\fetch_data.py            then: download what is missing (about 10-20 minutes the first time)
    python scripts\\fetch_data.py --only indexes            (or --only stocks)
    python scripts\\fetch_data.py --symbols RELIANCE,SBIN    (a few stocks only)
    python scripts\\fetch_data.py --days 180                 (more days)
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
from market_data.kq_store import INDEX_SYMBOLS, KQStore, default_path, symbol_of  # noqa: E402
from market_data.resampling import Candle  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX", "INDIAVIX")
DAY_DONE = time(15, 35)
MAX_RETRY_DAYS = 10            # broken days asked for again per symbol and run


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def last_finished_day(now: datetime) -> date:
    """Today after 15:35 on a weekday, else the weekday before (a holiday simply has no candles)."""
    day = now.date() if now.time() >= DAY_DONE else now.date() - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def move_old_downloads(store: KQStore, research_db: Path) -> int:
    """FYERS 1-minute candles an earlier fetch_data.py saved in data/research/market_data.db -> the shared database."""
    if not research_db.exists():
        return 0
    with sqlite3.connect(f"file:{research_db}?mode=ro", uri=True) as db:
        try:
            names = [r[0] for r in db.execute("SELECT DISTINCT series FROM candles WHERE source='fyers' AND "
                                              "resolution='1m'")]
        except sqlite3.Error:
            return 0
        moved = 0
        for name in names:
            if name.endswith(("_FUT",)) or (not name.startswith("STK_") and name not in INDEX_SYMBOLS):
                continue
            rows = db.execute("SELECT ts, open, high, low, close, volume FROM candles WHERE series=? AND "
                              "source='fyers' AND resolution='1m'", (name,)).fetchall()
            moved += store.add_candles(symbol_of(name), [Candle(int(t), o, h, l, c, v) for t, o, h, l, c, v in rows])
    return moved


def fetch_symbol(store: KQStore, client, name: str, *, days: int, end: date, pause: float, errors: list,
                 stock: bool) -> dict:
    """Download what is missing, re-ask broken days once, check every day. Returns counts for the summary."""
    from market_data.sources.fyers_history import fetch_history
    symbol = symbol_of(name)
    window = end - timedelta(days=days)
    first, have = store.saved_range(name)
    start = window
    if have is not None and first <= window + timedelta(days=7):   # older days already there: only the new ones
        start = max(window, have)
    new = fetch_history(client, symbol, resolution="1", start=start, end=end, pause=pause, on_error=errors.append)
    added = store.add_candles(symbol, new)
    rules = STOCK_RULES if stock else INDEX_RULES
    reports, _ = assess_series(store.load(name, since=window), fix_closing_artifact=not stock, rules=rules)
    retried = 0
    for day in [r.day for r in reports if not r.clean and not r.corporate_action][-MAX_RETRY_DAYS:]:
        again = fetch_history(client, symbol, resolution="1", start=day, end=day, pause=pause, on_error=errors.append)
        if store.add_candles(symbol, again):              # only missing minutes are added
            retried += 1
    if retried:
        reports, _ = assess_series(store.load(name, since=window), fix_closing_artifact=not stock, rules=rules)
    return {"name": name, "added": added, "days": len(reports), "clean": sum(r.clean for r in reports),
            "retried": retried, "last": reports[-1].day if reports else None,
            "broken": [(r.day, r.reason) for r in reports if not r.clean]}


def main(argv=None, *, client=None, master=None, today: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Download FYERS history into the shared database (3 months, clean days).")
    p.add_argument("--only", choices=("all", "indexes", "stocks"), default="all")
    p.add_argument("--symbols", default="", help="comma list of stocks (default: every F&O stock)")
    p.add_argument("--days", type=int, default=90, help="days back (default 90 = about 3 months)")
    p.add_argument("--kq-db", type=Path, default=None, help="the shared database (default: KunalQuant's)")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--pause", type=float, default=0.35, help="seconds between FYERS requests (their limit)")
    args = p.parse_args(argv)
    end = today or last_finished_day(datetime.now(IST))
    store = KQStore(args.kq_db or default_path())
    if not store.exists():
        say(f"Shared database not found: {store.path}. It will be CREATED (KunalQuant's layout). If your 5-year "
            "database is somewhere else, stop (Ctrl+C) and give its path with --kq-db.")
    if client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    errors: list[str] = []
    moved = move_old_downloads(store, args.data_folder / "research" / "market_data.db")
    if moved:
        say(f"Moved {moved:,} FYERS candles from an earlier download into the shared database.")
    say(f"Shared database: {store.path}")
    say(f"FYERS 1-minute candles, {args.days} days back, up to {end} (the last finished trading day).")

    if args.only in ("all", "indexes"):
        for key in INDEXES:
            r = fetch_symbol(store, client, key, days=args.days, end=end, pause=args.pause, errors=errors, stock=False)
            say(f"{key:<10} {r['clean']} clean of {r['days']} days (last {r['last']}), {r['added']:,} candles added"
                + (f", {r['retried']} broken days mended" if r["retried"] else ""))
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
                results.append(fetch_symbol(store, client, f"STK_{stock}", days=args.days, end=end, pause=args.pause,
                                            errors=errors, stock=True))
            except Exception as exc:                     # one bad stock must not stop the rest
                errors.append(f"{stock}: {exc}")
            if n % 10 == 0 or n == len(stocks):
                say(f"  {n} of {len(stocks)} stocks done ({100 * n // len(stocks)}%)")
        if results:
            days = sum(r["days"] for r in results)
            clean = sum(r["clean"] for r in results)
            thin = sorted((r["clean"], r["name"][4:]) for r in results if r["clean"] < 0.8 * max(1, r["days"]))
            say(f"Stocks: {clean} clean of {days} stock-days ({100 * clean // max(1, days)}%).")
            if thin:
                print("      fewer than 80% clean days (still tested on their clean days): "
                      + ", ".join(f"{s} {c}" for c, s in thin[:15]) + (" ..." if len(thin) > 15 else ""))

    if errors:
        say(f"{len(errors)} requests failed (run the same command again to retry them). First ones:")
        for line in errors[:5]:
            print("   ", line)
    say("Done. Check:  python scripts\\data_audit.py   Test:  python scripts\\prove_strategies.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
