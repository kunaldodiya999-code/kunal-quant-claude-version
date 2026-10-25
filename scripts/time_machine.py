"""Time Machine for one trade idea, any time you want it (no chart, just the chances). Paper / research only.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version , (.venv) active:

    python scripts\\time_machine.py --symbol RELIANCE --side LONG --entry 1190 --stop 1180
        chance of reaching 1:1.5 / 1:2 / 1:2.5 / 1:3 before 15:10, and the stop first (FYERS data: login first)
    python scripts\\time_machine.py --symbol RELIANCE --side SHORT --entry 1190 --stop 1200 --tsl PSAR_0.04_0.04_0.10
        with a TSL instead of a fixed target
    python scripts\\time_machine.py --symbol RELIANCE --side LONG --entry 1190 --stop 1180 --source cache --day 2026-10-23 --at 10:00
        a past day from the downloaded research data (no login)
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from strategies.exit_plan import ExitPlan  # noqa: E402
from strategies.time_machine import summary  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def main(argv=None, *, client=None, candles=None) -> int:
    p = argparse.ArgumentParser(description="Time Machine: the chances of one trade idea.")
    p.add_argument("--symbol", required=True, help="stock, e.g. RELIANCE (or a full FYERS symbol)")
    p.add_argument("--side", choices=("LONG", "SHORT"), required=True)
    p.add_argument("--entry", type=float, required=True)
    p.add_argument("--stop", type=float, required=True)
    p.add_argument("--reward", default="2", help="Reward 1:[box] (default 2); empty with --tsl")
    p.add_argument("--tsl", default="NONE", help="a TSL preset, e.g. PSAR_0.04_0.04_0.10")
    p.add_argument("--source", choices=("fyers", "cache"), default="fyers")
    p.add_argument("--day", default=None, help="YYYY-MM-DD (default today)")
    p.add_argument("--at", default=None, help="entry time HH:MM (default now)")
    p.add_argument("--exit-time", default="15:10")
    p.add_argument("--replays", type=int, default=2000)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    args = p.parse_args(argv)

    now = datetime.now(IST)
    day = datetime.fromisoformat(args.day).date() if args.day else now.date()
    at = datetime.strptime(args.at, "%H:%M").time() if args.at else now.time().replace(second=0, microsecond=0)
    entry_ts = int(datetime.combine(day, at, tzinfo=IST).timestamp())
    stock = args.symbol.upper().replace("NSE:", "").replace("-EQ", "")
    plan = ExitPlan(target_rr=args.reward if args.tsl == "NONE" else (args.reward or None), tsl_method=args.tsl)
    start_of_day = int(datetime.combine(day, datetime.min.time(), tzinfo=IST).timestamp())
    if candles is None:
        if args.source == "cache":
            from market_data.research_store import ResearchStore
            store = ResearchStore(args.data_folder / "research" / "market_data.db")
            candles = store.load(f"STK_{stock}", "yahoo", "5m", clean_only=False) or \
                store.load(f"STK_{stock}", "yahoo", "1m", clean_only=False)
        else:
            if client is None:
                from api.fyers_client import FyersClient
                from scripts.run_paper_session import find_credentials_folder
                client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
            from datetime import timedelta
            from paper_trading.warmup import parse_history_candles
            sym = args.symbol if ":" in args.symbol else f"NSE:{stock}-EQ"
            candles = parse_history_candles(client.history(sym, resolution="5",
                                                           range_from=(day - timedelta(days=90)).isoformat(),
                                                           range_to=day.isoformat()))
    history = [c for c in candles if c.timestamp < start_of_day]
    today = [c for c in candles if start_of_day <= c.timestamp <= entry_ts]
    out = summary(symbol=stock, side=args.side, entry=args.entry, stop=args.stop, plan=plan, entry_ts=entry_ts,
                  history=history, today=today, exit_time=args.exit_time, replays=args.replays)
    if out is None:
        print("Not enough history (at least 20 earlier sessions of 5-minute candles), or the stop is on the wrong "
              "side of the entry.")
        return 1
    risk = abs(args.entry - args.stop)
    print(f"TIME MACHINE  {stock} {args.side} entry {args.entry:g} stop {args.stop:g} (risk {risk:g}) at "
          f"{at.strftime('%H:%M')} {day}, {out['replays']} replays from the last {out['sessions']} sessions")
    print(f"  your plan ({plan.describe()}): {out['text']}, stop first {out['stop_pct']:.0f}%, "
          f"average {out['avg_r']:+.2f}R")
    print("  chance of reaching the target before " + args.exit_time + ":")
    for k, v in out["ladder"].items():
        print(f"    {k:<6} {v['target_pct']:5.1f}%   (stop first {v['stop_pct']:.0f}%, neither by {args.exit_time} "
              f"{v['time_pct']:.0f}%)")
    print("  Information only: in our check the target chances ranked trades correctly but were cautious; the win "
          "chance did not predict winners.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
