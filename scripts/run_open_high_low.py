"""Open High Low (OHOL) scanner + paper trading for F&O stocks (no real orders). Run when you want it.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version (own window, after the FYERS login):

    python scripts\\run_open_high_low.py
        waits for the first 5-minute candle to close (09:20), scans once, shortlists the top 5, enters each one
        when the next candle breaks the first candle's high (long) / low (short), follows them to 15:10
    python scripts\\run_open_high_low.py --scan-only
        scan now (or at the scan time), show the list, no trades, stop

What it does:
  1. Loads every F&O stock from FYERS' contract list.
  2. Quotes of every stock (spot) and its current-month future: open, high, low, price, volume.
     A stock where spot OR futures shows OPEN = LOW (long) or OPEN = HIGH (short) is a candidate.
  3. For candidates: (setting "Both must agree": the other chart must agree too), then quotes of the 11 strikes (ATM, 5 ITM, 5 OTM)
     of the nearest expiry, calls and puts: how many options show the same picture (calls open = low and
     puts open = high for a LONG; the opposite for a SHORT). Liquidity: futures traded value, ATM spread.
  4. The best 5 (most matches: spot + future + calls + puts, then liquidity) are shortlisted when the strategy is ON (dashboard); each one is
     entered when the next candle crosses the first candle's high (LONG) / low (SHORT); none if it does not.
  5. Every minute: the trades' 1-minute candles, stop / target / TSL, status for the dashboard page
     "Open High Low" (data\\open_high_low\\status.json).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo("Asia/Kolkata")


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def get_quotes(client, symbols: list[str], pause: float = 0.12) -> dict:
    """{symbol: Quote} from FYERS quotes, 50 symbols per request."""
    from strategies.open_high_low import Quote
    out = {}
    for i in range(0, len(symbols), 50):
        answer = client.quotes(symbols[i:i + 50])
        for item in (answer or {}).get("d") or []:
            v = item.get("v") or {}
            try:
                q = Quote(item.get("n") or v.get("symbol"), float(v.get("open_price") or 0),
                          float(v.get("high_price") or 0), float(v.get("low_price") or 0), float(v.get("lp") or 0),
                          float(v.get("volume") or 0), float(v.get("bid") or 0), float(v.get("ask") or 0))
            except (TypeError, ValueError):
                continue
            out[q.symbol] = q
        if pause and i + 50 < len(symbols):
            time.sleep(pause)
    return out


def today_minutes(client, symbol: str, now: datetime, days_back: int = 0) -> list:
    """Finished 1-minute candles of today (and ``days_back`` earlier days)."""
    from paper_trading.warmup import parse_history_candles
    start = (now.date() - timedelta(days=days_back)).isoformat()
    candles = parse_history_candles(client.history(symbol, resolution="1", range_from=start,
                                                   range_to=now.date().isoformat()))
    cutoff = int(now.timestamp())
    return [c for c in candles if c.timestamp + 60 <= cutoff]


def scan(client, master: dict, settings, today, *, pause: float = 0.12) -> tuple[list, dict, dict]:
    """Every F&O stock -> candidates (strategies.open_high_low.Candidate), plus symbols and lot sizes."""
    from market_data.sources.fyers_history import nearest_future
    from market_data.stock_universe import fno_stocks
    from strategies.open_high_low import evaluate, option_strikes, side_of
    stocks = fno_stocks(master)
    symbols = {s["stock"]: {"spot": s["symbol"], "future": nearest_future(master, s["stock"], today)} for s in stocks}
    lots = {s["stock"]: s["lot_size"] for s in stocks}
    spot_q = get_quotes(client, [v["spot"] for v in symbols.values()], pause)
    fut_q = get_quotes(client, [v["future"] for v in symbols.values() if v["future"]], pause)
    candidates, ladders = [], {}
    for stock, names in symbols.items():
        spot, fut = spot_q.get(names["spot"]), fut_q.get(names["future"])
        if side_of(spot, settings.tolerance_pct) is None and side_of(fut, settings.tolerance_pct) is None:
            continue
        price = (spot or fut).ltp
        _expiry, ladder = option_strikes(master, stock, price, today, settings.strikes_each_side,
                                         settings.min_days_to_expiry)
        ladders[stock] = ladder
    option_q = get_quotes(client, [sym for ladder in ladders.values() for _, ce, pe in ladder for sym in (ce, pe)],
                          pause)
    for stock, ladder in ladders.items():
        names = symbols[stock]
        spot, fut = spot_q.get(names["spot"]), fut_q.get(names["future"])
        price = (spot or fut).ltp
        atm = min(ladder, key=lambda r: (abs(r[0] - price), r[0])) if ladder else None
        options = [(k, option_q.get(ce), option_q.get(pe)) for k, ce, pe in ladder]
        candidates.append(evaluate(stock, spot, fut, options, settings, atm_strike=atm[0] if atm else None,
                                   atm_symbols=(atm[1], atm[2]) if atm else (None, None)))
    return candidates, symbols, lots


def main(argv=None, *, client=None, clock=None, sleep=time.sleep, master=None) -> int:
    p = argparse.ArgumentParser(description="Open High Low scanner + paper trading.")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data")
    p.add_argument("--credentials-folder", type=Path, default=None)
    p.add_argument("--stop-at", default="15:35")
    p.add_argument("--every", type=float, default=30.0, help="seconds between trade updates")
    p.add_argument("--scan-only", action="store_true", help="scan, show the list, no trades, stop")
    p.add_argument("--no-odds", action="store_true", help="do not work out the Time Machine odds of the shortlist")
    args = p.parse_args(argv)
    clock = clock or (lambda: datetime.now(IST))

    from paper_trading.live_support import load_fyers_master
    from paper_trading.open_high_low_paper import OpenHighLowDesk
    from strategies.open_high_low import OpenHighLowStore

    folder = args.data_folder / "open_high_low"
    settings = OpenHighLowStore(folder).settings
    if args.scan_only:
        from dataclasses import replace
        settings = replace(settings, enabled=False)
    if client is None:
        from api.fyers_client import FyersClient
        from scripts.run_paper_session import find_credentials_folder
        client = FyersClient(project_root=find_credentials_folder(args.credentials_folder))
    today = clock().date()
    if master is None:
        master = load_fyers_master("NSE_FO", args.data_folder / "raw" / "fyers", today=today)
    say(f"OPEN HIGH LOW: scan at {settings.scan_at}, confirm {settings.confirm}, {2 * settings.strikes_each_side + 1} "
        f"strikes, top {settings.top_n}, instrument {settings.instrument}. Paper trades: "
        f"{'ON' if settings.enabled else 'OFF (scan only; switch ON in the dashboard)'}")
    from paper_trading.time_machine_feed import fyers_odds_history
    desk = OpenHighLowDesk(folder, settings, odds_history=None if args.no_odds else fyers_odds_history(client, today))
    scan_time = dtime.fromisoformat(settings.scan_at)
    while clock().time() < scan_time:
        say(f"Waiting for {settings.scan_at} ...")
        sleep(30)
    candidates, symbols, lots = scan(client, master, settings, today, pause=0.0 if sleep is not time.sleep else 0.12)
    top = desk.scan(candidates, int(clock().timestamp()), symbols=symbols, lot_sizes=lots)
    status = desk.write_status(int(clock().timestamp()))
    sides = [c for c in candidates if c.side]
    say(f"Open = high / low in {len(sides)} stocks; {sum(c.passes for c in sides)} pass every check.")
    for c in top:
        say(f"TOP {c.stock} {c.side} matches {c.matches}/{c.matches_possible} (spot {'yes' if c.spot_ok else 'no'}, "
            f"future {'yes' if c.fut_ok else 'no'}, calls {c.call_matches}, puts {c.put_matches}) futures Rs {c.fut_value_cr:.1f} cr "
            f"ATM spread {c.atm_spread_pct if c.atm_spread_pct is None else round(c.atm_spread_pct, 2)}%"
            + (f"; time machine {desk.odds[c.stock]['text']}" if desk.odds.get(c.stock) else ""))
    if args.scan_only or not desk.trades:
        say("No paper trades." if not args.scan_only else "Scan only: done.")
        say(f"Saved in {folder}")
        return 0
    say("Shortlist (waiting for the breakout of the first candle): " + ", ".join(
        f"{t['stock']} {t['side']}" for t in status["trades"]))
    entered = set()
    stop_at = dtime.fromisoformat(args.stop_at)
    seen = None
    while clock().time() < stop_at:
        now = clock()
        minute = now.replace(second=0, microsecond=0)
        if minute != seen:
            seen = minute
            for stock, t in list(desk.trades.items()):
                try:
                    chart = today_minutes(client, t["chart"], now)
                    opt = today_minutes(client, t["symbol"], now) if t["instrument"] == "OPTION" else ()
                    desk.on_minutes(stock, chart, int(now.timestamp()), option_minutes=opt)
                except Exception as exc:              # one symbol must not stop the program
                    say(f"{stock}: not updated ({exc})")
            status = desk.write_status(int(now.timestamp()))
            for t in status["trades"]:
                if t["entry_epoch"] and t["stock"] not in entered:
                    entered.add(t["stock"])
                    say(f"PAPER {t['action']} {t['symbol']} qty {t['quantity']} at {t['entry']} "
                        f"(broke {t['trigger']}, stop {t['stop']})")
            states = [t["status"] for t in status["trades"]]
            say(f"Waiting {states.count('WAITING')}, open {states.count('OPEN')}, done "
                f"{len(states) - states.count('WAITING') - states.count('OPEN')}; paper P&L Rs {status['day_pnl']:,.0f}")
        sleep(args.every)
    desk.write_status(int(clock().timestamp()))
    say(f"Saved in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
