"""Broker orders: limit + buffer only, never market, switch OFF by default."""

import csv
from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from live_trading.executor import LimitOrderExecutor
from live_trading.gateway import DryRunGateway, FyersOrderGateway, OrderError
from live_trading.mirror import LiveOrderMirror, MirroringRecorder
from live_trading.orders import LiveOrderPolicy, limit_price, round_to_tick
from live_trading.switch import CONFIRM_PHRASE, LiveSwitch
from scripts.live_switch import main as switch_command

SYMBOL = "NSE:NIFTY26O2722000CE"


class FakeFyersModel:
    """Records every request. ``statuses`` = orderbook answers, one per state() call."""

    created = []   # every instance, so the autouse check below can inspect them all

    def __init__(self, statuses=(), place_response=None):
        FakeFyersModel.created.append(self)
        self.calls = []
        self.statuses = list(statuses)
        self.place_response = place_response
        self.last_qty = 0

    def place_order(self, data):
        self.calls.append(("place", dict(data)))
        self.last_qty = data["qty"]
        return self.place_response or {"s": "ok", "code": 1101, "message": "ok", "id": f"ORD{len(self.calls)}"}

    def modify_order(self, data):
        self.calls.append(("modify", dict(data)))
        return {"s": "ok", "code": 1102, "message": "modified", "id": data["id"]}

    def cancel_order(self, data):
        self.calls.append(("cancel", dict(data)))
        return {"s": "ok", "code": 1103, "message": "cancelled", "id": data["id"]}

    def orderbook(self, data):
        self.calls.append(("orderbook", dict(data)))
        status, filled, price, *msg = self.statuses.pop(0) if self.statuses else (6, 0, None)
        return {"s": "ok", "code": 200, "orderBook": [{
            "id": data["id"], "status": status, "filledQty": filled,
            "remainingQuantity": self.last_qty - filled, "tradedPrice": price, "message": msg[0] if msg else ""}]}

    def sent(self, kind):
        return [d for k, d in self.calls if k == kind]


@pytest.fixture(autouse=True)
def _never_market(request):
    """Every test: no request may ever be a market (2) or stop (3/4) order."""
    FakeFyersModel.created.clear()
    yield
    checked = 0
    for model in FakeFyersModel.created:
        for kind, data in model.calls:
            if kind in ("place", "modify"):
                assert data["type"] == 1, f"non-limit order sent: {data}"
                checked += 1
    request.node.user_properties.append(("orders_checked", checked))


def gateway(model, tmp_path):
    return FyersOrderGateway(model, journal_path=tmp_path / "orders_log.csv", sleep=lambda s: None)


def executor(model, tmp_path, prices=(100.0,), **policy):
    feed = list(prices)

    def price(symbol):
        if not feed:
            raise LookupError("stale")
        return feed.pop(0) if len(feed) > 1 else feed[0]
    return LimitOrderExecutor(gateway(model, tmp_path), LiveOrderPolicy(**policy), price, sleep=lambda s: None)


# ------------------------------------------------------------------ price rules

def test_limit_prices_round_to_tick_in_the_aggressive_direction():
    policy = LiveOrderPolicy()
    assert limit_price(101.52, "BUY", policy) == 102.55     # 102.52 -> up to 102.55
    assert limit_price(101.52, "SELL", policy) == 99.50     # 99.52  -> down to 99.50
    assert limit_price(1.0, "SELL", policy) == 0.05         # never zero or negative
    assert limit_price(100, "BUY", LiveOrderPolicy(buffer_unit="TICKS", entry_buffer=4)) == 100.20
    assert limit_price(200, "SELL", LiveOrderPolicy(buffer_unit="PERCENT", exit_buffer=1)) == 198.0
    assert round_to_tick(0.1 + 0.2, 0.05, "BUY") == 0.30     # no float drift


# ------------------------------------------------------------------- gateway

def test_place_sends_a_fyers_limit_order(tmp_path):
    model = FakeFyersModel()
    order_id = gateway(model, tmp_path).place_limit(SYMBOL, "BUY", 130, 101.55, "KQ_slot-1")
    data = model.sent("place")[0]
    assert order_id == "ORD1"
    assert data == {"symbol": SYMBOL, "qty": 130, "type": 1, "side": 1, "productType": "INTRADAY",
                    "limitPrice": 101.55, "stopPrice": 0, "validity": "DAY", "disclosedQty": 0,
                    "offlineOrder": False, "orderTag": "KQslot1"}
    rows = list(csv.DictReader((tmp_path / "orders_log.csv").open()))
    assert rows[0]["action"] == "PLACE" and rows[0]["mode"] == "LIVE"


