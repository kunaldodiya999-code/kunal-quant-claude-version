"""TSL checker: every trailing-stop indicator value for one day, to compare with TradingView.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version :

    python scripts\\tsl_check.py --date 2026-10-23 --timeframe 3
        (NIFTY 50 spot chart, uses FYERS history: needs today's FYERS login)
    python scripts\\tsl_check.py --date 2026-10-23 --timeframe 3 --symbol NSE:NIFTY26O2722000CE
        (an option chart: any FYERS symbol)
    python scripts\\tsl_check.py --date 2026-10-23 --timeframe 5 --database C:\\Users\\USER\\Desktop\\Kunal\\KunalQuant\\data\\database\\kunal_quant.db
        (your local price database, no login)

In TradingView open the same chart and timeframe and add: "Chandelier Exit" by everget
(ATR Period 9, ATR Multiplier 1.5, Use Close Price for Extremums ON), Supertrend (ATR 5 / factor 1
and ATR 7 / factor 1.5) and Parabolic SAR (0.02/0.02/0.2 and 0.04/0.04/0.1). Compare the Data Window
with the printed table. The numbers come from data\\paper_trading\\<INDEX>\\trade_management.json.
Read-only; saves the table as a CSV for Excel.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import date, datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from paper_trading.trade_management import TradeManagementStore, session_bars  # noqa: E402
from paper_trading.tsl_methods import chandelier, psar, supertrend  # noqa: E402
from paper_trading.warmup import fetch_minute_history  # noqa: E402
from scripts.ktmi_check import load_from_database  # noqa: E402
from strategies.index_profiles import get_profile  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def check_day(minutes, day: date, timeframe: int, params: dict) -> list[dict]:
    bars = session_bars(minutes, timeframe)
    ch = params["CHANDELIER_9_1.5"]
    ch_long, ch_short, ch_dir = chandelier(bars, int(ch["length"]), float(ch["mult"]), bool(ch["use_close"]))
    columns = {"chandelier_long_stop": ch_long, "chandelier_short_stop": ch_short,
               "chandelier_direction": ["Up" if d == 1 else "Down" for d in ch_dir]}
    for key in ("SUPERTREND_5_1.0", "SUPERTREND_7_1.5"):
        p = params[key]
        st, dirs, _, _ = supertrend(bars, int(p["atr_length"]), float(p["factor"]))
        name = f"supertrend_{p['atr_length']}_{p['factor']}"
        columns[name] = st
        columns[name + "_direction"] = [None if d is None else ("Up" if d == -1 else "Down") for d in dirs]
    for key in ("PSAR_0.02_0.02_0.20", "PSAR_0.04_0.04_0.10"):
        p = params[key]
        sars, _ = psar(bars, float(p["start"]), float(p["increment"]), float(p["maximum"]))
        columns[f"psar_{p['start']}_{p['increment']}_{p['maximum']}"] = sars
    rows = []
    for i, bar in enumerate(bars):
        if datetime.fromtimestamp(bar.timestamp, IST).date() != day:
            continue
        row = {"candle_time": datetime.fromtimestamp(bar.timestamp, IST).strftime("%Y-%m-%d %H:%M"),
               "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close}
        for name, values in columns.items():
            v = values[i]
            row[name] = round(v, 2) if isinstance(v, float) else ("" if v is None else v)
        rows.append(row)
    return rows


def main(argv=None, *, client=None) -> int:
    p = argparse.ArgumentParser(description="Trailing-stop indicator values for one day.")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--index", default="NIFTY", help="NIFTY, BANKNIFTY or SENSEX (settings and default chart)")
    p.add_argument("--symbol", default=None, help="any FYERS symbol (default: the index spot)")
    p.add_argument("--timeframe", type=int, default=3, choices=(1, 3, 5, 10, 15, 30, 60))
    p.add_argument("--database", type=Path, default=None, help="use a local price database instead of FYERS")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "tsl_check")
    args = p.parse_args(argv)
    try:
        profile = get_profile(args.index)
    except ValueError as exc:
        raise SystemExit(str(exc))
    symbol = args.symbol or profile.spot_symbol
    day = date.fromisoformat(args.date)
    end = datetime.combine(day, dtime(15, 31), tzinfo=IST)
    if args.database is not None:
        if not args.database.exists():
            raise SystemExit(f"Database not found: {args.database}")
        start = datetime.combine(day, dtime(0, 0), tzinfo=IST).timestamp() - 10 * 86400
        minutes = load_from_database(args.database, int(start), int(end.timestamp()), symbol)
    else:
        if client is None:
            from api.fyers_client import FyersClient
            from scripts.run_paper_session import find_credentials_folder
            client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
        minutes = fetch_minute_history(client, symbol, resolution_minutes=args.timeframe, now=end)
    params = TradeManagementStore(args.data_folder / "paper_trading" / profile.key).settings.method_params
    rows = check_day(minutes, day, args.timeframe, params)
    if not rows:
        raise SystemExit(f"No candles for {symbol} on {day} (holiday, weekend, or data missing).")
    print("=" * 112)
    print(f"TSL CHECK - {symbol} - {day:%a %d %b %Y} - {args.timeframe}-minute candles (compare with TradingView)")
    print("=" * 112)
    print(f"{'Candle':<7}{'Close':>10}{'Chand.L':>10}{'Chand.S':>10}{'ST 5/1':>10}{'':>5}{'ST 7/1.5':>10}{'':>5}"
          f"{'PSAR A':>10}{'PSAR B':>10}")
    keys = list(rows[0])
    st_a, st_b, ps_a, ps_b = keys[8], keys[10], keys[12], keys[13]
    for r in rows:
        def cell(v, w=10):
            return f"{v:>{w}}" if v != "" else " " * (w - 1) + "-"
        print(f"{r['candle_time'][-5:]:<7}{r['close']:>10.2f}{cell(r['chandelier_long_stop'])}{cell(r['chandelier_short_stop'])}"
              f"{cell(r[st_a])}{cell(r[keys[9]], 5)}{cell(r[st_b])}{cell(r[keys[11]], 5)}{cell(r[ps_a])}{cell(r[ps_b])}")
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"tsl_{symbol.replace(':', '_')}_{day.isoformat()}_{args.timeframe}m.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved for Excel: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
