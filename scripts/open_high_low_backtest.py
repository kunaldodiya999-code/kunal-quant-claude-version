"""Open High Low backtest on F&O stocks (spot candles; see research/open_high_low_backtest.py for the scope).

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\open_high_low_backtest.py
        every F&O stock, the candles already downloaded by the Gap Reversal backtest (1-minute, ~29 days)
    python scripts\\open_high_low_backtest.py --interval 5m
        5-minute candles (~60 days)
    python scripts\\open_high_low_backtest.py --source yahoo
        download first (free Yahoo data, no login), then test
    python scripts\\open_high_low_backtest.py --first-candle 15 --top-n 3

Uses the settings saved from the dashboard (data\\open_high_low\\settings.json). Results in data\\open_high_low\\:
backtest_summary.csv, backtest_trades.csv, backtest_candidates.csv, backtest_top_n.csv (5m: *_5m.csv).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.research_store import ResearchStore  # noqa: E402
from market_data.stock_universe import load_fno_stocks  # noqa: E402
from research.open_high_low_backtest import CAPITAL_PER_TRADE, run, summarize, top_n_study  # noqa: E402
from strategies.open_high_low import OpenHighLowStore  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        if rows:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def main(argv=None, *, yahoo_get=None, master=None) -> int:
    p = argparse.ArgumentParser(description="Open High Low backtest (spot candles).")
    p.add_argument("--source", choices=("cache", "yahoo"), default="cache")
    p.add_argument("--interval", choices=("1m", "5m"), default="1m")
    p.add_argument("--symbols", default="")
    p.add_argument("--first-candle", type=int, default=None, help="test another first-candle length in minutes")
    p.add_argument("--entry-candles", type=int, default=None, help="test entries in the next N candles (default 1)")
    p.add_argument("--top-n", type=int, default=None, help="test another top N (setting unchanged)")
    p.add_argument("--min-value-cr", type=float, default=50.0,
                   help="liquidity: Rs crore traded in the stock the previous day (default 50)")
    p.add_argument("--capital-per-trade", type=float, default=CAPITAL_PER_TRADE)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--pause", type=float, default=0.3)
    args = p.parse_args(argv)

    s = OpenHighLowStore(args.data_folder / "open_high_low").settings
    if args.first_candle:
        s = replace(s, first_candle_minutes=args.first_candle)
    if args.entry_candles:
        s = replace(s, entry_valid_candles=args.entry_candles)
    if args.top_n:
        s = replace(s, top_n=args.top_n)
    if args.symbols.strip():
        stocks = [x.strip().upper() for x in args.symbols.split(",") if x.strip()]
    else:
        stocks = [x["stock"] for x in load_fno_stocks(args.data_folder, today=datetime.now(IST).date(),
                                                      fetch=(lambda url: master) if master else None)]
    store = ResearchStore(args.data_folder / "research" / "market_data.db")
    series, failed = {}, []
    for stock in stocks:
        try:
            if args.source == "yahoo":
                from scripts.gap_reversal_backtest import download
                series[stock] = download(stock, "yahoo", store, days=29 if args.interval == "1m" else 59,
                                         yahoo_get=yahoo_get, pause=args.pause, interval=args.interval)
            else:
                series[stock] = store.load(f"STK_{stock}", "yahoo", args.interval, clean_only=False)
        except Exception as exc:                     # one bad symbol must not stop the run
            failed.append(f"{stock}: {exc}")
    series = {k: v for k, v in series.items() if v}
    print(f"Open High Low backtest: {len(series)} stocks with {args.interval} candles, first candle to {s.scan_at}, entry in the next {s.entry_valid_candles} candle(s), top "
          f"{s.top_n}, tolerance {s.tolerance_pct}%, liquidity >= Rs {args.min_value_cr} cr traded the day before")
    if not series:
        print("No candles. Run the Gap Reversal backtest first, or add --source yahoo.")
        return 1
    candidates, trades = run(series, replace(s, top_n=max(10, s.top_n)), min_value_cr=args.min_value_cr,
                             capital_per_trade=args.capital_per_trade)
    study = top_n_study(trades)
    trades = [t for t in trades if t["rank"] <= s.top_n]
    summary = summarize(trades)
    out = args.data_folder / "open_high_low"
    tag = "" if args.interval == "1m" else "_" + args.interval
    write_csv(out / f"backtest_candidates{tag}.csv", candidates)
    write_csv(out / f"backtest_trades{tag}.csv", trades)
    write_csv(out / f"backtest_summary{tag}.csv", summary)
    write_csv(out / f"backtest_top_n{tag}.csv", study)
    days = sorted({c["day"] for c in candidates})
    (out / f"backtest_meta{tag}.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "interval": args.interval,
        "stocks": len(series), "failed": failed, "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None, "capital_per_trade": args.capital_per_trade,
        "min_value_cr": args.min_value_cr, "settings": s.to_dict()}, indent=1, default=str), encoding="utf-8")
    print("-" * 104)
    print(f"Rs {args.capital_per_trade:,.0f} per entry; net = after estimated intraday charges.")
    for side in ("BOTH", "LONG", "SHORT"):
        rows = [r for r in summary if r["side"] == side]
        if rows:
            print(f"\n{side}")
            print(f"  {'exit plan':<44}{'trades':>7}{'win%':>7}{'avg R':>8}{'gross Rs':>11}{'net Rs':>11}{'worst DD':>10}")
            for r in rows:
                print(f"  {r['exit_plan'][:43]:<44}{r['trades']:>7}{r['win_rate_pct']:>7}{r['expectancy_r']:>8}"
                      f"{r['gross_pnl']:>11,.0f}{r['net_pnl']:>11,.0f}{r['max_drawdown']:>10,.0f}")
    print(f"\nOther top-N choices (both sides, net Rs):")
    ns = list(dict.fromkeys(r["top_n"] for r in study))
    print(f"  {'exit plan':<44}" + "".join(f"{'top ' + str(n):>10}" for n in ns))
    for ex in dict.fromkeys(r["exit"] for r in study):
        cells = {r["top_n"]: r["net_pnl"] for r in study if r["exit"] == ex}
        label = next(r["exit_plan"] for r in study if r["exit"] == ex)
        print(f"  {label[:43]:<44}" + "".join(f"{cells.get(n, 0):>10,.0f}" for n in ns))
    short = [c for c in candidates if c["shortlisted"]]
    print(f"\nCandidates: {len(candidates)} on {len(days)} days; shortlisted {len(short)}: entered "
          f"{sum(c['entry'] == 'ENTERED' for c in short)}, no breakout {sum(c['entry'] == 'NO ENTRY' for c in short)}, "
          f"cancelled {sum(c['entry'] == 'CANCELLED' for c in short)}. Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
