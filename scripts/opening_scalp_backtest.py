"""Backtest the Opening Scalp (first minutes after 09:15) on clean historical days.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\opening_scalp_backtest.py                       (research database, 1-minute)
    python scripts\\opening_scalp_backtest.py --source kq-db --index NIFTY
        (your 5 years of NIFTY 1-minute: THE real test)

Prints the default setting's result, every tested setting (grid) and a
walk-forward check (choose on the first half of days, test on the unseen
second half). Saves data\\research\\results\\opening_scalp_*.  Research only.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_data.day_quality import group_by_day  # noqa: E402
from research.data_loader import load, nifty_scales  # noqa: E402
from research.opening_scalp_backtest import GRID, grid_search, run_days, summarize  # noqa: E402
from strategies.opening_scalp import OpeningScalpConfig  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _line(name: str, s: dict) -> str:
    return (f"{name:<28} trades {s['trades']:>4}  win {s['win_rate_pct']:>5}%  PF {s['profit_factor']:>5}  "
            f"avg {s['avg_points']:>6} pts  (ATM option ~{s['approx_option_points_per_trade']} pts/trade, estimate)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Opening Scalp backtest on clean days.")
    p.add_argument("--source", choices=("fyers", "kq-db"), default="fyers",
                   help="the shared FYERS database (KunalQuant); kq-db = the same")
    p.add_argument("--days", type=int, default=None, help="test only the last N days (default: all)")
    p.add_argument("--index", default="NIFTY,BANKNIFTY,SENSEX")
    p.add_argument("--resolution", choices=("1m", "5m"), default="1m")
    p.add_argument("--kq-db", type=Path, default=None)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    seconds = 60 if args.resolution == "1m" else 300
    indexes = [x.strip().upper() for x in args.index.split(",") if x.strip()]
    clean = {k: load(args.source, k, resolution=args.resolution, kq_db=args.kq_db,
                     days=args.days)[1] for k in indexes}
    clean = {k: v for k, v in clean.items() if v}
    if not clean:
        raise SystemExit("No clean data found. Run  python scripts\\sweep_market_data.py  first.")
    series = {k: group_by_day(v) for k, v in clean.items()}
    scales = nifty_scales(clean)
    config = OpeningScalpConfig(enabled=False)

    trades = [t for k, d in series.items() for t in run_days(d, config.scaled(scales[k]), bar_seconds=seconds, index=k)]
    print("=" * 100)
    print(f"OPENING SCALP BACKTEST  source={args.source} {args.resolution}  "
          + ", ".join(f"{k}: {len(d)} clean days" for k, d in series.items()))
    print(f"Default: {config.mode}, range {config.range_minutes} min, target {config.target_points:g}, stop <= "
          f"{config.max_stop:g}, stop-to-cost after {config.breakeven_after}, entries until {config.last_entry:%H:%M}, "
          f"exit by {config.exit_by:%H:%M}   (NIFTY points; scaled per index)")
    print("=" * 100)
    default = summarize(trades, scales)
    print(_line("DEFAULT (all indexes)", default))
    for direction in ("LONG", "SHORT"):
        print(_line(f"  {direction}", summarize([t for t in trades if t["direction"] == direction], scales)))
    for k in series:
        print(_line(f"  {k}", summarize([t for t in trades if t["index"] == k], scales)))

    grid = grid_search(series, scales, bar_seconds=seconds)
    first = {k: {d: v[d] for d in sorted(v)[:len(v) // 2]} for k, v in series.items()}
    second = {k: {d: v[d] for d in sorted(v)[len(v) // 2:]} for k, v in series.items()}
    ranked = [r for r in grid_search(first, scales, bar_seconds=seconds) if r["trades"] >= 8]
    walk = {}
    if ranked:
        chosen = replace(config, **{k: ranked[0][k] for k in GRID})
        test = summarize([t for k, d in second.items()
                          for t in run_days(d, chosen.scaled(scales[k]), bar_seconds=seconds, index=k)], scales)
        default_halves = [summarize([t for k, d in half.items()
                                     for t in run_days(d, config.scaled(scales[k]), bar_seconds=seconds, index=k)],
                                    scales) for half in (first, second)]
        walk = {"chosen_on_first_half": {k: ranked[0][k] for k in GRID}, "first_half_pf": ranked[0]["profit_factor"],
                "second_half_unseen": test, "default_first_half": default_halves[0],
                "default_second_half": default_halves[1]}
        print("-" * 100)
        print(f"Walk-forward: best on first half {walk['chosen_on_first_half']} (PF {walk['first_half_pf']})")
        print(_line("  -> on unseen second half", test))
        print(_line("Default on first half", default_halves[0]))
        print(_line("Default on second half", default_halves[1]))
    print("-" * 100)
    print("Top 5 settings (beware: the best of many is usually luck; trust walk-forward and long data):")
    for r in grid[:5]:
        print("  ", {k: r[k] for k in GRID}, f"PF {r['profit_factor']} n {r['trades']}")

    out = args.data_folder / "research" / "results"
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("opening_scalp_trades.csv", trades), ("opening_scalp_grid.csv", grid)):
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            fields = list(dict.fromkeys(k for r in rows for k in r)) or ["none"]
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    (out / "opening_scalp_summary.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": args.source,
        "resolution": args.resolution, "clean_days": {k: len(d) for k, d in series.items()},
        "default_config": {k: str(v) for k, v in asdict(config).items()}, "default": default,
        "walk_forward": walk}, indent=2, default=str), encoding="utf-8")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
