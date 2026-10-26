"""What price data is on this PC, which days are CLEAN, and what is missing up to today. Read-only, no login.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\data_audit.py
    python scripts\\data_audit.py --days 90        (the window the tests need; default 90 = about 3 months)

Looks at every place candles are kept:
  1. KunalQuant database   C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db (5-year NIFTY ...)
  2. research database     data\\research\\market_data.db (Yahoo sweep, FYERS download of scripts\\fetch_data.py)
  3. live recordings       data\\paper_trading\\<INDEX>\\minute_candles.csv (+ futures) from the trading program
Every 1-minute day is checked with market_data/day_quality.py (indexes strict; stocks: STOCK rules).
Saved: data\\research\\data_audit.txt (this text) and data\\research\\data_audit_days.csv (every day + reason).
At the end: what the strategy tests need and the command that fills the gap.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import INDEX_RULES, STOCK_RULES, assess_series  # noqa: E402
from market_data.resampling import Candle  # noqa: E402
from research.data_loader import DEFAULT_KQ_DB  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
INDEXES = ("NIFTY", "BANKNIFTY", "SENSEX")
KQ_INDEX = {"NSE:NIFTY50-INDEX": "NIFTY", "NSE:NIFTYBANK-INDEX": "BANKNIFTY", "BSE:SENSEX-INDEX": "SENSEX",
            "NSE:INDIAVIX-INDEX": "INDIAVIX"}
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
        for r in reports:
            self.rows.append({"place": place, "series": series, "day": r.day.isoformat(), "clean": int(r.clean),
                              "candles": r.actual, "reason": r.reason})
        recent = [r for r in reports if self.start <= r.day <= self.end]
        info = {"place": place, "series": series, "days": len(reports), "clean": sum(r.clean for r in reports),
                "first": reports[0].day if reports else None, "last": reports[-1].day if reports else None,
                "recent_days": {r.day for r in recent}, "recent_clean": {r.day for r in recent if r.clean},
                "broken": [(r.day, r.reason) for r in recent if not r.clean]}
        self.found.append(info)
        return info


def _candles(rows) -> list[Candle]:
    return [Candle(int(t), float(o), float(h), float(l), float(c), None if v is None else int(v))
            for t, o, h, l, c, v in rows]


def audit_kq_db(a: Audit, path: Path) -> None:
    a.say(f"1. KunalQuant database: {path}")
    if not path.exists():
        a.say("   not found on this PC (fine: the tests use the research database below).")
        return
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        kinds = db.execute("SELECT i.instrument_type, COUNT(DISTINCT i.id) FROM instruments i "
                           "GROUP BY i.instrument_type").fetchall()
        a.say("   instruments: " + ", ".join(f"{k} {n}" for k, n in kinds))
        for symbol, key in KQ_INDEX.items():
            rows = db.execute("SELECT c.timestamp, c.open, c.high, c.low, c.close, c.volume FROM candles c JOIN "
                              "instruments i ON i.id = c.instrument_id WHERE i.symbol = ? AND c.resolution = '1' "
                              "GROUP BY c.timestamp ORDER BY c.timestamp", (symbol,)).fetchall()
            if rows:
                info = a.check("kq-db", key, _candles(rows), stock=False)
                a.say(f"   {key:<10} 1-min: {info['clean']} clean of {info['days']} days, {info['first']} to "
                      f"{info['last']}; last {a.window} days: {len(info['recent_clean'])} clean of "
                      f"{len(info['recent_days'])}")
        (n_opt,) = db.execute("SELECT COUNT(*) FROM instruments WHERE option_type IN ('CE', 'PE')").fetchone()
        lo, hi = db.execute("SELECT MIN(timestamp), MAX(timestamp) FROM candles").fetchone()   # uses the index: fast
        if lo:
            a.say(f"   all candles: {datetime.fromtimestamp(lo, IST).date()} to {datetime.fromtimestamp(hi, IST).date()}"
                  f"; option contracts listed: {n_opt}")


def audit_research_db(a: Audit, path: Path) -> None:
    a.say(f"2. Research database: {path}")
    if not path.exists():
        a.say("   not found yet (scripts\\fetch_data.py creates it).")
        return
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        series = db.execute("SELECT series, source, COUNT(*) FROM candles WHERE resolution='1m' "
                            "GROUP BY series, source ORDER BY source, series").fetchall()
        stocks: dict[str, list] = defaultdict(list)
        for name, source, _n in series:
            rows = db.execute("SELECT ts, open, high, low, close, volume FROM candles WHERE series=? AND source=? "
                              "AND resolution='1m' ORDER BY ts", (name, source)).fetchall()
            info = a.check(source, name, _candles(rows), stock=name.startswith("STK_"))
            if name.startswith("STK_"):
                stocks[source].append(info)
            else:
                a.say(f"   {source:<6} {name:<10} 1-min: {info['clean']} clean of {info['days']} days, {info['first']}"
                      f" to {info['last']}; last {a.window} days: {len(info['recent_clean'])} clean of "
                      f"{len(info['recent_days'])}")
        for source, infos in stocks.items():
            days = sum(len(i["recent_days"]) for i in infos)
            clean = sum(len(i["recent_clean"]) for i in infos)
            last = max((i["last"] for i in infos if i["last"]), default=None)
            first = min((i["first"] for i in infos if i["first"]), default=None)
            a.say(f"   {source:<6} F&O stocks: {len(infos)} stocks, {first} to {last}; last {a.window} days: {clean} "
                  f"clean of {days} stock-days ({100 * clean // max(1, days)}%)")
            reasons: dict[str, int] = defaultdict(int)
            for i in infos:
                for _d, why in i["broken"]:
                    reasons[why.split(" (")[0].split(";")[0]] += 1
            if reasons:
                a.say("      most common problems: " + ", ".join(
                    f"{k} x{v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:4]))


def audit_live(a: Audit, folder: Path) -> None:
    a.say(f"3. Live recordings of the trading program: {folder}")
    any_found = False
    for key in INDEXES:
        for name, label in (("minute_candles.csv", key), ("futures_minute_candles.csv", key + "_FUT")):
            path = folder / key / name
            if not path.exists():
                continue
            with path.open(newline="", encoding="utf-8") as handle:
                rows = [r for r in csv.DictReader(handle) if r.get("timestamp")]
            candles = [Candle(int(r["timestamp"]), float(r["open"]), float(r["high"]), float(r["low"]),
                              float(r["close"]), int(float(r.get("volume") or 0))) for r in rows]
            if candles:
                any_found = True
                info = a.check("live", label, sorted({c.timestamp: c for c in candles}.values(),
                                                    key=lambda c: c.timestamp), stock=False)
                a.say(f"   {label:<14} {info['clean']} clean of {info['days']} days, {info['first']} to {info['last']}"
                      " (a day is clean only if the program ran the whole session)")
    if not any_found:
        a.say("   nothing recorded yet.")


def verdict(a: Audit) -> list[str]:
    """What the tests need, from the best place for each, and the command that fills the gap."""
    seen = set()
    for info in a.found:
        seen |= info["recent_days"]
    lo, hi = (min(seen), max(seen)) if seen else (None, None)
    trading, day = 0, a.start + timedelta(days=1)
    while day <= a.end:            # every weekday, except one INSIDE the covered period that no source has (holiday)
        if day.weekday() < 5 and (day in seen or lo is None or not (lo <= day <= hi)):
            trading += 1
        day += timedelta(days=1)
    a.say(f"WHAT THE TESTS NEED: the last {a.window} days up to {a.end} = about {trading} trading days "
          f"(weekdays; a weekday no source has inside the covered period counts as a holiday).")
    todo = []
    for key in INDEXES:
        options = [i for i in a.found if i["series"] == key]
        best = max(options, key=lambda i: len(i["recent_clean"]), default=None)
        have = len(best["recent_clean"]) if best else 0
        ok = have >= ENOUGH * trading and best and best["last"] and best["last"] >= a.end - timedelta(days=4)
        a.say(f"   {key:<10} {'OK  ' if ok else 'NEED'} {have} clean of {trading} days"
              + (f" (best: {best['place']}, newest {best['last']})" if best else " (no data)"))
        if not ok:
            todo.append("indexes")
    for place in ("fyers", "yahoo"):
        infos = [i for i in a.found if i["place"] == place and i["series"].startswith("STK_")]
        if not infos:
            continue
        clean = sum(len(i["recent_clean"]) for i in infos)
        need = len(infos) * trading
        newest = max(i["last"] for i in infos if i["last"])
        ok = clean >= ENOUGH * need and newest >= a.end - timedelta(days=4) and place == "fyers"
        a.say(f"   F&O stocks ({place}) {'OK  ' if ok else 'NEED'} {clean} clean of about {need} stock-days, "
              f"newest {newest}" + ("" if place == "fyers" else "  (Yahoo stocks: only ~30 days; use FYERS)"))
    if not any(i["place"] == "fyers" and i["series"].startswith("STK_") for i in a.found) or any(
            i["place"] == "fyers" and i["series"].startswith("STK_") and i["last"] and
            i["last"] < a.end - timedelta(days=4) for i in a.found):
        todo.append("stocks")
    if todo:
        only = "" if len(set(todo)) > 1 else f" --only {todo[0]}"
        a.say(f"NEXT: python scripts\\fetch_data.py{only}   (FYERS login first; then run this check again)")
    else:
        a.say("NEXT: data is complete and clean enough. Run: python scripts\\prove_strategies.py")
    return todo


def main(argv=None, *, today: date | None = None) -> int:
    p = argparse.ArgumentParser(description="Check every price data store on this PC.")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--kq-db", type=Path, default=DEFAULT_KQ_DB)
    args = p.parse_args(argv)
    from scripts.fetch_data import last_finished_day
    a = Audit(args.days, today or last_finished_day(datetime.now(IST)))
    a.say(f"KUNAL QUANT - DATA CHECK  {datetime.now(IST):%Y-%m-%d %H:%M}  (window: {a.start} to {a.end})")
    a.say("A day is CLEAN when every minute 09:15-15:29 is there with sane prices (stocks: up to 15:14, a few quiet "
          "minutes allowed, never in the first 15).")
    a.say()
    audit_kq_db(a, args.kq_db)
    a.say()
    audit_research_db(a, args.data_folder / "research" / "market_data.db")
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