def test_refused_and_unacknowledged_orders_raise_and_are_not_resent(tmp_path):
    with pytest.raises(OrderError, match="code -50"):
        gateway(FakeFyersModel(place_response={"s": "error", "code": -50, "message": "not allowed"}), tmp_path) \
            .place_limit(SYMBOL, "BUY", 65, 100, "KQ")
    model = FakeFyersModel(place_response={"s": "ok", "code": 201, "message": "not acknowledged"})
    with pytest.raises(OrderError, match="not acknowledged"):
        gateway(model, tmp_path).place_limit(SYMBOL, "BUY", 65, 100, "KQ")
    assert len(model.sent("place")) == 1


# ------------------------------------------------------------------ executor

def test_entry_filled_first_check(tmp_path):
    model = FakeFyersModel(statuses=[(2, 130, 101.0)])
    result = executor(model, tmp_path).execute(kind="ENTRY", symbol=SYMBOL, qty=130, lot_size=65)
    assert (result.status, result.filled_qty, result.avg_price) == ("FILLED", 130, 101.0)
    assert model.sent("place")[0]["limitPrice"] == 101.0 and model.sent("place")[0]["side"] == 1


def test_entry_chases_up_to_the_cap_then_cancels(tmp_path):
    model = FakeFyersModel(statuses=[(6, 0, None)] * 4)
    result = executor(model, tmp_path, prices=(100, 101, 103, 110)).execute(
        kind="ENTRY", symbol=SYMBOL, qty=65, lot_size=65)
    assert result.status == "NOT_FILLED"
    assert [d["limitPrice"] for d in model.sent("modify")] == [102.0, 104.0]   # capped at 100+3+1
    assert len(model.sent("cancel")) == 1


def test_partial_entry_keeps_the_filled_part(tmp_path):
    model = FakeFyersModel(statuses=[(6, 65, 100.5)] * 4)
    result = executor(model, tmp_path).execute(kind="ENTRY", symbol=SYMBOL, qty=130, lot_size=65)
    assert (result.status, result.filled_qty) == ("PARTIAL", 65)


def test_rejected_order_is_reported_not_retried(tmp_path):
    model = FakeFyersModel(statuses=[(5, 0, None, "RMS: insufficient funds")])
    result = executor(model, tmp_path).execute(kind="ENTRY", symbol=SYMBOL, qty=65, lot_size=65)
    assert result.status == "REJECTED" and "insufficient funds" in result.message
    assert len(model.sent("place")) == 1


def test_unfilled_exit_stays_working_with_an_alert_and_no_market_order(tmp_path):
    model = FakeFyersModel(statuses=[(6, 0, None)] * 4)
    result = executor(model, tmp_path, prices=(80, 79, 78, 77)).execute(
        kind="EXIT", symbol=SYMBOL, qty=65, lot_size=65)
    assert result.status == "EXIT_WORKING" and result.alert
    assert "No market order" in result.message
    assert model.sent("cancel") == []                         # the exit order is left working
    assert model.sent("place")[0]["side"] == -1 and model.sent("place")[0]["limitPrice"] == 78.0


def test_exit_without_fresh_price_uses_the_paper_exit_price(tmp_path):
    model = FakeFyersModel(statuses=[(2, 65, 79.0)])
    result = executor(model, tmp_path, prices=()).execute(kind="EXIT", symbol=SYMBOL, qty=65, lot_size=65,
                                                          reference=80.0)
    assert result.status == "FILLED" and model.sent("place")[0]["limitPrice"] == 78.0


def test_entry_without_fresh_price_is_not_sent(tmp_path):
    model = FakeFyersModel()
    result = executor(model, tmp_path, prices=()).execute(kind="ENTRY", symbol=SYMBOL, qty=65, lot_size=65)
    assert result.status == "NOT_PLACED" and model.calls == []


@pytest.mark.parametrize("qty, reason", [(100, "whole number of lots"), (65 * 11, "safety cap")])
def test_size_safety_checks(tmp_path, qty, reason):
    model = FakeFyersModel()
    result = executor(model, tmp_path).execute(kind="ENTRY", symbol=SYMBOL, qty=qty, lot_size=65)
    assert result.status == "NOT_PLACED" and reason in result.message and model.calls == []


def test_daily_order_cap(tmp_path):
    model = FakeFyersModel(statuses=[(2, 65, 100)] * 5)
    ex = executor(model, tmp_path, max_orders_per_day=2)
    statuses = [ex.execute(kind="ENTRY", symbol=SYMBOL, qty=65, lot_size=65).status for _ in range(3)]
    assert statuses == ["FILLED", "FILLED", "NOT_PLACED"]


