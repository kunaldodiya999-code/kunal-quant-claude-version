"""Monday runner, end to end with a pretend FYERS (no network, no orders)."""

import csv
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import paper_trading.session as session_module
from paper_trading.engine import PaperStrategyId
from paper_trading.live_support import sync_nifty_option_contracts
from paper_trading.signals import PaperSignal
from scripts.run_paper_session import main

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 10, 26)
EXPIRY_EPOCH = int(datetime(2026, 10, 27, 15, 30, tzinfo=IST).timestamp())


def master():
    rows = {}
    for strike in range(21800, 22251, 50):
        for typ in ("CE", "PE"):
            sym = f"NSE:NIFTY26O27{strike}{typ}"
            rows[sym] = {"symTicker": sym, "underSym": "NIFTY", "exInstType": 14, "expiryDate": str(EXPIRY_EPOCH),
                         "strikePrice": float(strike), "optType": typ, "minLotSize": 65, "tickSize": 0.05,
                         "exchange": 10, "exchangeName": "NSE", "fyToken": sym}
    rows["NSE:BANKNIFTY26O2750000CE"] = dict(rows["NSE:NIFTY26O2722000CE"], underSym="BANKNIFTY",
                                             symTicker="NSE:BANKNIFTY26O2750000CE")
    return rows


class FakeClient:
    def history(self, symbol, *, resolution, range_from, range_to):
        start = int(datetime(2026, 10, 23, 9, 15, tzinfo=IST).timestamp())     # Friday
        return {"s": "ok", "candles": [[start + 60 * i, 22000, 22001, 21999, 22000, 0] for i in range(375)]}


class FakeSocket:
    def __init__(self, **callbacks):
        self.cb = callbacks
        self.subscribed = []

    def connect(self):
        self.cb["on_connect"]()

    def subscribe(self, symbols, data_type):
        self.subscribed += symbols

    def close(self):
        pass


def test_contract_sync_reads_lot_size_and_expiry_from_fyers(tmp_path):
    result = sync_nifty_option_contracts(tmp_path / "c.db", master(), today=MONDAY)
    assert (result.contracts, result.lot_size, result.nearest_expiry) == (20, 65, date(2026, 10, 27))


def test_contract_sync_ignores_expired_contracts(tmp_path):
    with pytest.raises(RuntimeError):
        sync_nifty_option_contracts(tmp_path / "c.db", master(), today=date(2026, 10, 28))


def test_missing_login_files_give_plain_instructions(tmp_path):
    with pytest.raises(SystemExit, match="fyers_auth.py"):
        main(["--credentials-folder", str(tmp_path), "--data-folder", str(tmp_path)])


def run_day(tmp_path, monkeypatch, extra_args=(), client=None):
    """Pretend Monday 10:00-10:12 with one LONG signal on the 10:00 3-minute bar."""
    def one_signal(bars, *, paper_config, **kwargs):
        last = bars[-1]
        if last.timestamp == int(datetime(2026, 10, 26, 10, 0, tzinfo=IST).timestamp()):
            return [PaperSignal(PaperStrategyId.STRATEGY_A, "LONG", last.timestamp, len(bars) - 1, "TEST")]
        return []
    monkeypatch.setitem(session_module.SIGNAL_PROFILES, "UNI_LITE_CORE", one_signal)

    sockets = []

    def socket_factory(**callbacks):
        sockets.append(FakeSocket(**callbacks))
        return sockets[-1]

    # Scripted day: start 10:00, each sleep() = 1 minute of live ticks.
    t = {"now": datetime(2026, 10, 26, 10, 0, 1, tzinfo=IST)}
    monkeypatch.setattr("market_data.fyers_quote_cache.time.time", lambda: t["now"].timestamp())
    monkeypatch.setattr("paper_trading.pending_entry_orchestrator.datetime",
                        type("D", (datetime,), {"now": staticmethod(lambda tz=None: t["now"])}))
    monkeypatch.setattr("live_trading.switch.datetime",
                        type("D2", (datetime,), {"now": staticmethod(lambda tz=None: t["now"])}), raising=False)

    def tick(symbol, price, at):
        return {"symbol": symbol, "ltp": price, "last_traded_time": int(at.timestamp()),
                "exch_feed_time": int(at.timestamp()), "type": "sf"}

    def sleep(_seconds):
        if not sockets:
            return
        on_message = sockets[0].cb["on_message"]
        on_message(tick("NSE:NIFTY50-INDEX", 22010, t["now"]))
        for sym in sockets[0].subscribed:
            if sym.endswith(("CE", "PE")):
                on_message(tick(sym, 101.5, t["now"]))
        t["now"] += timedelta(minutes=1)

    main(["--data-folder", str(tmp_path), "--stop-at", "10:12", "--status-every", "0", *extra_args],
         client=client or FakeClient(), raw_master=master(), socket_factory=socket_factory,
         clock=lambda: t["now"], sleep=sleep)
    return sockets


