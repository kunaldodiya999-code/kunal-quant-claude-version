"""Gap Reversal backtest on F&O stocks (and indexes). Research only.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version, after  python scripts\\fetch_data.py :

    python scripts\\gap_reversal_backtest.py                 every stock in the shared FYERS database, last 90 days
    python scripts\\gap_reversal_backtest.py --symbols HCLTECH,ADANIENT,SWIGGY
    python scripts\\gap_reversal_backtest.py --interval 5m   (5-minute candles built from the 1-minute ones)
    python scripts\\gap_reversal_backtest.py --gap-pct 1     (test gaps of 1% or more; the dashboard setting stays)
    python scripts\\gap_reversal_backtest.py --days 365      (more days, if the database has them)

FYERS data only, from the ONE shared database (market_data/kq_store.py); CLEAN days only (market_data/clean_days.py,
--all-days to switch that off).
Every trade is run with each exit plan: fixed targets 1:1.5, 1:2, 1:2.5, 1:3 and "TSL only" (empty reward
box) for each TSL method with the owner's numbers. Money: --capital-per-trade (default 50,000) per entry,
before and after estimated intraday charges.

Uses the settings saved from the dashboard (data\\gap_reversal\\settings.json). Results in data\\gap_reversal\\:
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

from research.gap_reversal_backtest import (  # noqa: E402
    CAPITAL_PER_TRADE, apply_daily_cap, cap_study, run_symbol, summarize,
)
from strategies.gap_reversal import GapReversalStore  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Gap Reversal backtest on F&O stocks.")
    p.add_argument("--symbols", default="", help="comma list (default: every stock in the shared database)")
    p.add_argument("--days", type=int, default=90, help="test the last N days (default 90)")
    p.add_argument("--kq-db", type=Path, default=None, help="the shared database (default: KunalQuant's)")
    p.add_argument("--interval", choices=("1m", "5m"), default="1m")
    p.add_argument("--capital-per-trade", type=float, default=CAPITAL_PER_TRADE)
    p.add_argument("--gap-pct", type=float, default=None,
                   help="test another gap size (e.g. 1); the saved dashboard setting is not changed")
    p.add_argument("--entry-from", default=None,
                   help="test another earliest entry time, e.g. 09:15 (the saved setting is not changed)")
    p.add_argument("--max-trades", type=int, default=None,
                   help="test another daily trade cap (0 = no limit); the saved setting is not changed")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--all-days", action="store_true",
                   help="also trade days that are not clean (default: clean days only, market_data/clean_days.py)")
    args = p.parse_args(argv)
    days = args.days

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
    from market_data.clean_days import stock_candles, tradable_days
    from market_data.kq_store import KQStore, default_path
    store = KQStore(args.kq_db or default_path())
    stocks = [x.strip().upper() for x in args.symbols.split(",") if x.strip()] or store.stocks()
    since = datetime.now(IST).date() - timedelta(days=days + 5)
    calendar = store.trading_days(since)
    print(f"Gap Reversal backtest: {len(stocks)} stocks, shared FYERS database, last {days} days, gap >= "
          f"{settings.gap_pct}%, {settings.timeframe}-min candles, first {settings.window_bars()} candles, entries from "
          f"{settings.entry_from}")
    if not stocks:
        print("No stocks in the shared database yet. Run  python scripts\\fetch_data.py  first.")
        return 1
    counts = {"days": 0, "clean": 0, "tradable": 0}
    all_candidates, all_trades, failed = [], [], []
    for n, stock in enumerate(stocks, 1):
        try:
            minutes = stock_candles(store, stock, args.interval, since=since)
        except Exception as exc:             # one bad symbol must not stop the run
            failed.append(f"{stock}: {exc}")
            continue
        allowed = None
        if not args.all_days:
            allowed, c = tradable_days(minutes, calendar, minutes=int(args.interval.rstrip("m")))
            counts = {k: counts[k] + c[k] for k in counts}
        candidates, trades = run_symbol(stock, minutes, settings, capital_per_trade=args.capital_per_trade,
                                        trade_days=allowed)
        all_candidates += candidates
        all_trades += trades
        if n % 25 == 0:
            print(f"  {n}/{len(stocks)} symbols done, {len(all_candidates)} setups marked so far")
    if not args.all_days:
        print(f"Clean data: {counts['tradable']} of {counts['days']} stock-days traded ({counts['clean']} clean; a clean "
              "day also needs the stock's previous trading day). --all-days = every day.")
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
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": "shared FYERS database",
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
