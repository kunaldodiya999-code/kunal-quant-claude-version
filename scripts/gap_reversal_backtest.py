"""Gap Reversal backtest on F&O stocks (and indexes). Research only.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\gap_reversal_backtest.py
        (all F&O stocks, free Yahoo 1-minute data: last ~29 days, no login)
    python scripts\\gap_reversal_backtest.py --source fyers --days 90
        (FYERS 1-minute history, needs today's FYERS login; longer history)
    python scripts\\gap_reversal_backtest.py --symbols HCLTECH,ADANIENT,SWIGGY
    python scripts\\gap_reversal_backtest.py --source cache
        (re-run on data already downloaded, e.g. after changing settings)

Uses the settings saved from the dashboard (data\\gap_reversal\\settings.json). Downloads are kept in
data\\research\\market_data.db, so a second run is fast. Results in data\\gap_reversal\\:
backtest_summary.csv, backtest_trades.csv, backtest_candidates.csv.
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
from research.gap_reversal_backtest import run_symbol, summarize  # noqa: E402
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


def download(stock: str, source: str, store: ResearchStore, *, days: int, client=None, yahoo_get=None, pause=0.3):
    if source == "yahoo":
        from market_data.sources import yahoo
        kwargs = {"get": yahoo_get} if yahoo_get else {}
        candles = yahoo.fetch(stock, "1m", days=days, stock=True, pause=pause, **kwargs)
    else:
        from market_data.sources.fyers_history import fetch_history
        today = datetime.now(IST).date()
        candles = fetch_history(client, f"NSE:{stock}-EQ", resolution="1", start=today - timedelta(days=days),
                                end=today, pause=pause)
    store.save_candles(series_name(stock), source, "1m", candles)
    return candles


def main(argv=None, *, client=None, yahoo_get=None, master=None) -> int:
    p = argparse.ArgumentParser(description="Gap Reversal backtest on F&O stocks.")
    p.add_argument("--source", choices=("yahoo", "fyers", "cache"), default="yahoo")
    p.add_argument("--symbols", default="", help="comma list (default: every F&O stock)")
    p.add_argument("--days", type=int, default=29)
    p.add_argument("--cache-source", default="yahoo", help="with --source cache: which download to use")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--pause", type=float, default=0.3)
    args = p.parse_args(argv)

    settings = GapReversalStore(args.data_folder / "gap_reversal").settings
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
          f"{settings.timeframe}-min candles, first {settings.window_bars()} candles")
    all_candidates, all_trades, failed = [], [], []
    for n, stock in enumerate(stocks, 1):
        try:
            if args.source == "cache":
                minutes = store.load(series_name(stock), args.cache_source, "1m", clean_only=False)
            else:
                minutes = download(stock, args.source, store, days=args.days, client=client, yahoo_get=yahoo_get,
                                   pause=args.pause)
        except Exception as exc:             # one bad symbol must not stop the run
            failed.append(f"{stock}: {exc}")
            continue
        candidates, trades = run_symbol(stock, minutes, settings)
        all_candidates += candidates
        all_trades += trades
        if n % 25 == 0:
            print(f"  {n}/{len(stocks)} symbols done, {len(all_candidates)} setups marked so far")
    summary = summarize(all_trades)
    out = args.data_folder / "gap_reversal"
    write_csv(out / "backtest_candidates.csv", all_candidates)
    write_csv(out / "backtest_trades.csv", all_trades)
    write_csv(out / "backtest_summary.csv", summary)
    (out / "backtest_meta.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": args.source, "symbols": len(stocks),
        "failed": failed, "settings": settings.to_dict()}, indent=1, default=str), encoding="utf-8")
    print("-" * 96)
    for row in summary:
        if row["group"] == "ALL":
            print(f"{row['side']:<6}{row['entry_mode']:<6} 1:{row['rr']:<4} trades {row['trades']:>4}  "
                  f"win {row['win_rate_pct']:>5}%  PF {row['profit_factor']:>5}  avg {row['avg_r']:>6} R  "
                  f"total {row['total_r']:>7} R")
    gap_days = len({(c['symbol'], c['day']) for c in all_candidates})
    print(f"Setups marked: {len(all_candidates)} on {gap_days} gap days. Failed downloads: {len(failed)}")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
