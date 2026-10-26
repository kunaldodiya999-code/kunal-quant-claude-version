"""TSL Lab: compare every trailing stop on historical KTMI Uni Lite signals (research, index points).

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\tsl_lab.py                                   (data from the sweep: research database)
    python scripts\\tsl_lab.py --source kq-db --index NIFTY      (5 years of NIFTY from KunalQuant)
    python scripts\\tsl_lab.py --timeframes 3,5 --tsl-timeframes 1,3,5 --triggers CLOSE,TOUCH
    python scripts\\tsl_lab.py --source kq-db --index NIFTY --no-beta    (without the BETA test methods)

BETA test methods (research only, never used live; research/tsl_beta.py) are included and marked BETA:
two-key (index Chandelier 9 x 1.5 close + premium lock), tightening Chandelier, R-ladder.

Every method uses the numbers saved in data\\paper_trading\\<INDEX>\\trade_management.json
(defaults: Chandelier 9 x 1.5, Supertrend 5 x 1.0 and 7 x 1.5, PSAR 0.02/0.02/0.20 and 0.04/0.04/0.10,
point trail 10 / 15). Trails run on the SPOT chart; option-chart trails are compared live.
Results: data\\research\\results\\tsl_lab_summary.csv and tsl_lab_trades.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import group_by_day  # noqa: E402
from paper_trading.trade_management import LABELS, TradeManagementStore  # noqa: E402
from research.data_loader import load  # noqa: E402
from research.ktmi_accuracy import find_signals  # noqa: E402
from research.tsl_beta import BETA_LABELS  # noqa: E402
from research.tsl_lab import run  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Compare trailing stops on historical KTMI Uni Lite signals.")
    p.add_argument("--source", choices=("research", "fyers", "kq-db"), default="research")
    p.add_argument("--index", default="NIFTY,BANKNIFTY,SENSEX")
    p.add_argument("--timeframes", default="3,5", help="KTMI signal timeframes")
    p.add_argument("--tsl-timeframes", default="", help="TSL candle sizes (default: same as the signal)")
    p.add_argument("--triggers", default="CLOSE,TOUCH")
    p.add_argument("--kq-db", type=Path, default=None)
    p.add_argument("--no-beta", action="store_true", help="leave out the BETA test methods")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    indexes = [x.strip().upper() for x in args.index.split(",") if x.strip()]
    frames = [int(x) for x in args.timeframes.split(",")]
    tsl_frames = [int(x) for x in args.tsl_timeframes.split(",") if x.strip()] or None
    triggers = [x.strip().upper() for x in args.triggers.split(",") if x.strip()]

    all_trades, all_summary = [], []
    for index in indexes:
        everything, clean = load(args.source, index, kq_db=args.kq_db,
                                 research_db=args.data_folder / "research" / "market_data.db")
        if not clean:
            print(f"{index}: no clean data, skipped.")
            continue
        settings = TradeManagementStore(args.data_folder / "paper_trading" / index).settings
        days = sorted(group_by_day(clean))
        for tf in frames:
            print(f"{index} {tf}m: finding KTMI signals in {len(days)} clean days (can take a few minutes)...",
                  flush=True)
            signals = find_signals(everything, index=index, timeframe=tf, clean_days=days)
            print(f"{index} {tf}m: {len(signals)} signals, testing every trailing stop on them...", flush=True)
            trades, summary = run(signals, clean, triggers=triggers, tsl_timeframes=tsl_frames, settings=settings,
                                  beta=not args.no_beta,
                                  progress=lambda done, total, i=index, f=tf: print(
                                      f"   {i} {f}m: {done} of {total} signals done ({100 * done // total}%)",
                                      flush=True))
            all_trades += trades
            all_summary += summary
            print(f"{index} {tf}m: {len(days)} clean days, {len(signals)} signals")
            for row in sorted(summary, key=lambda r: r["total_points"], reverse=True):
                print(f"   {LABELS.get(row['method'], BETA_LABELS.get(row['method'], row['method']))[:58]:<58} TSL {row['tsl_timeframe']}m {row['trigger']:<5} "
                      f"total {row['total_points']:>8} pts  PF {row['profit_factor']}  win {row['win_rate_pct']}%  "
                      f"capture {row['capture_pct']}%")
    if not all_summary:
        raise SystemExit("Nothing to test: no clean data or no KTMI signals. Download data first:  "
                         "python scripts\\fetch_data.py  (or  python scripts\\sweep_market_data.py)")
    out = args.data_folder / "research" / "results"
    write_csv(out / "tsl_lab_summary.csv", all_summary)
    write_csv(out / "tsl_lab_trades.csv", all_trades)
    (out / "tsl_lab_meta.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": args.source,
        "indexes": indexes, "timeframes": frames, "tsl_timeframes": tsl_frames or "same as signal",
        "triggers": triggers, "beta": not args.no_beta}, indent=2), encoding="utf-8")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
