"""Run one live PAPER trading day on real FYERS market data.

PAPER MODE: prices are real, trades are simulated. No order is ever sent to
the broker by this program.

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version (after
logging in to FYERS for the day):

    python scripts\\run_paper_session.py

What it does, in order:
  1. Checks your FYERS login (today's access token).
  2. Loads today's NIFTY option contracts and lot size from FYERS.
  3. Reads your settings (timeframe, Long/Short/Both, times, strikes).
  4. Loads earlier candles so KTMI matches your TradingView chart.
  5. Streams live prices; takes paper trades on KTMI Uni Lite signals.
  6. Closes open paper trades at the force-exit time; stops after the market.

Leave the window open all day. Press Ctrl+C to stop early (open paper trades
are kept in the journal and restored next time).
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

IST = ZoneInfo("Asia/Kolkata")
UNDERLYING = "NSE:NIFTY50-INDEX"


def find_credentials_folder(explicit: Path | None) -> Path:
    """Folder holding .env (FYERS_CLIENT_ID) and fyers_access_token.txt."""
    candidates = [explicit] if explicit else [PROJECT_ROOT, PROJECT_ROOT.parent / "KunalQuant"]
    for folder in candidates:
        if folder and (folder / ".env").exists() and (folder / "fyers_access_token.txt").exists():
            return folder
    looked = ", ".join(str(c) for c in candidates if c)
    raise SystemExit(
        "FYERS login files not found (.env and fyers_access_token.txt).\n"
        f"Looked in: {looked}\n"
        "Log in first: in the folder that has your .env file run   python fyers_auth.py"
    )


def say(text: str) -> None:
    print(f"[{datetime.now(IST):%H:%M:%S}] {text}", flush=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Live PAPER trading day on FYERS data (no real orders).")
    p.add_argument("--credentials-folder", type=Path, default=None,
                   help="folder with .env and fyers_access_token.txt (auto-detected)")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data",
                   help="where journals, settings and the contracts database live")
    p.add_argument("--stop-at", default="15:35", help="stop the program at this IST time (HH:MM)")
    p.add_argument("--status-every", type=float, default=2.0, help="seconds between dashboard updates")
    return p


def main(argv=None, *, client=None, raw_master=None, socket_factory=None, clock=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    clock = clock or (lambda: datetime.now(IST))
    OUTPUT_DIR = args.data_folder / "paper_trading"
    CONTRACTS_DB = args.data_folder / "database" / "paper_contracts.db"

    from instruments.symbol_master import download_symbol_master
    from paper_trading.live_support import build_status, sync_nifty_option_contracts, write_status
    from paper_trading.session import PaperSessionConfig, build_paper_session
    from paper_trading.strategy_settings import StrategySettings, StrategySettingsStore
    from paper_trading.warmup import fetch_minute_history

    print("=" * 72)
    print("KUNAL QUANT - LIVE PAPER TRADING  (real prices, simulated trades, NO real orders)")
    print("=" * 72)

    # 1. Login
    if client is None:
        from api.fyers_client import FyersClient
        folder = find_credentials_folder(args.credentials_folder)
        say(f"Using FYERS login from {folder}")
        client = FyersClient(project_root=folder)
        try:
            profile = client.profile()
        except Exception as exc:   # expired token is the common case
            raise SystemExit(f"FYERS login failed ({exc}). Run  python fyers_auth.py  again, then retry.")
        name = (profile.get("data") or {}).get("name") if isinstance(profile, dict) else None
        say(f"FYERS login OK{f' ({name})' if name else ''}")

    # 2. Contracts
    today = clock().date()
    if raw_master is None:
        raw_master = download_symbol_master(force_refresh=True)
    contracts = sync_nifty_option_contracts(CONTRACTS_DB, raw_master, today=today)
    say(f"NIFTY options loaded: {contracts.contracts} contracts, nearest expiry "
        f"{contracts.nearest_expiry:%a %d %b %Y}, lot size {contracts.lot_size}")

    # 3. Settings
    settings = StrategySettingsStore(StrategySettings(), OUTPUT_DIR).settings
    say(f"Settings: {settings.timeframe_minutes}-min candles, direction {settings.trade_direction}, "
        f"entries {settings.entry_start}-{settings.entry_end}, force exit {settings.force_exit}")
    strike_text = ("ATM" if settings.use_atm else "") + (" + ATM+1" if settings.use_atm_plus_1 else "")
    say("Strikes: " + (strike_text.strip(" +") if strike_text else
                       f"CALL {settings.call_strike}, PUT {settings.put_strike} (dropdowns)"))

    session = build_paper_session(
        client=client,
        config=PaperSessionConfig(
            lot_size=contracts.lot_size,
            resolution_minutes=settings.timeframe_minutes,
            database_path=CONTRACTS_DB,
            output_dir=OUTPUT_DIR,
            pending_journal_path=OUTPUT_DIR / "pending_entries.csv",
            underlying_symbol=UNDERLYING,
        ),
        socket_factory=socket_factory,
    )
    if session.recovery is not None and session.recovery.open_trade_ids:
        say(f"Restored open paper trades from the journal: {', '.join(session.recovery.open_trade_ids)}")
        if session.recovery.stale_open_trade_ids:
            say("WARNING: some restored trades were opened on an EARLIER day: "
                f"{', '.join(session.recovery.stale_open_trade_ids)}. Check rejections/exit files.")

    # 4. Warm-up
    history = fetch_minute_history(client, UNDERLYING, resolution_minutes=settings.timeframe_minutes, now=clock())
    bars = session.pipeline.seed_history(UNDERLYING, history)
    say(f"Warm-up: {len(history)} one-minute candles -> {bars} {settings.timeframe_minutes}-min bars of history")

    # 5. Live
    stop_at = dtime.fromisoformat(args.stop_at)
    threading.Thread(target=session.start, name="fyers-feed", daemon=True).start()
    say("Connecting to FYERS live data... (Ctrl+C to stop)")
    last_status = 0.0
    reported_error = None
    try:
        while True:
            now = clock()
            if now.time() >= stop_at:
                say(f"Reached {args.stop_at}. Stopping.")
                break
            stamp = int(now.timestamp())
            if session.controls.exits_due(stamp):
                result = session.controls.close_due_positions(
                    session.engine, timestamp=stamp, prices=session.coordinator.marks_provider())
                for strategy, exit_event in result.closed:
                    say(f"FORCE EXIT {strategy.value} at {getattr(exit_event, 'price', '?')}")
            if time.monotonic() - last_status >= args.status_every:
                status = build_status(session, underlying_symbol=UNDERLYING, contracts=contracts,
                                      now=now.timestamp())
                write_status(OUTPUT_DIR, status)
                error = status["feed"]["last_error"]
                if error and error != reported_error:
                    say(f"FEED MESSAGE: {error}")
                    reported_error = error
                last_status = time.monotonic()
            sleep(1)
    except KeyboardInterrupt:
        say("Stopped by you (Ctrl+C).")
    finally:
        write_status(OUTPUT_DIR, build_status(session, underlying_symbol=UNDERLYING, contracts=contracts))
        session.close()
        say(f"Journals and status saved in {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
