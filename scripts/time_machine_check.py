"""Check the Time Machine against what really happened (backtest trades; no look-ahead).

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\time_machine_check.py
        Gap Reversal and Open High Low 5-minute backtest trades (run those backtests first)
    python scripts\\time_machine_check.py --trades data\\gap_reversal\\backtest_trades.csv --interval 1m

For each trade the odds are made with only the stock's earlier sessions; then trades are grouped by the predicted
chances and each group's REAL win rate, average R and net rupees are shown. Result: data\\time_machine\\check.csv.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from research.time_machine_check import calibration, check  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Is the Time Machine right?")
    p.add_argument("--trades", type=Path, action="append", default=None)
    p.add_argument("--interval", choices=("1m", "5m"), default="5m")
    p.add_argument("--exits", default="1:2,1:3,TSL PSAR_0.04_0.04_0.10")
    p.add_argument("--replays", type=int, default=1000)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    tag = "" if args.interval == "1m" else "_5m"
    files = args.trades or [args.data_folder / "gap_reversal" / f"backtest_trades{tag}.csv",
                            args.data_folder / "open_high_low" / f"backtest_trades{tag}.csv"]
    wanted = {x.strip() for x in args.exits.split(",")}
    rows = []
    for f in files:
        if f.exists():
            rows += [r for r in csv.DictReader(f.open(encoding="utf-8"))
                     if r["exit"] in wanted and r.get("entry_mode", "SCAN") in ("BREAK", "SCAN")]
    if not rows:
        print("No backtest trades found. Run scripts\\gap_reversal_backtest.py / scripts\\open_high_low_backtest.py first.")
        return 1
    from market_data.clean_days import stock_candles
    from market_data.kq_store import KQStore
    store = KQStore()                                                      # the shared FYERS database
    done = check(rows, lambda s: stock_candles(store, s, args.interval),
                 replays=args.replays,
                 progress=lambda n, total: print(f"  {n}/{total}", flush=True) if n % 100 == 0 else None)
    table = calibration(done)
    out = args.data_folder / "time_machine" / "check.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as h:
        w = csv.DictWriter(h, fieldnames=list(table[0]))
        w.writeheader()
        w.writerows(table)
    print(f"{len(rows)} trades, {len(done)} with 20+ earlier sessions.")
    for r in table:
        print(f"  {r['exit']:<26}{r['group']:<26}{r['trades']:>5} trades  predicted win {r['predicted_win_pct']:>5}%  "
              f"real win {r['actual_win_pct']:>5}%  avg {r['actual_avg_r']:>6}R  net Rs {r['net_pnl']:>9,.0f}")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
