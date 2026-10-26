"""How accurate are KTMI Uni Lite's BUY CALL / BUY PUT arrows? (research, index points)

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\ktmi_accuracy.py                        (data from the sweep: research database)
    python scripts\\ktmi_accuracy.py --source kq-db --index NIFTY
        (your 5 years of NIFTY 1-minute in KunalQuant\\data\\database\\kunal_quant.db)

Only CLEAN days count. Entry = next minute after the signal candle closes.
Results: data\\research\\results\\ktmi_accuracy_summary.csv and ktmi_accuracy_signals.csv
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
from research.data_loader import load, nifty_scales  # noqa: E402
from research.ktmi_accuracy import evaluate, find_signals  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
TARGETS = (20.0, 30.0, 40.0, 50.0)     # NIFTY points, scaled for other indexes
STOPS = (15.0, 20.0, 25.0)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="KTMI Uni Lite signal accuracy on clean historical days.")
    p.add_argument("--source", choices=("fyers", "kq-db"), default="fyers",
                   help="the shared FYERS database (KunalQuant); kq-db = the same")
    p.add_argument("--days", type=int, default=None, help="test only the last N days (default: all)")
    p.add_argument("--index", default="NIFTY,BANKNIFTY,SENSEX")
    p.add_argument("--timeframes", default="3,5")
    p.add_argument("--kq-db", type=Path, default=None)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    args = p.parse_args(argv)
    indexes = [x.strip().upper() for x in args.index.split(",") if x.strip()]
    frames = [int(x) for x in args.timeframes.split(",")]

    data = {k: load(args.source, k, kq_db=args.kq_db, days=args.days)
            for k in indexes}
    data = {k: v for k, v in data.items() if v[1]}
    if not data:
        raise SystemExit("No clean data found. Run  python scripts\\sweep_market_data.py  first.")
    scales = nifty_scales({k: v[1] for k, v in data.items()})
    summary, signals = [], []
    for index, (everything, clean) in data.items():
        days = sorted(group_by_day(clean))
        for tf in frames:
            sigs = find_signals(everything, index=index, timeframe=tf, clean_days=days)
            s = scales[index]
            res = evaluate(sigs, clean, targets=[t * s for t in TARGETS], stops=[x * s for x in STOPS])
            signals += res["signals"]
            for g in res["grid"]:
                summary.append({"index": index, "timeframe": tf, "clean_days": len(days),
                                "first_day": days[0], "last_day": days[-1],
                                "target_nifty_pts": round(g["target"] / s), "stop_nifty_pts": round(g["stop"] / s),
                                **{k: g[k] for k in ("trades", "win_rate_pct", "profit_factor", "avg_points",
                                                     "approx_option_points")},
                                **{f"dir_acc_{h}": v for h, v in res["direction_accuracy_pct"].items()}})
            best = max(res["grid"], key=lambda g: g["profit_factor"]) if res["grid"] else None
            print(f"{index:<10} {tf}m  {len(days):>4} clean days  {len(sigs):>5} signals  direction right after "
                  f"5/15/30 min: {res['direction_accuracy_pct']}  best PF {best['profit_factor'] if best else '-'}")
    out = args.data_folder / "research" / "results"
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("ktmi_accuracy_summary.csv", summary), ("ktmi_accuracy_signals.csv", signals)):
        with (out / name).open("w", newline="", encoding="utf-8") as handle:
            fields = list(dict.fromkeys(k for r in rows for k in r))
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    (out / "ktmi_accuracy_meta.json").write_text(json.dumps({
        "generated_at": datetime.now(IST).isoformat(timespec="seconds"), "source": args.source,
        "indexes": list(data), "timeframes": frames}, indent=2), encoding="utf-8")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
