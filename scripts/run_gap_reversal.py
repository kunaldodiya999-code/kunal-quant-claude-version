"""Gap Reversal live scanner + paper trading (no real orders). Run on trading days.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version (own window, after the FYERS login):

    python scripts\\run_gap_reversal.py

What it does:
  1. Logs in to FYERS (same login files as the paper session).
  2. Loads every F&O stock (+ NIFTY, BANK NIFTY, SENSEX when "include indexes" is on).
  3. At/after 09:16 reads each symbol's open and previous close (quotes) and keeps the ones that
     gapped by the set % (default 3%) up or down.
  4. Every minute downloads the gap symbols' 1-minute candles, marks every reversal setup with its
     strength %, and (only when the strategy is switched ON in the dashboard) paper-trades the first
     qualifying setup of each symbol: stop at the day's extreme, target 1:2 (setting), flat by 15:10.
  5. Writes data\\gap_reversal\\status.json for the dashboard page "Gap Reversal".
Read-only towards the broker: nothing is ordered.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo("Asia/Kolkata")


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def quote_levels(client, symbols: list[str]) -> dict:
    """{symbol: (prev_close, open)} from FYERS quotes, 50 symbols per request."""
    out = {}
    for i in range(0, len(symbols), 50):
        answer = client.quotes(symbols[i:i + 50])
        for item in (answer or {}).get("d") or []:
            v = item.get("v") or {}
            try:
                prev, opn = float(v.get("prev_close_price")), float(v.get("open_price"))
            except (TypeError, ValueError):
                continue
            if prev > 0 and opn > 0:
                out[item.get("n") or v.get("symbol")] = (prev, opn)
    return out


def today_minutes(client, symbol: str, now: datetime) -> list:
    """Today's FINISHED 1-minute candles (with volume) of one symbol."""
    from paper_trading.warmup import parse_history_candles
    day = now.date().isoformat()
    candles = parse_history_candles(client.history(symbol, resolution="1", range_from=day, range_to=day))
    cutoff = int(now.timestamp())
    return [c for c in candles if c.timestamp + 60 <= cutoff]


def earlier_minutes(client, symbol: str, now: datetime, days: int = 7) -> list:
    """1-minute candles of the last few sessions before today (TSL warm-up)."""
    from paper_trading.warmup import parse_history_candles
    from datetime import timedelta
    start, end = (now.date() - timedelta(days=days)).isoformat(), (now.date() - timedelta(days=1)).isoformat()
    return parse_history_candles(client.history(symbol, resolution="1", range_from=start, range_to=end))


def main(argv=None, *, client=None, clock=None, sleep=time.sleep, master=None) -> int:
    p = argparse.ArgumentParser(description="Gap Reversal live scanner + paper trading.")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--stop-at", default="15:35")
    p.add_argument("--every", type=float, default=30.0, help="seconds between scans")
    p.add_argument("--no-odds", action="store_true", help="do not work out the Time Machine odds of each trade")
    args = p.parse_args(argv)
    clock = clock or (lambda: datetime.now(IST))

    from market_data.stock_universe import load_fno_stocks
    from paper_trading.gap_reversal_paper import GapReversalDesk
    from strategies.gap_reversal import GapReversalStore
    from strategies.index_profiles import INDEX_PROFILES

    folder = args.data_folder / "gap_reversal"
    settings = GapReversalStore(folder).settings
    if client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    stocks = load_fno_stocks(args.data_folder, today=clock().date(), fetch=(lambda url: master) if master else None)
    symbols = [s["symbol"] for s in stocks]
    if settings.include_indexes:
        symbols += [prof.spot_symbol for prof in INDEX_PROFILES.values()]
    say(f"GAP REVERSAL: {len(symbols)} symbols, gap >= {settings.gap_pct}%, {settings.timeframe}-min candles, "
        f"setups in the first {settings.window_bars()} candles. Paper trades: "
        f"{'ON' if settings.enabled else 'OFF (marking setups only; switch ON in the dashboard)'}")
    from paper_trading.time_machine_feed import fyers_odds_history
    desk = GapReversalDesk(folder, settings,
                           odds_history=None if args.no_odds else fyers_odds_history(client, clock().date()))

    while clock().time() < dtime(9, 16):
        say("Waiting for 09:16 (the first candle must be known)...")
        sleep(30)
    levels = quote_levels(client, symbols)
    for symbol, (prev, opn) in levels.items():
        desk.set_gap(symbol, prev, opn)
    say(f"Gaps of {settings.gap_pct}% or more: " + (", ".join(f"{k} {v['gap_pct']:+.2f}%" for k, v in desk.gaps.items())
                                                   or "none today"))
    if settings.short.exit_plan().uses_tsl or settings.long.exit_plan().uses_tsl:
        for symbol in desk.gaps:                            # TSL warm-up on the previous days (once)
            try:
                desk.set_history(symbol, earlier_minutes(client, symbol, clock()))
            except Exception as exc:
                say(f"{symbol}: no earlier candles for the TSL warm-up ({exc})")
    stop_at = dtime.fromisoformat(args.stop_at)
    seen_minute = None
    while True:
        now = clock()
        if now.time() >= stop_at:
            say(f"Reached {args.stop_at}. Stopping.")
            break
        minute = now.replace(second=0, microsecond=0)
        if minute != seen_minute:
            seen_minute = minute
            for symbol in list(desk.gaps):
                try:
                    desk.on_minutes(symbol, today_minutes(client, symbol, now), int(now.timestamp()))
                except Exception as exc:                 # one symbol must not stop the scanner
                    say(f"{symbol}: not updated ({exc})")
            status = desk.write_status(int(now.timestamp()))
            new = [c for c in status["candidates"] if c["qualifies"]]
            if new:
                say("Setups: " + "; ".join(f"{c['symbol']} {c['side']} {c['time']} {c['strength']}% ({c['setups']})"
                                           for c in new[:5]))
            for t in status["trades"]:
                say(f"PAPER {t['symbol']} {t['side']} {t['status']} entry {t['entry']} stop {t['stop']} "
                    f"target {t['target'] or 'TSL'} P&L {t['pnl']}"
                    + (f" (time machine {t['time_machine']})" if t.get("time_machine") else ""))
            if status.get("skipped"):
                cap = status["daily_cap"]
                say(f"Daily cap full ({cap['taken']} of {cap['max_trades'] or 'no limit'}): skipped "
                    + ", ".join(r["symbol"] for r in status["skipped"]))
        sleep(args.every)
    desk.write_status(int(clock().timestamp()))
    say(f"Saved in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
