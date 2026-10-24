"""Gap Reversal backtest on F&O stocks (and indexes). Research only.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\gap_reversal_backtest.py
        (all F&O stocks, free Yahoo 1-minute data: last ~29 days, no login)
    python scripts\\gap_reversal_backtest.py --source fyers --days 90
        (FYERS 1-minute history, needs today's FYERS login; longer history)
    python scripts\\gap_reversal_backtest.py --symbols HCLTECH,ADANIENT,SWIGGY
    python scripts\\gap_reversal_backtest.py --source cache
        (re-run on data already downloaded, e.g. after changing settings)
    python scripts\\gap_reversal_backtest.py --interval 5m
    python scripts\\gap_reversal_backtest.py --gap-pct 1
        (test gaps of 1% or more; the dashboard setting stays as it is)
        (Yahoo 5-minute data: about 60 days instead of 29; entries and stops less precise)

Every trade is run with each exit plan: fixed targets 1:1.5, 1:2, 1:2.5, 1:3 and "TSL only" (empty reward
box) for each TSL method with the owner's numbers. Money: --capital-per-trade (default 50,000) per entry,
before and after estimated intraday charges.

Uses the settings saved from the dashboard (data\\gap_reversal\\settings.json). Downloads are kept in
data\\research\\market_data.db, so a second run is fast. Results in data\\gap_reversal\\:
backtest_summary.csv, backtest_trades.csv, backtest_candidates.csv (with --interval 5m: *_5m.csv).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.research_store import ResearchStore  # noqa: E402
from market_data.stock_universe import load_fno_stocks  # noqa: E402
from research.gap_reversal_backtest import (  # noqa: E402
    CAPITAL_PER_TRADE, apply_daily_cap, cap_study, run_symbol, summarize,
)
from strategies.gap_reversal import GapReversalStore  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def series_name(stock: str) -> str:
    return f"STK_{stock}"


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def download(stock: str, source: str, store: ResearchStore, *, days: int, client=None, yahoo_get=None, pause=0.3,
             interval: str = "1m"):
    if source == "yahoo":
        from market_data.sources import yahoo
        kwargs = {"get": yahoo_get} if yahoo_get else {}
        candles = yahoo.fetch(stock, interval, days=days, stock=True, pause=pause, **kwargs)
    else:
        from market_data.sources.fyers_history import fetch_history
        today = datetime.now(IST).date()
        candles = fetch_history(client, f"NSE:{stock}-EQ", resolution=interval.rstrip("m"),
                                start=today - timedelta(days=days), end=today, pause=pause)
    store.save_candles(series_name(stock), source, interval, candles)
    return candles


def main(argv=None, *, client=None, yahoo_get=None, master=None) -> int:
    p = argparse.ArgumentParser(description="Gap Reversal backtest on F&O stocks.")
    p.add_argument("--source", choices=("yahoo", "fyers", "cache"), default="yahoo")
    p.add_argument("--symbols", default="", help="comma list (default: every F&O stock)")
    p.add_argument("--days", type=int, default=None, help="days back (default 29 for 1m, 59 for 5m)")
    p.add_argument("--interval", choices=("1m", "5m"), default="1m")
    p.add_argument("--capital-per-trade", type=float, default=CAPITAL_PER_TRADE)
    p.add_argument("--gap-pct", type=float, default=None,
                   help="test another gap size (e.g. 1); the saved dashboard setting is not changed")
    p.add_argument("--entry-from", default=None,
                   help="test another earliest entry time, e.g. 09:15 (the saved setting is not changed)")
    p.add_argument("--max-trades", type=int, default=None,
                   help="test another daily trade cap (0 = no limit); the saved setting is not changed")
    p.add_argument("--cache-source", default="yahoo", help="with --source cache: which download to use")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--pause", type=float, default=0.3)
    args = p.parse_args(argv)
    days = args.days or (29 if args.interval == "1m" else 59)

    settings = GapReversalStore(args.data_folder / "gap_reversal").settings
    if args.gap_pct is not None:
        from dataclasses import replace
        settings = replace(settings, gap_pct=args.gap_pct)
    if args.entry_from is not None:
        from dataclasses import replace
        settings = replace(settings, entry_from=args.entry_from)
    if args.max_trades is not None:
        from dataclasses import replace
        settings = replace(settings, max_trades_per_day=args.max_trades)
    if args.symbols.strip():
        stocks = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    else:
        stocks = [s["stock"] for s in load_fno_stocks(args.data_folder, today=datetime.now(IST).date(),
                                                       fetch=(lambda url: master) if master else None)]
    if args.source == "fyers" and client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    store = ResearchStore(args.data_folder / "research" / "market_data.db")
    print(f"Gap Reversal backtest: {len(stocks)} symbols, source {args.source}, gap >= {settings.gap_pct}%, "
          f"{settings.timeframe}-min candles, first {settings.window_bars()} candles, entries from {settings.entry_from}")
    all_candidates, all_trades, failed = [], [], []
    for n, stock in enumerate(stocks, 1):
        try:
            if args.source == "cache":
                minutes = store.load(series_name(stock), args.cache_source, args.interval, clean_only=False)
            else:
                minutes = download(stock, args.source, store, days=days, client=client, yahoo_get=yahoo_get,
                                   pause=args.pause, interval=args.interval)
        except Exception as exc:             # one bad symbol must not stop the run
            failed.append(f"{stock}: {exc}")
            continue
        candidates, trades = run_symbol(stock, minutes, settings, capital_per_trade=args.capital_per_trade)
        all_candidates += candidates
        all_trades += trades
        if n % 25 == 0:
            print(f"  {n}/{len(stocks)} symbols done, {len(all_candidates)} setups marked so far")
    study = cap_study(all_trades, settings)
    uncapped = len(all_trades)
    all_trades = apply_daily_cap(all_trades, settings)
    summary = summarize(all_trades)
    out = args.data_folder / "gap_reversal"
    tag = "" if args.interval == "1m" else "_" + args.interval
    write_csv(out / f"backtest_candidates{tag}.csv", all_candidates)
    write_csv(out / f"backtest_trades{tag}.csv", all_trades)
    write_csv(out / f"backtest_summary{tag}.csv", summary)
    write_csv(out / f"backtest_cap_study{tag}.csv", study)
    days_seen = sorted({t["day"] for t in all_trades} | {c["day"] for c in all_candidates})
    (out / f"backtest_meta{tag}.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": args.source,
        "interval": args.interval, "symbols": len(stocks), "failed": failed, "days_back": days,
        "capital_per_trade": args.capital_per_trade, "trade_rows_before_cap": uncapped, "first_day": days_seen[0] if days_seen else None,
        "last_day": days_seen[-1] if days_seen else None, "settings": settings.to_dict()},
        indent=1, default=str), encoding="utf-8")
    print("-" * 118)
    print(f"Rs {args.capital_per_trade:,.0f} per entry. R = multiples of the risk to the stop. Net = after estimated "
          "intraday charges.")
    for side in ("BOTH", "SHORT", "LONG"):
        rows = [r for r in summary if r["group"] == "ALL" and r["side"] == side]
        if not rows:
            continue
        print(f"\n{side}{'  (long + short together)' if side == 'BOTH' else ''}")
        print(f"  {'entry':<6}{'exit plan':<44}{'trades':>6}{'win%':>7}{'avg R':>8}{'PF':>6}"
              f"{'gross Rs':>11}{'charges':>9}{'net Rs':>11}")
        for r in rows:
            print(f"  {r['entry_mode']:<6}{r['exit_plan'][:43]:<44}{r['trades']:>6}{r['win_rate_pct']:>7}"
                  f"{r['expectancy_r']:>8}{r['profit_factor']:>6}{r['gross_pnl']:>11,.0f}{r['charges']:>9,.0f}"
                  f"{r['net_pnl']:>11,.0f}")
    cap = settings.max_trades_per_day
    print(f"\nDaily trade cap used above: {cap or 'no limit'} (SHORT {settings.max_short_per_day or '-'}, "
          f"LONG {settings.max_long_per_day or '-'}). Same exits for other caps (break entry, net Rs):")
    names = list(dict.fromkeys(r["exit"] for r in study))
    caps = list(dict.fromkeys(r["max_trades_per_day"] for r in study))
    print(f"  {'exit plan':<44}" + "".join(f"{('cap ' + str(c)) if c != 'no limit' else 'no cap':>11}" for c in caps))
    for ex in names:
        cells = {r["max_trades_per_day"]: r for r in study if r["exit"] == ex and r["entry_mode"] == "BREAK"}
        label = next(r["exit_plan"] for r in study if r["exit"] == ex)
        print(f"  {label[:43]:<44}" + "".join(f"{cells[c]['net_pnl'] if c in cells else 0:>11,.0f}" for c in caps))
    gap_days = len({(c['symbol'], c['day']) for c in all_candidates})
    print(f"\nSetups marked: {len(all_candidates)} on {gap_days} gap days. Failed downloads: {len(failed)}")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