# --------------------------------------------------------------------- mirror

@dataclass
class Position:
    symbol: str
    quantity: int
    entry_price: float


def record(qty=130):
    return SimpleNamespace(position=Position(SYMBOL, qty, 101.0), strategy_id=SimpleNamespace(value="KTMI_A"))


def exit_event(qty=130, price=120.0):
    return SimpleNamespace(quantity=qty, price=price, reason=SimpleNamespace(value="TARGET"))


def test_exit_is_skipped_when_the_entry_never_filled(tmp_path):
    model = FakeFyersModel(statuses=[(6, 0, None)] * 4)
    mirror = LiveOrderMirror(executor(model, tmp_path), lot_size=65, journal_path=tmp_path / "live.csv",
                             mode="LIVE", on_alert=lambda t: None, synchronous=True)
    mirror.on_open(record())
    mirror.on_exit(record(), exit_event())
    rows = list(csv.DictReader((tmp_path / "live.csv").open()))
    assert [(r["kind"], r["status"]) for r in rows] == [("ENTRY", "NOT_FILLED"), ("EXIT", "SKIPPED")]
    assert len(model.sent("place")) == 1


def test_exit_never_sells_more_than_was_bought(tmp_path):
    model = FakeFyersModel(statuses=[(6, 65, 101.0)] * 4 + [(2, 65, 119.0)])
    mirror = LiveOrderMirror(executor(model, tmp_path), lot_size=65, journal_path=tmp_path / "live.csv",
                             mode="LIVE", on_alert=lambda t: None, synchronous=True)
    mirror.on_open(record(130))                 # only 65 of 130 filled
    mirror.on_exit(record(130), exit_event(130))
    assert model.sent("place")[1]["qty"] == 65 and model.sent("place")[1]["side"] == -1
    assert mirror.holdings[SYMBOL] == 0


def test_dry_run_journals_the_whole_sequence_and_calls_nothing(tmp_path):
    dry = DryRunGateway(journal_path=tmp_path / "orders_log.csv")
    mirror = LiveOrderMirror(LimitOrderExecutor(dry, LiveOrderPolicy(), lambda s: 101.0, sleep=lambda s: None),
                             lot_size=65, journal_path=tmp_path / "live.csv", mode="DRY_RUN",
                             on_alert=lambda t: None, synchronous=True)
    mirror.on_open(record())
    mirror.on_exit(record(), exit_event())
    log = list(csv.DictReader((tmp_path / "orders_log.csv").open()))
    assert [(r["action"], r["side"], r["price"]) for r in log] == [
        ("WOULD_PLACE", "BUY", "102.0"), ("WOULD_PLACE", "SELL", "99.0")]
    assert all(r["mode"] == "DRY_RUN" for r in log)


def test_recorder_wrapper_forwards_everything(tmp_path):
    seen = []
    inner = SimpleNamespace(record_trade_open=lambda t: seen.append("open"),
                            record_trade_exit=lambda t, e: seen.append("exit"), signals_path="x")
    mirror = SimpleNamespace(on_open=lambda t: seen.append("m-open"), on_exit=lambda t, e: seen.append("m-exit"))
    wrapped = MirroringRecorder(inner, mirror)
    wrapped.record_trade_open(None)
    wrapped.record_trade_exit(None, None)
    assert seen == ["open", "m-open", "exit", "m-exit"] and wrapped.signals_path == "x"


# --------------------------------------------------------------------- switch

def test_switch_is_off_by_default_and_needs_the_exact_phrase(tmp_path):
    switch = LiveSwitch(tmp_path)
    today = date(2026, 10, 26)
    assert not switch.armed_for(today)
    with pytest.raises(ValueError):
        switch.arm(today, "yes")
    switch.arm(today, CONFIRM_PHRASE)
    assert switch.armed_for(today)
    assert not switch.armed_for(today + timedelta(days=1))   # expires next day
    switch.disarm()
    assert not switch.armed_for(today)


def test_switch_command(tmp_path, capsys):
    assert switch_command(["status", "--folder", str(tmp_path)]) == 0
    assert "OFF" in capsys.readouterr().out
    assert switch_command(["arm", "--folder", str(tmp_path)], ask=lambda _: "ok") == 1
    assert switch_command(["arm", "--folder", str(tmp_path)], ask=lambda _: CONFIRM_PHRASE) == 0
    assert "ON (armed)" in capsys.readouterr().out
    assert switch_command(["disarm", "--folder", str(tmp_path)]) == 0
    assert "OFF" in capsys.readouterr().out
