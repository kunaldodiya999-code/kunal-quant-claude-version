"""KTMI Uni Lite checker: values and arrows for any past day, to compare with TradingView.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\ktmi_check.py --date 2026-10-23 --timeframe 3
        (uses FYERS history: needs today's FYERS login)

    python scripts\\ktmi_check.py --date 2026-10-23 --timeframe 3 --database C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db
        (uses your local price database instead, no login needed)

Prints every candle of that day with Long/Short Speed and Signal and the
arrows (BUY CALL / BUY PUT) exactly as the paper engine computes them, and
saves the same table as a CSV you can open in Excel. Read-only.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from indicators.ktmi.universal import OHLCData  # noqa: E402
from indicators.ktmi_uni_lite import UNI_LITE_CORE, calculate_uni_lite  # noqa: E402
from market_data.resampling import Candle, aggregate_day  # noqa: E402
from paper_trading.ktmi_journal import KTMI_BAR_FIELDS, ktmi_row  # noqa: E402
from paper_trading.market_data_pipeline import SUPPORTED_RESOLUTIONS, bar_close_timestamp  # noqa: E402
from paper_trading.warmup import fetch_minute_history, warmup_calendar_days  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
SYMBOL = "NSE:NIFTY50-INDEX"


def load_from_database(path: Path, start_ts: int, end_ts: int) -> list[Candle]:
    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT c.timestamp, c.open, c.high, c.low, c.close
            FROM candles c JOIN instruments i ON i.id = c.instrument_id
            WHERE i.symbol = ? AND c.resolution = '1' AND c.timestamp BETWEEN ? AND ?
            GROUP BY c.timestamp ORDER BY c.timestamp
            """,
            (SYMBOL, start_ts, end_ts),
        ).fetchall()
    return [Candle(int(t), float(o), float(h), float(l), float(c)) for t, o, h, l, c in rows]


def signal_bars(minutes: list[Candle], timeframe: int) -> list:
    if timeframe == 1:
        return minutes
    by_day: dict = {}
    for candle in minutes:
        by_day.setdefault(datetime.fromtimestamp(candle.timestamp, IST).date(), []).append(candle)
    return [bar for day in sorted(by_day) for bar in aggregate_day(by_day[day], timeframe) if bar.complete]


def check_day(minutes: list[Candle], day: date, timeframe: int) -> list[dict]:
    bars = signal_bars(minutes, timeframe)
    values = calculate_uni_lite([OHLCData(b.open, b.high, b.low, b.close) for b in bars], UNI_LITE_CORE)
    rows = []
    for bar, value in zip(bars, values):
        if datetime.fromtimestamp(bar.timestamp, IST).date() == day:
            row = ktmi_row(bar, value, timeframe_minutes=timeframe, symbol=SYMBOL)
            row["candle_closes"] = datetime.fromtimestamp(bar_close_timestamp(bar.timestamp, timeframe), IST).strftime("%H:%M")
            rows.append(row)
    return rows


def _f(value, width=8):
    return f"{value:>{width}}" if value != "" else " " * (width - 1) + "-"


def print_table(rows: list[dict], day: date, timeframe: int, history_bars: int) -> None:
    print("=" * 96)
    print(f"KTMI UNI LITE CHECK - NIFTY 50 - {day:%a %d %b %Y} - {timeframe}-minute candles")
    print(f"(warm-up: {history_bars} earlier candles; compare with TradingView Data Window, same timeframe)")
    print("=" * 96)
    print(f"{'Candle':<7}{'Close':>10}{'LongSpd':>9}{'LongSig':>9}{'ShortSpd':>10}{'ShortSig':>10}   Arrow  (entry at candle close)")
    for r in rows:
        arrow = " ".join(a for a in (r["long_buy"], r["short_buy"]) if a)
        print(f"{r['candle_time'][-5:]:<7}{r['close']:>10.2f}{_f(r['long_speed'], 9)}{_f(r['long_signal'], 9)}"
              f"{_f(r['short_speed'], 10)}{_f(r['short_signal'], 10)}   {arrow + ('  @ ' + r['candle_closes'] if arrow else '')}")
    arrows = [r for r in rows if r["long_buy"] or r["short_buy"]]
    print("-" * 96)
    print(f"Arrows today: {len(arrows)}  ->  " + (", ".join(
        f"{r['candle_time'][-5:]} {'CALL' if r['long_buy'] else 'PUT'}" for r in arrows) or "none"))
    print("=" * 96)


def main(argv=None, *, client=None) -> int:
    p = argparse.ArgumentParser(description="KTMI Uni Lite values and arrows for one day.")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--timeframe", type=int, default=3, choices=SUPPORTED_RESOLUTIONS)
    p.add_argument("--database", type=Path, default=None, help="use a local price database instead of FYERS")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "ktmi_check")
    args = p.parse_args(argv)

    day = date.fromisoformat(args.date)
    end = datetime.combine(day, dtime(15, 31), tzinfo=IST)
    if args.database is not None:
        if not args.database.exists():
            raise SystemExit(f"Database not found: {args.database}")
        start = datetime.combine(day, dtime(0, 0), tzinfo=IST).timestamp() - warmup_calendar_days(args.timeframe) * 86400
        minutes = load_from_database(args.database, int(start), int(end.timestamp()))
    else:
        if client is None:
            from api.fyers_client import FyersClient
            from scripts.run_paper_session import find_credentials_folder
            client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
        minutes = fetch_minute_history(client, SYMBOL, resolution_minutes=args.timeframe, now=end)

    rows = check_day(minutes, day, args.timeframe)
    if not rows:
        raise SystemExit(f"No NIFTY candles found for {day} (holiday, weekend, or data missing).")
    print_table(rows, day, args.timeframe, len(signal_bars(minutes, args.timeframe)) - len(rows))

    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"ktmi_{day.isoformat()}_{args.timeframe}m.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*KTMI_BAR_FIELDS, "candle_closes"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved for Excel: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
