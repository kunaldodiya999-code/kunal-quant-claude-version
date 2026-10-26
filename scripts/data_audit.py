"""What FYERS price data is on this PC, which days are CLEAN, and what is missing up to today. Read-only, no login.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\data_audit.py
    python scripts\\data_audit.py --days 90        (the window the tests need; default 90 = about 3 months)

Looks at:
  1. the ONE shared database (both repos): C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db
     (market_data/kq_store.py): NIFTY, BANK NIFTY, SENSEX, India VIX and every stock with candles;
  2. the live recordings of the trading program: data\\paper_trading\\<INDEX>\\minute_candles.csv (+ futures).
Yahoo data (data\\research\\market_data.db) is NOT used any more (owner 26 Oct 2026: broker data only).
Every 1-minute day is checked with market_data/day_quality.py (indexes strict; stocks: STOCK rules).
Saved: data\\research\\data_audit.txt (this text) and data\\research\\data_audit_days.csv (every day + reason).
At the end: what the strategy tests need and the command that fills the gap.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import INDEX_RULES, STOCK_RULES, assess_series  # noqa: E402
from market_data.kq_store import KQStore, default_path  # noqa: E402
from market_data.resampling import Candle  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX")
ENOUGH = 0.8                     # 80% of the trading days in the window clean = enough to test


class Audit:
    def __init__(self, days: int, end: date):
        self.window = days
        self.end = end
        self.start = end - timedelta(days=days)
        self.rows: list[dict] = []                 # every day of every series
        self.found: list[dict] = []                # one line per series
        self.lines: list[str] = []

    def say(self, text: str = "") -> None:
        print(text, flush=True)
        self.lines.append(text)

    def check(self, place: str, series: str, candles: list[Candle], *, stock: bool) -> dict:
        reports, _ = assess_series(candles, minutes=1, fix_closing_artifact=not stock,
                                   rules=STOCK_RULES if stock else INDEX_RULES)
        recent = [r for r in reports if self.start < r.day <= self.end]
        for r in recent:
            self.rows.append({"place": place, "series": series, "day": r.day.isoformat(), "clean": int(r.clean),
                              "candles": r.actual, "reason": r.reason})
        info = {"place": place, "series": series, "stock": stock, "recent_days": {r.day for r in recent},
                "recent_clean": {r.day for r in recent if r.clean}, "last": recent[-1].day if recent else None,
                "first": recent[0].day if recent else None, "broken": [(r.day, r.reason) for r in recent if not r.clean]}
        self.found.append(info)
        return info


def audit_shared(a: Audit, store: KQStore) -> None:
    a.say(f"1. Shared FYERS database (both repos): {store.path}")
    if not store.exists():
        a.say("   NOT FOUND. Check the path (or give it with --kq-db). scripts\\fetch_data.py creates it if needed.")
        return
    full = store.saved_range("NIFTY")
    if full[0]:
        a.say(f"   NIFTY history in total: {full[0]} to {full[1]}")
    since = a.start - timedelta(days=5)
    for key in (*INDEXES, "INDIAVIX"):
        info = a.check("shared", key, store.load(key, since=since), stock=False)
        a.say(f"   {key:<10} last {a.window} days: {len(info['recent_clean'])} clean of {len(info['recent_days'])} "
              f"days with data" + (f", newest {info['last']}" if info["last"] else " (none)"))
        for day, why in info["broken"][-3:]:
            a.say(f"      not clean {day}: {why}")
    stocks = store.stocks()
    if not stocks:
        a.say("   stocks: none yet")
        return
    infos = [a.check("shared", f"STK_{s}", store.load(f"STK_{s}", since=since), stock=True) for s in stocks]
    days = sum(len(i["recent_days"]) for i in infos)
    clean = sum(len(i["recent_clean"]) for i in infos)
    newest = max((i["last"] for i in infos if i["last"]), default=None)
    a.say(f"   stocks: {len(stocks)} with candles; last {a.window} days: {clean} clean of {days} stock-days with data "
          f"({100 * clean // max(1, days)}%), newest {newest}")
    reasons: dict[str, int] = defaultdict(int)
    for i in infos:
        for _d, why in i["broken"]:
            reasons[why.split(" (")[0].split(";")[0]] += 1
    if reasons:
        a.say("      most common problems: " + ", ".join(
            f"{k} x{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4]))


def audit_live(a: Audit, folder: Path) -> None:
    a.say(f"2. Live recordings of the trading program: {folder}")
    any_found = False
    for key in INDEXES:
        for name, label in (("minute_candles.csv", key), ("futures_minute_candles.csv", key + "_FUT")):
            path = folder / key / name
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as handle:
                rows = [r for r in csv.DictReader(handle) if r.get("timestamp")]
            candles = sorted({int(r["timestamp"]): Candle(int(r["timestamp"]), float(r["open"]), float(r["high"]),
                                                          float(r["low"]), float(r["close"]),
                                                          int(float(r.get("volume") or 0))) for r in rows}.values(),
                             key=lambda c: c.timestamp)
            if candles:
                any_found = True
                info = a.check("live", label, candles, stock=False)
                a.say(f"   {label:<14} {len(info['recent_clean'])} clean of {len(info['recent_days'])} days "
                      "(clean only if the program ran the whole session; extra, the tests use the shared database)")
    if not any_found:
        a.say("   nothing recorded yet.")


def trading_days(a: Audit) -> int:
    """Weekdays in the window, except a weekday NIFTY has no candles for INSIDE its covered period (a holiday)."""
    nifty = next((i for i in a.found if i["series"] == "NIFTY" and i["place"] == "shared"), None)
    seen = nifty["recent_days"] if nifty else set()
    lo, hi = (min(seen), max(seen)) if seen else (None, None)
    count, day = 0, a.start + timedelta(days=1)
    while day <= a.end:
        if day.weekday() < 5 and (day in seen or lo is None or not (lo <= day <= hi)):
            count += 1
        day += timedelta(days=1)
    return count


def verdict(a: Audit) -> list[str]:
    trading = trading_days(a)
    fresh = a.end - timedelta(days=4)
    a.say(f"WHAT THE TESTS NEED: the last {a.window} days up to {a.end} = about {trading} trading days, FYERS only.")
    todo = []
    for key in INDEXES:
        info = next((i for i in a.found if i["series"] == key and i["place"] == "shared"), None)
        have = len(info["recent_clean"]) if info else 0
        ok = have >= ENOUGH * trading and info and info["last"] and info["last"] >= fresh
        a.say(f"   {key:<10} {'OK  ' if ok else 'NEED'} {have} clean of {trading} days"
              + (f", newest {info['last']}" if info and info["last"] else ""))
        if not ok:
            todo.append("indexes")
    stocks = [i for i in a.found if i["stock"]]
    clean = sum(len(i["recent_clean"]) for i in stocks)
    need = max(1, len(stocks)) * trading
    newest = max((i["last"] for i in stocks if i["last"]), default=None)
    ok = bool(stocks) and clean >= ENOUGH * need and newest is not None and newest >= fresh
    a.say(f"   F&O stocks {'OK  ' if ok else 'NEED'} {len(stocks)} stocks, {clean} clean of about {need if stocks else 0}"
          f" stock-days" + (f", newest {newest}" if newest else ""))
    if not ok:
        todo.append("stocks")
    if todo:
        only = "" if len(set(todo)) > 1 else f" --only {todo[0]}"
        a.say(f"NEXT: python scripts\\fetch_data.py{only}   (FYERS login first; then run this check again)")
    else:
        a.say("NEXT: data is complete and clean enough. Run: python scripts\\prove_strategies.py")
    return todo


def main(argv=None, *, today: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Check the shared FYERS price data on this PC.")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--kq-db", type=Path, default=None, help="the shared database (default: KunalQuant's)")
    args = p.parse_args(argv)
    from scripts.fetch_data import last_finished_day
    a = Audit(args.days, today or last_finished_day(datetime.now(IST)))
    a.say(f"KUNAL QUANT - DATA CHECK  {datetime.now(IST):%Y-%m-%d %H:%M}  (window: {a.start} to {a.end})")
    a.say("A day is CLEAN when every minute 09:15-15:29 is there with sane prices (stocks: up to 15:14, a few quiet "
          "minutes allowed, never in the first 15, no split / bonus jump).")
    a.say()
    audit_shared(a, KQStore(args.kq_db or default_path()))
    a.say()
    audit_live(a, args.data_folder / "paper_trading")
    a.say()
    verdict(a)
    out = args.data_folder / "research"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "data_audit_days.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["place", "series", "day", "clean", "candles", "reason"])
        writer.writeheader()
        writer.writerows(a.rows)
    (out / "data_audit.txt").write_text("\n".join(a.lines) + "\n", encoding="utf-8")
    print(f"Saved: {out / 'data_audit.txt'} and data_audit_days.csv (every day with its reason)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