def rows(path):
    return list(csv.DictReader(path.open()))


def test_paper_day_end_to_end(tmp_path, monkeypatch):
    sockets = run_day(tmp_path, monkeypatch)
    status = json.loads((tmp_path / "paper_trading" / "live_status.json").read_text())
    assert status["mode"] == "PAPER" and status["orders_mode"] == "DRY_RUN"
    assert status["contracts"] == {"nearest_expiry": "2026-10-27", "lot_size": 65}
    assert status["ladders"]["call"][1] == {"choice": "ATM", "strike": 22000}
    assert [p["symbol"] for p in status["positions"]] == ["NSE:NIFTY26O2722000CE"]
    assert status["positions"][0]["side"] == "BUY CALL"
    assert "NSE:NIFTY26O2722000CE" in sockets[0].subscribed
    trades = (tmp_path / "paper_trading" / "trade_events.csv").read_text()
    assert "NSE:NIFTY26O2722000CE" in trades
    # Dry run: the order that WOULD be sent, nothing sent.
    log = rows(tmp_path / "live_trading" / "orders_log.csv")
    assert [(r["action"], r["symbol"], r["side"], r["qty"], r["price"]) for r in log] == [
        ("WOULD_PLACE", "NSE:NIFTY26O2722000CE", "BUY", "130", "102.5")]
    assert rows(tmp_path / "live_trading" / "live_orders.csv")[0]["mode"] == "DRY_RUN"


def test_live_orders_refused_unless_switch_armed(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="NOT armed"):
        run_day(tmp_path, monkeypatch, ["--live-orders"])


def test_armed_live_day_sends_one_limit_buy(tmp_path, monkeypatch):
    from live_trading.switch import CONFIRM_PHRASE, LiveSwitch
    from tests.test_live_orders import FakeFyersModel
    LiveSwitch(tmp_path / "live_trading").arm(MONDAY, CONFIRM_PHRASE)
    model = FakeFyersModel(statuses=[(2, 130, 102.0)])
    client = FakeClient()
    client.model = model
    monkeypatch.setattr("live_trading.executor.time.sleep", lambda s: None, raising=False)
    monkeypatch.setattr("scripts.run_paper_session.time.sleep", lambda s: None)
    run_day(tmp_path, monkeypatch, ["--live-orders"], client=client)
    placed = model.sent("place")
    assert len(placed) == 1
    assert (placed[0]["symbol"], placed[0]["side"], placed[0]["type"], placed[0]["qty"], placed[0]["limitPrice"]) == (
        "NSE:NIFTY26O2722000CE", 1, 1, 130, 102.5)
    live = rows(tmp_path / "live_trading" / "live_orders.csv")
    assert (live[0]["mode"], live[0]["status"], live[0]["filled_qty"]) == ("LIVE", "FILLED", "130")
