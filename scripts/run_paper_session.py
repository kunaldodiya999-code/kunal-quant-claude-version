"""Run one live PAPER trading day on real FYERS market data.

PAPER MODE: prices are real, trades are simulated. Broker orders are a DRY
RUN (listed, never sent) unless you arm the live switch for today AND start
with --live-orders (see docs/LIVE_ORDERS.md).

Run from C:\\Users\\USER\\Desktop\\Kunal\\kunal-quant-claude-version (after
logging in to FYERS for the day):

    python scripts\\run_paper_session.py                      (NIFTY, BANK NIFTY and SENSEX)
    python scripts\\run_paper_session.py --index NIFTY        (one index only)

What it does, in order:
  1. Checks your FYERS login (today's access token).
  2. Loads today's option contracts and lot size of each index from FYERS.
  3. Reads each index's settings (timeframe, Long/Short/Both, times, strikes).
  4. Loads earlier candles so KTMI matches your TradingView chart.
  5. Saves chart data: futures volume (the index has none), daily candles, option-chain OI.
  6. Streams live prices (one FYERS connection); paper trades on KTMI Uni Lite.
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
    p.add_argument("--index", default="NIFTY,BANKNIFTY,SENSEX",
                   help="which indexes to trade, comma separated (NIFTY, BANKNIFTY, SENSEX)")
    p.add_argument("--credentials-folder", type=Path, default=None,
                   help="folder with .env and fyers_access_token.txt (auto-detected)")
    p.add_argument("--data-folder", type=Path, default=PROJECT_ROOT / "data",
                   help="where journals, settings and the contracts database live")
    p.add_argument("--live-orders", action="store_true",
                   help="send REAL orders to FYERS (also needs: python scripts\\live_switch.py arm)")
    p.add_argument("--stop-at", default="15:35", help="stop the program at this IST time (HH:MM)")
    p.add_argument("--status-every", type=float, default=2.0, help="seconds between dashboard updates")
    return p


class IndexDesk:
    """Everything for one index: session, contracts, paper folder and broker-order mirror."""

    def __init__(self, profile, session, contracts, paper_dir, gateway, mirror) -> None:
        self.profile, self.session, self.contracts = profile, session, contracts
        self.paper_dir, self.gateway, self.mirror = paper_dir, gateway, mirror
        self.reported_error = None
        self.last_silence_warning = 0.0
        self.futures = None          # FuturesMinuteRecorder (chart volume), when the future is known
        self.last_oi = 0.0           # monotonic time of the last option-chain refresh
        self.oi_error = None

    def silence_seconds(self, now: datetime) -> float | None:
        """Seconds since the last index price arrived, during market hours only."""
        if now.weekday() >= 5 or not (dtime(9, 16) <= now.time() <= dtime(15, 29)):
            return None
        snap = self.session.quote_cache.snapshot(self.profile.spot_symbol)
        return float("inf") if snap is None else now.timestamp() - snap.received_at

    def status(self, now: float | None = None) -> dict:
        from paper_trading.live_support import build_status
        status = build_status(self.session, underlying_symbol=self.profile.spot_symbol,
                              contracts=self.contracts, strike_step=self.profile.strike_step, now=now)
        status["index"] = self.profile.key
        status["index_label"] = self.profile.label
        status["orders_mode"] = self.gateway.mode
        return status


def main(argv=None, *, client=None, raw_master=None, socket_factory=None, clock=None, sleep=time.sleep) -> int:
    args = build_parser().parse_args(argv)
    clock = clock or (lambda: datetime.now(IST))
    from strategies.registry import DeploymentStore
    if not DeploymentStore(args.data_folder).is_deployed("KTMI_UNI_LITE"):
        print("KTMI Uni Lite is NOT deployed (dashboard page 'Strategies'). Nothing to do. To deploy it:\n"
              "    python scripts\\run_strategies.py --deploy KTMI_UNI_LITE   (add ,GAP_REVERSAL for both)")
        return 0

    from paper_trading.chart_feeds import FuturesMinuteRecorder, save_daily_candles, save_option_chain
    from market_data.sources.fyers_history import nearest_future
    from paper_trading.live_support import load_fyers_master, sync_option_contracts, write_status
    from paper_trading.session import PaperSessionConfig, build_paper_session
    from paper_trading.shared_socket import SharedSocketHub
    from paper_trading.strategy_settings import SETTINGS_FILE, StrategySettings, StrategySettingsStore
    from paper_trading.warmup import fetch_minute_history
    from live_trading.executor import LimitOrderExecutor
    from live_trading.gateway import DryRunGateway, FyersOrderGateway
    from live_trading.mirror import MirroringRecorder, LiveOrderMirror
    from live_trading.orders import LiveOrderPolicy
    from live_trading.switch import LiveSwitch
    from strategies.index_profiles import parse_index_list
    from strategies.option_contract_resolver import OptionContractResolver
    from strategies.strike_ladder import StrikeLadderResolver

    try:
        profiles = parse_index_list(args.index)
    except ValueError as exc:
        raise SystemExit(str(exc))

    print("=" * 72)
    print("KUNAL QUANT - LIVE PAPER TRADING  (real prices, simulated trades)")
    print("Indexes: " + ", ".join(p.label for p in profiles))
    print("=" * 72)

    # 1. Login (one login for all indexes)
    if client is None:
        from api.fyers_client import FyersClient
        folder = find_credentials_folder(args.credentials_folder)
        say(f"Using FYERS login from {folder}")
        client = FyersClient(project_root=folder)
        try:
            profile = client.profile()
        except Exception as exc:   # expired token is the common case
            raise SystemExit(f"FYERS login failed ({exc}). Run  python fyers_auth.py  again, then retry.")
        if not (isinstance(profile, dict) and profile.get("s") == "ok"):
            raise SystemExit(f"FYERS login failed ({profile}). Run  python fyers_auth.py  again, then retry.")
        name = (profile.get("data") or {}).get("name")
        say(f"FYERS login OK{f' ({name})' if name else ''}")

    today = clock().date()
    live_root = args.data_folder / "live_trading"
    if args.live_orders and not LiveSwitch(live_root).armed_for(today):
        raise SystemExit("--live-orders was given but the live switch is NOT armed for today.\n"
                         "Arm it first:  python scripts\\live_switch.py arm   (or run without --live-orders).")
    if args.live_orders:
        print("!" * 72)
        print("!!  LIVE ORDERS ARE ON: paper trades will also be sent to FYERS with REAL MONEY  !!")
        print("!" * 72)
    else:
        say("Broker orders: DRY RUN (orders that WOULD be sent are listed per index in data\\live_trading\\)")

    hub = SharedSocketHub(socket_factory or client.create_data_socket)
    contracts_db = args.data_folder / "database" / "paper_contracts.db"
    masters: dict = {}

    def master(name: str) -> dict:
        if raw_master is not None:
            return raw_master
        if name not in masters:
            say(f"Loading FYERS {name} contract list (first run of the day downloads it)...")
            masters[name] = load_fyers_master(name, args.data_folder / "raw" / "fyers", today=today)
        return masters[name]

    policy = LiveOrderPolicy()
    desks: list[IndexDesk] = []
    for prof in profiles:
        paper_dir = args.data_folder / "paper_trading" / prof.key
        legacy = args.data_folder / "paper_trading" / SETTINGS_FILE
        if legacy.exists() and not (paper_dir / SETTINGS_FILE).exists():
            paper_dir.mkdir(parents=True, exist_ok=True)
            (paper_dir / SETTINGS_FILE).write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")

        # 2. Contracts and lot size from FYERS
        contracts = sync_option_contracts(contracts_db, master(prof.master), underlying=prof.underlying, today=today)
        # 3. Settings (per index)
        settings = StrategySettingsStore(StrategySettings(), paper_dir).settings
        boxes = " + ".join(n for n, on in (("ATM", settings.use_atm), ("ATM+1", settings.use_atm_plus_1)) if on)
        say(f"{prof.label}: lot {contracts.lot_size}, expiry {contracts.nearest_expiry:%a %d %b}, "
            f"{settings.timeframe_minutes}-min, {settings.trade_direction}, {settings.entry_start}-{settings.entry_end}, "
            f"strikes {boxes or f'CALL {settings.call_strike} / PUT {settings.put_strike}'}")

        session = build_paper_session(
            client=client,
            config=PaperSessionConfig(
                lot_size=contracts.lot_size,
                resolution_minutes=settings.timeframe_minutes,
                database_path=contracts_db,
                output_dir=paper_dir,
                pending_journal_path=paper_dir / "pending_entries.csv",
                underlying_symbol=prof.spot_symbol,
            ),
            resolver=StrikeLadderResolver(OptionContractResolver(contracts_db), underlying=prof.underlying,
                                          strike_step=prof.strike_step),
            socket_factory=hub.factory,
        )
        if session.recovery is not None and session.recovery.open_trade_ids:
            say(f"{prof.label}: restored open paper trades: {', '.join(session.recovery.open_trade_ids)}")
            if session.recovery.stale_open_trade_ids:
                say(f"{prof.label}: WARNING trades from an EARLIER day are still open: "
                    f"{', '.join(session.recovery.stale_open_trade_ids)}")

        # Broker orders: DRY RUN unless armed today AND --live-orders.
        live_dir = live_root / prof.key
        if args.live_orders:
            gateway = FyersOrderGateway(client.model, journal_path=live_dir / "orders_log.csv",
                                        product_type=policy.product_type)
            order_sleep = time.sleep
        else:
            gateway = DryRunGateway(journal_path=live_dir / "orders_log.csv")
            order_sleep = lambda _seconds: None   # nothing to wait for in a dry run

        def option_price(symbol: str, _session=session) -> float:
            quote = _session.quote_cache.get_quote(symbol, decision_timestamp=int(clock().timestamp()),
                                                   max_exchange_age_seconds=5, max_receive_age_seconds=5.0)
            return float(quote["lp"])

        mirror = LiveOrderMirror(
            LimitOrderExecutor(gateway, policy, option_price, sleep=order_sleep),
            lot_size=contracts.lot_size, journal_path=live_dir / "live_orders.csv", mode=gateway.mode,
            on_alert=lambda text, label=prof.label: say(f"*** {label}: {text} ***"),
        )
        session.engine.recorder = MirroringRecorder(session.engine.recorder, mirror)

        # 4. Warm-up
        history = fetch_minute_history(client, prof.spot_symbol, resolution_minutes=settings.timeframe_minutes,
                                       now=clock())
        bars = session.pipeline.seed_history(prof.spot_symbol, history)
        say(f"{prof.label}: warm-up {len(history)} one-minute candles -> {bars} bars of history")
        desk = IndexDesk(prof, session, contracts, paper_dir, gateway, mirror)
        desks.append(desk)

        # 5. Chart data (futures volume, daily candles). Never stops trading.
        try:
            future = nearest_future(master(prof.master), prof.underlying, today)
            if future:
                desk.futures = FuturesMinuteRecorder(paper_dir, future)
                desk.futures.seed(fetch_minute_history(client, future, resolution_minutes=settings.timeframe_minutes,
                                                       now=clock()))
                if session.exit_manager is not None:          # FUTURE trailing-stop source reads these candles
                    from paper_trading.chart_feeds import read_candles
                    session.exit_manager.future_minutes_provider = lambda f=desk.futures: read_candles(f.file.path)
            save_daily_candles(client, paper_dir, spot=prof.spot_symbol, future=future, today=today,
                               pause=0.35 if sleep is time.sleep else 0)
            say(f"{prof.label}: chart data ready (volume from {future or 'no future found'}, daily candles)")
        except Exception as exc:
            say(f"{prof.label}: chart extras not loaded ({exc}). Trading is not affected.")

    def refresh_oi(desk: IndexDesk, now: datetime) -> None:
        """Option-chain open interest for the chart's OI profile, about once a minute."""
        model = getattr(client, "model", client)
        if not hasattr(model, "optionchain") or time.monotonic() - desk.last_oi < 60:
            return
        if now.weekday() >= 5 or not (dtime(9, 10) <= now.time() <= dtime(15, 35)):
            return
        desk.last_oi = time.monotonic()
        try:
            save_option_chain(model, desk.paper_dir, spot_symbol=desk.profile.spot_symbol, now=now)
            desk.oi_error = None
        except Exception as exc:
            if str(exc) != desk.oi_error:
                say(f"{desk.profile.label}: option-chain OI not updated ({exc}). Trading is not affected.")
            desk.oi_error = str(exc)

    # 6. Live (one FYERS connection for all indexes; futures ticks only feed the chart volume)
    def start_all() -> None:
        for desk in desks:
            desk.session.start()
        for desk in desks:
            if desk.futures is None:
                continue
            holder: dict = {}
            holder["socket"] = hub.factory(
                on_message=desk.futures.on_message,
                on_connect=lambda h=holder, sym=desk.futures.symbol: h["socket"].subscribe([sym]))
            holder["socket"].connect()
    threading.Thread(target=start_all, name="fyers-feed", daemon=True).start()
    say("Connecting to FYERS live data... leave this window open. (Ctrl+C to stop)")
    stop_at = dtime.fromisoformat(args.stop_at)
    last_status = 0.0
    try:
        while True:
            now = clock()
            if now.time() >= stop_at:
                say(f"Reached {args.stop_at}. Stopping.")
                break
            stamp = int(now.timestamp())
            for desk in desks:
                controls = desk.session.controls
                manager = desk.session.exit_manager
                forced_on = manager is None or manager.store.refresh().forced_exit_enabled
                if forced_on and controls.exits_due(stamp):
                    result = controls.close_due_positions(
                        desk.session.engine, timestamp=stamp, prices=desk.session.coordinator.marks_provider())
                    for strategy, exit_event in result.closed:
                        say(f"{desk.profile.label}: FORCE EXIT {strategy.value} at {getattr(exit_event, 'price', '?')}")
            for desk in desks:
                refresh_oi(desk, now)
            for desk in desks:
                silent = desk.silence_seconds(now)
                if silent is not None and silent > 60 and now.timestamp() - desk.last_silence_warning > 60:
                    say(f"WARNING {desk.profile.label}: no live price for "
                        f"{'over a minute' if silent == float('inf') else f'{int(silent)} s'}. "
                        "Check internet / FYERS. No new trades without fresh prices.")
                    desk.last_silence_warning = now.timestamp()
            if time.monotonic() - last_status >= args.status_every:
                for desk in desks:
                    status = desk.status(now.timestamp())
                    write_status(desk.paper_dir, status)
                    error = status["feed"]["last_error"]
                    if error and error != desk.reported_error:
                        say(f"{desk.profile.label}: FEED MESSAGE: {error}")
                        desk.reported_error = error
                last_status = time.monotonic()
            sleep(1)
    except KeyboardInterrupt:
        say("Stopped by you (Ctrl+C).")
    finally:
        for desk in desks:
            write_status(desk.paper_dir, desk.status())
            desk.session.close()
            desk.mirror.close()
            if desk.futures is not None:
                desk.futures._close_minute()
        say(f"Journals and status saved in {args.data_folder / 'paper_trading'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
